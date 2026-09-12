from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field


class NotifyConfig(BaseModel):
    enabled: bool = False
    poll_interval_seconds: int = 60
    discord_enabled: bool = False
    discord_webhook_url: str = ""
    slack_enabled: bool = False
    slack_webhook_url: str = ""
    mattermost_enabled: bool = False
    mattermost_webhook_url: str = ""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_started: bool = True
    notify_stopped: bool = True
    notify_added: bool = True
    notify_removed: bool = True


class MachineEvent(BaseModel):
    event_type: str  # started | stopped | added | removed
    machine_id: str
    machine_name: str = ""
    machine_type: str = ""
    node: str = ""
    status: str = ""
    previous_status: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TestResult(BaseModel):
    provider: str
    success: bool
    error: str = ""


class SyncResult(BaseModel):
    status: str
    events: List[MachineEvent] = []
    notifications_sent: int = 0
    provider_results: List[TestResult] = []
    errors: List[str] = []
