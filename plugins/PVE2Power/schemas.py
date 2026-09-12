from typing import Optional

from pydantic import BaseModel


class PowerConfig(BaseModel):
    enabled: bool = False
    timezone: str = "UTC"
    poll_interval_seconds: int = 60
    default_force_stop_timeout: int = 5


class PowerScheduleIn(BaseModel):
    machine_id: str
    machine_name: str = ""
    enabled: bool = True
    weekday_start_time: str = "08:00"
    weekday_stop_time: str = "18:00"
    weekend_start_time: str = "10:00"
    weekend_stop_time: str = "20:00"
    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True
    saturday: bool = False
    sunday: bool = False
    force_stop_timeout: int = 5


class PowerScheduleOut(BaseModel):
    id: int
    machine_id: str
    machine_name: str = ""
    enabled: bool = True
    weekday_start_time: str = "08:00"
    weekday_stop_time: str = "18:00"
    weekend_start_time: str = "10:00"
    weekend_stop_time: str = "20:00"
    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True
    saturday: bool = False
    sunday: bool = False
    force_stop_timeout: int = 5
    last_action: Optional[str] = None
    last_action_at: Optional[str] = None


class MachineWithSchedule(BaseModel):
    machine_id: str
    machine_name: str = ""
    type: str = ""
    node: str = ""
    status: str = ""
    schedule: Optional[PowerScheduleOut] = None
