"""Configuration and request schemas for PVE2LLM (assistant name: Winky)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """Provider + assistant configuration (stored via ConnectorConfig)."""

    enabled: bool = False
    provider: str = "ollama"  # ollama | openai | anthropic
    base_url: str = ""
    model: str = ""
    # Secret: encrypted at rest by ConnectorConfig.SECRET_FIELDS.
    api_key: str = ""
    max_turns: int = 5
    max_tokens: int = 1024
    temperature: float = 0.2
    system_prompt: str = ""
    # Empty list = every plugin's read-only tools.
    allowed_plugins: list[str] = Field(default_factory=list)
    # Safety guards: 0 disables the respective limit.
    rate_limit_per_minute: int = 20
    max_tool_result_chars: int = 20000


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)


class ToolInfo(BaseModel):
    plugin_id: str
    name: str
    description: str = ""
    capability: str = ""
    input_schema: dict = Field(default_factory=dict)
