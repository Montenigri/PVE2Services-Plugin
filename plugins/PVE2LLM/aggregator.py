"""Aggregate read-only MCP tools and dispatch them in-process.

PVE2LLM (Winky) never talks MCP over the network: the core plugin loader wires
every plugin's declared ``mcp:`` tools into an in-process registry and this
module turns them into the provider-specific tool schema, resolves a tool call
back to its spec and executes the handler read-only.
"""

from __future__ import annotations

from typing import Any

from PVE2Services.libs.mcp_registry import MCPToolSpec, get_mcp_registry


def select_specs(allowed_plugins: list[str] | None = None) -> list[MCPToolSpec]:
    """Read-only tools from the registry, optionally limited to some plugins."""
    specs = get_mcp_registry().all(read_only_only=True)
    if allowed_plugins:
        allowed = {p.strip().lower() for p in allowed_plugins if p and p.strip()}
        specs = [s for s in specs if s.plugin_id in allowed]
    return specs


def provider_tool_name(spec: MCPToolSpec) -> str:
    """Globally unique, provider-safe tool name (``plugin__tool``)."""
    return f"{spec.plugin_id}__{spec.name}"


def _parameters(spec: MCPToolSpec) -> dict[str, Any]:
    return spec.input_schema or {"type": "object", "properties": {}}


def build_tools(provider: str, specs: list[MCPToolSpec]) -> list[dict[str, Any]]:
    """Build the tool definitions in the shape the provider expects."""
    provider = (provider or "ollama").lower()
    if provider == "anthropic":
        return [
            {
                "name": provider_tool_name(s),
                "description": s.description or s.name,
                "input_schema": _parameters(s),
            }
            for s in specs
        ]
    # OpenAI and Ollama share the function-calling schema.
    return [
        {
            "type": "function",
            "function": {
                "name": provider_tool_name(s),
                "description": s.description or s.name,
                "parameters": _parameters(s),
            },
        }
        for s in specs
    ]


def resolve_spec(
    provider_name: str, specs: list[MCPToolSpec]
) -> MCPToolSpec | None:
    for spec in specs:
        if provider_tool_name(spec) == provider_name:
            return spec
    return None


async def execute(
    provider_name: str,
    arguments: dict[str, Any] | None,
    specs: list[MCPToolSpec],
) -> Any:
    """Execute one tool call in-process (read-only). Raises on unknown tool."""
    spec = resolve_spec(provider_name, specs)
    if spec is None:
        raise KeyError(f"Unknown tool {provider_name!r}")
    handler = get_mcp_registry().get_handler(spec.key)
    if handler is None:
        raise KeyError(f"No handler registered for tool {spec.key!r}")
    return await handler(arguments or {})
