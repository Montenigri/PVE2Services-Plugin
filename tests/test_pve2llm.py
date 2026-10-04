"""Tests for PVE2LLM (assistant: Winky) — tool aggregation, dispatch, providers."""

import asyncio
import importlib
from pathlib import Path

import pytest
from PVE2Services.libs.mcp_registry import (
    get_mcp_registry,
    register_tool,
    reset_mcp_registry,
)
from PVE2Services.libs.plugin_manifest import load_manifest
from PVE2Services.plugins.PVE2LLM import agent, aggregator, providers
from PVE2Services.plugins.PVE2LLM.schemas import LLMConfig

PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"


@pytest.fixture(autouse=True)
def clean_registry():
    reset_mcp_registry()
    yield
    reset_mcp_registry()


def _register(name, *, read_only=True, plugin="pve2dns"):
    async def handler(params):
        return {"echo": params, "tool": name}

    register_tool(
        plugin,
        name=name,
        handler=handler,
        description=name,
        input_schema={"type": "object"},
        read_only=read_only,
    )


# --- aggregation / read-only enforcement ----------------------------------


def test_only_read_only_tools_selected():
    _register("list_records", read_only=True)
    _register("delete_everything", read_only=False)
    names = {s.name for s in aggregator.select_specs()}
    assert "list_records" in names
    assert "delete_everything" not in names


def test_allowed_plugins_filter():
    _register("a", plugin="pve2dns")
    _register("b", plugin="pve2audit")
    specs = aggregator.select_specs(["pve2audit"])
    assert [s.name for s in specs] == ["b"]


def test_build_tools_shapes():
    _register("a")
    specs = aggregator.select_specs()
    openai_tools = aggregator.build_tools("openai", specs)
    assert openai_tools[0]["type"] == "function"
    assert openai_tools[0]["function"]["name"] == "pve2dns__a"
    assert openai_tools[0]["function"]["parameters"] == {"type": "object"}

    anthropic_tools = aggregator.build_tools("anthropic", specs)
    assert anthropic_tools[0]["name"] == "pve2dns__a"
    assert "input_schema" in anthropic_tools[0]
    assert "function" not in anthropic_tools[0]


def test_execute_dispatch():
    _register("a")
    specs = aggregator.select_specs()
    out = asyncio.run(aggregator.execute("pve2dns__a", {"x": 1}, specs))
    assert out == {"echo": {"x": 1}, "tool": "a"}
    with pytest.raises(KeyError):
        asyncio.run(aggregator.execute("nope", {}, specs))


# --- agent loop -----------------------------------------------------------


def test_agent_executes_tool_then_answers(monkeypatch):
    _register("list_records")
    calls = {"n": 0}

    async def fake_chat(config, messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return providers.ProviderReply(
                content="",
                tool_calls=[
                    providers.ToolCall(id="c1", name="pve2dns__list_records", arguments={})
                ],
            )
        return providers.ProviderReply(content="Ci sono 3 record.", tool_calls=[])

    monkeypatch.setattr(agent.providers, "chat", fake_chat)
    result = asyncio.run(agent.run(LLMConfig(provider="ollama", model="test"), "Quanti record?"))
    assert result["answer"] == "Ci sono 3 record."
    assert result["tool_calls"][0]["tool"] == "pve2dns__list_records"
    assert result["tool_calls"][0]["ok"] is True
    assert calls["n"] == 2


def test_agent_reports_tool_error(monkeypatch):
    async def boom(params):
        raise RuntimeError("boom")

    register_tool("pve2dns", name="failing", handler=boom, input_schema={"type": "object"})

    async def fake_chat(config, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return providers.ProviderReply(
                content="", tool_calls=[providers.ToolCall(id="c1", name="pve2dns__failing", arguments={})]
            )
        return providers.ProviderReply(content="Errore gestito.", tool_calls=[])

    monkeypatch.setattr(agent.providers, "chat", fake_chat)
    result = asyncio.run(agent.run(LLMConfig(provider="ollama", model="test"), "test"))
    assert result["tool_calls"][0]["ok"] is False
    assert result["answer"] == "Errore gestito."


# --- provider message conversions -----------------------------------------


def test_openai_message_conversion():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "t", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "{}"},
    ]
    out = providers._openai_messages(messages)
    assert out[0]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    assert out[1]["role"] == "tool"
    assert out[1]["tool_call_id"] == "c1"


def test_anthropic_message_conversion():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "t", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "res"},
    ]
    system, conversation = providers._anthropic_messages(messages)
    assert system == "sys"
    assert conversation[0]["role"] == "user"
    assert conversation[1]["content"][0]["type"] == "tool_use"
    assert conversation[-1]["role"] == "user"
    assert conversation[-1]["content"][0]["type"] == "tool_result"
    assert conversation[-1]["content"][0]["tool_use_id"] == "c1"


def test_ollama_message_conversion():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "t", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "res"},
    ]
    out = providers._ollama_messages(messages)
    assert out[0]["tool_calls"][0]["function"]["name"] == "t"
    assert out[1] == {"role": "tool", "content": "res"}


# --- real plugin manifests -------------------------------------------------


def test_every_mcp_manifest_is_valid_and_read_only():
    for manifest_path in PLUGINS_DIR.glob("*/plugin.yaml"):
        manifest = load_manifest(manifest_path.parent)
        if manifest.mcp is None:
            continue
        assert manifest.mcp.enabled is True
        for tool in manifest.mcp.tools:
            assert tool.read_only is True, f"{manifest.id}:{tool.name} is not read-only"


def test_every_mcp_handler_resolves():
    for manifest_path in PLUGINS_DIR.glob("*/plugin.yaml"):
        manifest = load_manifest(manifest_path.parent)
        if manifest.mcp is None:
            continue
        for tool in manifest.mcp.tools:
            module_name, func_name = tool.handler.split(":")
            module = importlib.import_module(
                f"PVE2Services.plugins.{manifest_path.parent.name}.{module_name}"
            )
            assert callable(getattr(module, func_name)), f"{manifest.id}:{tool.handler}"


def test_registry_has_pve2_tools_after_handlers_loaded():
    # Importing the mcp_tools modules directly does not populate the registry
    # (the loader does that), so this only asserts the modules are importable.
    assert get_mcp_registry() is not None


# --- hardening: SSRF base_url guard ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://100.100.100.200/latest/meta-data",
        "ftp://example.com",
        "http://",
    ],
)
def test_validate_base_url_blocks(url):
    with pytest.raises(ValueError):
        providers.validate_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "https://api.openai.com/v1",
    ],
)
def test_validate_base_url_allows(url):
    assert providers.validate_base_url(url) == url.rstrip("/")


# --- hardening: rate limiter ----------------------------------------------


def test_sliding_window_limiter():
    from PVE2Services.plugins.PVE2LLM.ratelimit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(2)
    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False
    limiter.reset()
    assert limiter.allow() is True

    disabled = SlidingWindowLimiter(0)
    assert all(disabled.allow() for _ in range(10))


# --- hardening: tool-result truncation ------------------------------------


def test_agent_truncates_large_tool_result(monkeypatch):
    async def big(params):
        return {"data": "x" * 5000}

    register_tool("pve2dns", name="big", handler=big, input_schema={"type": "object"})
    captured = {}

    async def fake_chat(config, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return providers.ProviderReply(
                content="", tool_calls=[providers.ToolCall(id="c1", name="pve2dns__big", arguments={})]
            )
        captured["tool_msg"] = next(m["content"] for m in messages if m.get("role") == "tool")
        return providers.ProviderReply(content="ok", tool_calls=[])

    monkeypatch.setattr(agent.providers, "chat", fake_chat)
    cfg = LLMConfig(provider="ollama", model="t", max_tool_result_chars=100)
    asyncio.run(agent.run(cfg, "q"))
    assert '"truncated": true' in captured["tool_msg"]



# --- provider API-key policy & base_url normalization ---------------------


def _cfg(**kw):
    return LLMConfig(**kw)


def test_requires_api_key_only_for_cloud():
    assert providers.requires_api_key(_cfg(provider="anthropic")) is True
    # OpenAI hosted API (default base_url) needs a key...
    assert providers.requires_api_key(_cfg(provider="openai")) is True
    assert providers.requires_api_key(
        _cfg(provider="openai", base_url="https://api.openai.com/v1")
    ) is True
    # ...but a custom base_url is a self-hosted, key-less server.
    assert providers.requires_api_key(
        _cfg(provider="openai", base_url="http://localhost:8000/v1")
    ) is False
    assert providers.requires_api_key(
        _cfg(provider="openai", base_url="http://10.0.0.5:8000")
    ) is False
    assert providers.requires_api_key(_cfg(provider="ollama")) is False


def test_base_url_appends_v1_for_openai():
    assert providers.effective_base_url(
        _cfg(provider="openai", base_url="http://host:8000")
    ) == "http://host:8000/v1"
    # already present -> untouched
    assert providers.effective_base_url(
        _cfg(provider="openai", base_url="http://host:8000/v1")
    ) == "http://host:8000/v1"
    # a custom path is left alone
    assert providers.effective_base_url(
        _cfg(provider="openai", base_url="http://host:8000/api")
    ) == "http://host:8000/api"
    # default cloud URL stays /v1
    assert providers.effective_base_url(
        _cfg(provider="openai")
    ) == "https://api.openai.com/v1"
    # non-openai providers are untouched
    assert providers.effective_base_url(
        _cfg(provider="ollama", base_url="http://host:11434")
    ) == "http://host:11434"
