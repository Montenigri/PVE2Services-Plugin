from pydantic import BaseModel, field_validator


class NutServer(BaseModel):
    label: str = ""
    host: str
    port: int = 3493
    username: str = ""
    password: str = ""
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def _host_required(cls, value: str) -> str:
        if not (value or "").strip():
            raise ValueError("host is required")
        return value.strip()

    @field_validator("port")
    @classmethod
    def _port_range(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("port must be 1-65535")
        return value


class NutConfig(BaseModel):
    enabled: bool = False
    servers: list[NutServer] = []
    poll_interval_seconds: int = 60
    prune_days: int = 30
    notify_on_battery: bool = True
    notify_low_battery: bool = True
    notify_ups_online: bool = False
    notify_comm_lost: bool = True
    notify_comm_restored: bool = False

    @field_validator("poll_interval_seconds")
    @classmethod
    def _interval_min(cls, value: int) -> int:
        return max(15, value)

    @field_validator("prune_days")
    @classmethod
    def _prune_min(cls, value: int) -> int:
        return max(1, value)
