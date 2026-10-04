"""LLM provider adapters for PVE2LLM (Winky): Ollama, OpenAI, Anthropic.

Each adapter takes the same provider-neutral conversation (see agent.py) and
returns a :class:`ProviderReply`. Only ``httpx`` is used — no provider SDKs.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Cloud metadata endpoints must never be reachable through a configured
# provider base_url (SSRF defense). Localhost and private ranges stay allowed
# so a local Ollama works.
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
    "metadata.azure.com",
}
_BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}


def validate_base_url(url: str) -> str:
    """Validate a configured provider base_url. Returns the normalized URL.

    Raises ``ValueError`` on a non-http(s) scheme, a missing host, or a cloud
    metadata host/link-local address.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("base_url must include a host")
    if host in _BLOCKED_HOSTNAMES:
        raise ValueError(f"base_url host {host!r} is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_link_local or ip in _BLOCKED_IPS):
        raise ValueError(f"base_url address {host!r} is not allowed")
    return url.rstrip("/")



@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


def _base_url(config: Any) -> str:
    configured = (getattr(config, "base_url", "") or "").strip()
    provider = (getattr(config, "provider", "") or "ollama").lower()
    if configured:
        url = validate_base_url(configured)
    else:
        url = DEFAULT_BASE_URLS.get(provider, "").rstrip("/")
    # OpenAI-compatible servers (vLLM / llama.cpp / Unsloth, …) serve the API
    # under /v1; add it when the user gave a bare host. A path already present
    # (e.g. ".../v1" or ".../api") is left untouched.
    if provider == "openai" and url and urlparse(url).path in ("", "/"):
        url = url.rstrip("/") + "/v1"
    return url


def effective_base_url(config: Any) -> str:
    """The base_url actually used, for display/diagnostics (never raises)."""
    try:
        return _base_url(config)
    except ValueError:
        return ""


def requires_api_key(config: Any) -> bool:
    """Whether the configured provider must have an API key.

    Anthropic always needs one. OpenAI needs one for the hosted API, but a
    custom ``base_url`` points at a self-hosted OpenAI-compatible server
    (vLLM, llama.cpp, Unsloth) that normally has no key — so it is optional
    there. Ollama never needs one.
    """
    provider = (getattr(config, "provider", "") or "ollama").lower()
    if provider == "anthropic":
        return True
    if provider == "openai":
        configured = (getattr(config, "base_url", "") or "").strip()
        if not configured:
            return True  # falls back to the hosted OpenAI API
        try:
            return validate_base_url(configured) == DEFAULT_BASE_URLS["openai"].rstrip("/")
        except ValueError:
            return True
    return False


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": value}
    return {}


def provider_requires_key(provider: str) -> bool:
    return (provider or "").lower() in ("openai", "anthropic")


async def chat(config: Any, messages: list[dict], tools: list[dict]) -> ProviderReply:
    """Dispatch to the configured provider."""
    provider = (getattr(config, "provider", "") or "ollama").lower()
    if provider == "openai":
        return await _openai(config, messages, tools)
    if provider == "anthropic":
        return await _anthropic(config, messages, tools)
    return await _ollama(config, messages, tools)


# --- Ollama ---------------------------------------------------------------


def _ollama_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [
                        {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in m["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            out.append({"role": "tool", "content": m.get("content", "")})
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


async def _ollama(config: Any, messages: list[dict], tools: list[dict]) -> ProviderReply:
    body: dict[str, Any] = {
        "model": getattr(config, "model", ""),
        "messages": _ollama_messages(messages),
        "stream": False,
    }
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(_base_url(config) + "/api/chat", json=body)
        response.raise_for_status()
        data = response.json()
    message = data.get("message") or {}
    calls = [
        ToolCall(
            id=f"call_{i}",
            name=(tc.get("function") or {}).get("name", ""),
            arguments=_as_dict((tc.get("function") or {}).get("arguments")),
        )
        for i, tc in enumerate(message.get("tool_calls") or [])
    ]
    return ProviderReply(content=message.get("content") or "", tool_calls=calls)


# --- OpenAI-compatible ----------------------------------------------------


def _openai_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": m.get("content", ""),
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


async def _openai(config: Any, messages: list[dict], tools: list[dict]) -> ProviderReply:
    headers = {"Content-Type": "application/json"}
    api_key = getattr(config, "api_key", "") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body: dict[str, Any] = {
        "model": getattr(config, "model", ""),
        "messages": _openai_messages(messages),
        "temperature": getattr(config, "temperature", 0.2),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _base_url(config) + "/chat/completions", json=body, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    message = ((data.get("choices") or [{}])[0]).get("message") or {}
    calls = [
        ToolCall(
            id=tc.get("id") or f"call_{i}",
            name=(tc.get("function") or {}).get("name", ""),
            arguments=_as_dict((tc.get("function") or {}).get("arguments")),
        )
        for i, tc in enumerate(message.get("tool_calls") or [])
    ]
    return ProviderReply(content=message.get("content") or "", tool_calls=calls)


# --- Anthropic ------------------------------------------------------------


def _anthropic_messages(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system_parts: list[str] = []
    conversation: list[dict] = []
    pending_tool_results: list[dict] = []

    def flush_tool_results() -> None:
        if pending_tool_results:
            conversation.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for m in messages:
        role = m.get("role")
        if role == "system":
            system_parts.append(m.get("content", ""))
            continue
        if role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id"),
                    "content": m.get("content", ""),
                }
            )
            continue
        flush_tool_results()
        if role == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    }
                )
            conversation.append(
                {"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]}
            )
        else:
            conversation.append({"role": "user", "content": m.get("content", "")})
    flush_tool_results()
    system = "\n\n".join(system_parts) if system_parts else None
    return system, conversation


async def _anthropic(config: Any, messages: list[dict], tools: list[dict]) -> ProviderReply:
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    api_key = getattr(config, "api_key", "") or ""
    if api_key:
        headers["x-api-key"] = api_key
    system, conversation = _anthropic_messages(messages)
    body: dict[str, Any] = {
        "model": getattr(config, "model", ""),
        "max_tokens": getattr(config, "max_tokens", 1024),
        "messages": conversation,
    }
    if system:
        body["system"] = system
    temperature = getattr(config, "temperature", None)
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _base_url(config) + "/v1/messages", json=body, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    content = ""
    calls: list[ToolCall] = []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            content += block.get("text", "")
        elif block.get("type") == "tool_use":
            calls.append(
                ToolCall(
                    id=block.get("id") or f"call_{len(calls)}",
                    name=block.get("name", ""),
                    arguments=_as_dict(block.get("input")),
                )
            )
    return ProviderReply(content=content, tool_calls=calls)
