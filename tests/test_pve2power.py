"""Tests for PVE2Power plugin — power schedule management."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter


class TestPVE2Power:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_power.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_schedule_lifecycle(self):
        # Create
        assert self.db.save_power_schedule(
            "vm/100", "Test VM",
            weekday_start_time="09:00", weekday_stop_time="17:00",
            weekend_start_time="10:00", weekend_stop_time="16:00"
        ) is True
        
        # Read
        schedule = self.db.get_power_schedule("vm/100")
        assert schedule is not None
        assert schedule["weekday_start_time"] == "09:00"
        assert schedule["weekday_stop_time"] == "17:00"
        assert schedule["enabled"]  # SQLite returns 1, which is truthy
        
        # Update
        self.db.save_power_schedule("vm/100", "Test VM Updated", weekday_start_time="08:00")
        schedule = self.db.get_power_schedule("vm/100")
        assert schedule["weekday_start_time"] == "08:00"
        assert schedule["machine_name"] == "Test VM Updated"
        
        # Delete
        assert self.db.delete_power_schedule("vm/100") is True
        assert self.db.get_power_schedule("vm/100") is None

    def test_update_action(self):
        self.db.save_power_schedule("vm/100", "Test VM")
        self.db.update_power_schedule_action("vm/100", "start")
        schedule = self.db.get_power_schedule("vm/100")
        assert schedule["last_action"] == "start"
        assert schedule["last_action_at"] is not None

    def test_day_configuration(self):
        self.db.save_power_schedule(
            "vm/100", "Test VM",
            monday=True, tuesday=False, wednesday=True,
            thursday=False, friday=True,
            saturday=False, sunday=False
        )
        schedule = self.db.get_power_schedule("vm/100")
        assert schedule["monday"]  # SQLite returns 1, which is truthy
        assert not schedule["tuesday"]  # SQLite returns 0, which is falsy
        assert schedule["wednesday"]

    def test_force_stop_timeout(self):
        self.db.save_power_schedule("vm/100", "Test VM", force_stop_timeout=10)
        schedule = self.db.get_power_schedule("vm/100")
        assert schedule["force_stop_timeout"] == 10
