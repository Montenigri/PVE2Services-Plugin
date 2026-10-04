"""PVE2LLM — the Winky assistant.

Winky is an in-process MCP client: it reads the read-only tools every plugin
declares in its ``mcp:`` manifest block, exposes them to an LLM provider
(Ollama, OpenAI or Anthropic) and answers questions about the cluster without
ever mutating it.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:  # pragma: no cover
    ConnectorConfig = None

try:
    from PVE2Services.libs.audit import audit
except ImportError:  # pragma: no cover
    audit = None

from .agent import DEFAULT_SYSTEM_PROMPT, run
from .aggregator import select_specs
from .frontend import build_page
from .providers import chat as provider_chat
from .providers import effective_base_url, requires_api_key
from .ratelimit import SlidingWindowLimiter
from .schemas import ChatRequest, LLMConfig

logger = logging.getLogger("pve2llm")

PLUGIN_ID = "pve2llm"
ASSISTANT_NAME = "Winky"
_MASK = "********"

_limiter = SlidingWindowLimiter(20)


def _limiter_for(max_per_minute: int) -> SlidingWindowLimiter:
    global _limiter
    if _limiter.max_per_minute != max_per_minute:
        _limiter = SlidingWindowLimiter(max_per_minute)
    return _limiter


def _load_config(config_manager) -> LLMConfig:
    if config_manager is None:
        return LLMConfig()
    raw = config_manager.get_config(PLUGIN_ID) or {}
    allowed = raw.get("allowed_plugins") or []
    if isinstance(allowed, str):
        allowed = [p.strip() for p in allowed.split(",") if p.strip()]
    try:
        max_turns = int(raw.get("max_turns") or 5)
    except (TypeError, ValueError):
        max_turns = 5
    try:
        max_tokens = int(raw.get("max_tokens") or 1024)
    except (TypeError, ValueError):
        max_tokens = 1024
    try:
        temperature = float(raw.get("temperature") if raw.get("temperature") is not None else 0.2)
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        rate_limit = int(
            raw.get("rate_limit_per_minute")
            if raw.get("rate_limit_per_minute") is not None
            else 20
        )
    except (TypeError, ValueError):
        rate_limit = 20
    try:
        max_result = int(
            raw.get("max_tool_result_chars")
            if raw.get("max_tool_result_chars") is not None
            else 20000
        )
    except (TypeError, ValueError):
        max_result = 20000
    return LLMConfig(
        enabled=bool(raw.get("enabled")),
        provider=raw.get("provider") or "ollama",
        base_url=raw.get("base_url") or "",
        model=raw.get("model") or "",
        api_key=raw.get("api_key") or "",
        max_turns=max_turns,
        max_tokens=max_tokens,
        temperature=temperature,
        system_prompt=raw.get("system_prompt") or "",
        allowed_plugins=allowed,
        rate_limit_per_minute=rate_limit,
        max_tool_result_chars=max_result,
    )


def load_plugin(app: FastAPI):
    config_manager = None
    if ConnectorConfig:
        try:
            config_manager = ConnectorConfig()
        except Exception:  # pragma: no cover
            logger.warning("ConnectorConfig unavailable for pve2llm")

    @app.get(f"/api/plugins/{PLUGIN_ID}/info")
    async def plugin_info():
        return {
            "plugin": PLUGIN_ID,
            "name": "PVE2 LLM",
            "assistant_name": ASSISTANT_NAME,
            "version": "0.1.0",
            "description": f"{ASSISTANT_NAME} — assistente LLM in sola lettura sui dati dei plugin PVE2",
            "status": "active",
        }

    @app.get(f"/api/plugins/{PLUGIN_ID}/config")
    async def get_config():
        if config_manager is None:
            return {"error": "Config manager unavailable"}
        cfg = _load_config(config_manager)
        safe = cfg.model_dump()
        if safe.get("api_key"):
            safe["api_key"] = _MASK
        return {
            "configured": bool(cfg.provider and cfg.model),
            "assistant_name": ASSISTANT_NAME,
            "config": safe,
            "sync_state": config_manager.get_sync_state(PLUGIN_ID),
        }

    @app.post(f"/api/plugins/{PLUGIN_ID}/config")
    async def save_config(body: LLMConfig):
        if config_manager is None:
            return {"error": "Config manager unavailable"}
        existing = config_manager.get_config(PLUGIN_ID) or {}
        data = body.model_dump()
        if data.get("api_key") in ("", _MASK):
            data["api_key"] = existing.get("api_key", "")
        saved = config_manager.save_config(PLUGIN_ID, data, body.enabled)
        if audit:
            try:
                audit.log(
                    PLUGIN_ID,
                    "INFO",
                    "Config saved",
                    detail=f"provider: {body.provider}\nmodel: {body.model}\nenabled: {body.enabled}",
                )
            except Exception:  # pragma: no cover
                pass
        return {"saved": saved, "connector": PLUGIN_ID, "assistant_name": ASSISTANT_NAME}

    @app.post(f"/api/plugins/{PLUGIN_ID}/test")
    async def test_provider():
        cfg = _load_config(config_manager)
        if not cfg.model:
            return {"connected": False, "error": "Model not configured"}
        if requires_api_key(cfg) and not cfg.api_key:
            return {"connected": False, "error": f"{cfg.provider} requires an API key"}
        target = effective_base_url(cfg)
        try:
            reply = await provider_chat(
                cfg,
                [
                    {"role": "system", "content": "Rispondi solo con: pong"},
                    {"role": "user", "content": "ping"},
                ],
                [],
            )
            return {
                "connected": True,
                "provider": cfg.provider,
                "model": cfg.model,
                "base_url": target,
                "reply": (reply.content or "")[:200],
            }
        except httpx.HTTPStatusError as exc:
            detail = ""
            if exc.response is not None:
                detail = exc.response.text[:300]
            return {
                "connected": False,
                "provider": cfg.provider,
                "base_url": target,
                "error": str(exc) + (f" — {detail}" if detail else ""),
            }
        except Exception as exc:  # noqa: BLE001 - surface provider errors
            return {
                "connected": False,
                "provider": cfg.provider,
                "base_url": target,
                "error": str(exc),
            }

    @app.post(f"/api/plugins/{PLUGIN_ID}/sync")
    async def trigger_sync():
        specs = select_specs(_load_config(config_manager).allowed_plugins)
        return {
            "synced": True,
            "message": "PVE2LLM is read-only — nothing to sync",
            "tools_available": len(specs),
        }

    @app.get(f"/api/plugins/{PLUGIN_ID}/tools")
    async def list_tools():
        specs = select_specs(_load_config(config_manager).allowed_plugins)
        return {
            "count": len(specs),
            "assistant_name": ASSISTANT_NAME,
            "tools": [
                {
                    "plugin_id": s.plugin_id,
                    "name": s.name,
                    "description": s.description,
                    "capability": s.capability,
                    "input_schema": s.input_schema,
                }
                for s in specs
            ],
        }

    @app.post(f"/api/plugins/{PLUGIN_ID}/chat")
    async def chat(body: ChatRequest):
        cfg = _load_config(config_manager)
        if not cfg.model:
            raise HTTPException(status_code=503, detail="Winky non è configurato: imposta provider e modello")
        if requires_api_key(cfg) and not cfg.api_key:
            raise HTTPException(status_code=503, detail=f"{cfg.provider} richiede una API key")
        if not body.message.strip():
            raise HTTPException(status_code=400, detail="Messaggio vuoto")
        if not _limiter_for(cfg.rate_limit_per_minute).allow():
            raise HTTPException(
                status_code=429,
                detail="Troppe richieste a Winky: riprova tra poco",
            )
        try:
            result = await run(cfg, body.message, body.history)
        except Exception as exc:  # noqa: BLE001 - return provider errors to the UI
            logger.exception("Winky chat failed")
            raise HTTPException(status_code=502, detail=f"Errore del provider: {exc}") from exc
        result["assistant_name"] = ASSISTANT_NAME
        return result

    @app.get(f"/api/plugins/{PLUGIN_ID}/system-prompt")
    async def system_prompt():
        return {"default": DEFAULT_SYSTEM_PROMPT}

    @app.get(f"/admin/{PLUGIN_ID}", response_class=HTMLResponse)
    async def admin_page():
        return HTMLResponse(content=build_page(assistant_name=ASSISTANT_NAME))
