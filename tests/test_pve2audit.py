"""Tests for PVE2Audit plugin — resource history and recommendations."""

import os

import pytest
from PVE2Services.libs.db_adapter import DBAdapter
from PVE2Services.plugins.PVE2Audit.analyzer import Analyzer


class TestPVE2Audit:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db_path = str(tmp_path / "test_audit.db")
        os.environ["PVE2_DB_URL"] = f"sqlite:///{self.db_path}"
        self.db = DBAdapter(db_url=f"sqlite:///{self.db_path}")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)

    def test_resource_history_insert_and_query(self):
        self.db.insert_resource_history("vm/100", "node1", "vm", 0.5, 0.8, 1024, 2048, 500, 1000, 100, 200)
        history = self.db.get_resource_history("vm/100")
        assert len(history) == 1
        assert history[0]["cpu_avg"] == 0.5
        assert history[0]["cpu_max"] == 0.8
        assert history[0]["mem_used"] == 1024

    def test_resource_history_multiple(self):
        for i in range(5):
            self.db.insert_resource_history("vm/100", "node1", "vm", 0.1 * i, 0.2 * i, 100 * i, 2000, 50 * i, 1000, 10 * i, 20 * i)
        history = self.db.get_resource_history("vm/100")
        assert len(history) == 5

    def test_resource_history_aggregate(self):
        for _i in range(3):
            self.db.insert_resource_history("vm/100", "node1", "vm", 0.5, 0.8, 1024, 2048, 500, 1000, 100, 200)
        agg = self.db.get_resource_history_aggregate("vm/100")
        assert agg is not None
        assert agg["cpu_avg"] == 0.5
        assert agg["cpu_peak"] == 0.8

    def test_recommendations_crud(self):
        rec_id = self.db.save_recommendation(
            "vm/100", "Test VM", "vm", "node1",
            "rightsizing", "warning",
            "4 CPU", "2 CPU", "CPU usage below 20%"
        )
        assert rec_id > 0
        
        recs = self.db.get_recommendations()
        assert len(recs) == 1
        assert recs[0]["category"] == "rightsizing"
        
        # Filter by category
        recs = self.db.get_recommendations(category="rightsizing")
        assert len(recs) == 1
        recs = self.db.get_recommendations(category="security")
        assert len(recs) == 0

    def test_recommendation_dismiss(self):
        rec_id = self.db.save_recommendation(
            "vm/100", "Test VM", "vm", "node1",
            "rightsizing", "warning", "4 CPU", "2 CPU", "Low usage"
        )
        assert self.db.dismiss_recommendation(rec_id) is True
        recs = self.db.get_recommendations(active_only=True)
        assert len(recs) == 0

    def test_recommendation_applied(self):
        rec_id = self.db.save_recommendation(
            "vm/100", "Test VM", "vm", "node1",
            "rightsizing", "warning", "4 CPU", "2 CPU", "Low usage"
        )
        assert self.db.mark_recommendation_applied(rec_id) is True
        recs = self.db.get_recommendations(active_only=True)
        assert len(recs) == 0

    def test_recommendation_summary(self):
        self.db.save_recommendation("vm/100", "VM1", "vm", "n1", "rightsizing", "warning", "4", "2", "Low")
        self.db.save_recommendation("vm/200", "VM2", "vm", "n1", "security", "critical", "open", "closed", "Port open")
        summary = self.db.get_recommendation_summary()
        assert summary["total"] == 2
        assert "warning" in summary["by_severity"]
        assert "critical" in summary["by_severity"]


class TestMedianRightsizing:
    """Median-based suggestions with burst protection (Feature: history-driven rightsizing)."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db = DBAdapter(db_url=f"sqlite:///{tmp_path}/audit_median.db")
        self.analyzer = Analyzer(self.db)
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)
        import PVE2Services.libs.db_adapter as _dba

        _dba._db_instance = None

    def _samples(self, cpu_vals, mem_used_vals, mem_max, disk_vals, cpu_max_vals=None):
        """Insert one sample per list entry; cpu fraction, bytes for mem."""
        n = max(len(cpu_vals), len(mem_used_vals), len(disk_vals))
        for i in range(n):
            cpu = cpu_vals[i % len(cpu_vals)]
            burst = (cpu_max_vals[i % len(cpu_max_vals)] if cpu_max_vals else cpu)
            self.db.insert_resource_history(
                "vm-901", "pve", "vm",
                cpu_avg=cpu, cpu_max=burst,
                mem_used=mem_used_vals[i % len(mem_used_vals)], mem_max=mem_max,
                disk_used=disk_vals[i % len(disk_vals)], disk_max=100 * 1024**3,
                netin=0, netout=0,
            )

    def _analyze(self):
        samples = self.db.get_resource_history("vm-901", limit=5000)
        return self.analyzer._analyze_entity("vm-901", samples, cores=4)

    def test_bursty_machine_never_downsized(self):
        """Median CPU is low but bursts hit 95% — a downsize would break it."""
        # 20 quiet samples, 2 bursts at 95% -> median ~5%, max 95%
        cpu = [0.05] * 20 + [0.95] * 2
        self._samples(cpu, [1 * 1024**3] * 22, 4 * 1024**3, [10 * 1024**3] * 22)
        recs = self._analyze()
        cpu_recs = [r for r in recs if r["category"] == "cpu" and "reduce" in (r["rationale"] or "")]
        assert cpu_recs == [], "bursty machine must NOT get a CPU downsize advice"

    def test_steady_low_cpu_gets_downsize(self):
        """Median AND max both low -> safe to remove one vCPU."""
        self._samples([0.03] * 20, [1 * 1024**3] * 20, 4 * 1024**3, [10 * 1024**3] * 20)
        recs = self._analyze()
        cpu_recs = [r for r in recs if r["category"] == "cpu"]
        assert len(cpu_recs) == 1
        assert "3 vCPU" in cpu_recs[0]["suggested_value"]
        assert "median" in cpu_recs[0]["rationale"].lower()

    def test_memory_downsize_requires_headroom_fit(self):
        """Low median but peak + 30% doesn't fit anything smaller -> no advice.

        Median 0.5GB (25% of 2GB) looks shrinkable, but the peak (1.9GB)
        + 30% headroom needs 3GB — more than the current 2GB. No reduction.
        """
        self._samples([0.2] * 10, [0.5 * 1024**3] * 8 + [1.9 * 1024**3] * 2, 2 * 1024**3, [10 * 1024**3] * 10)
        recs = self._analyze()
        assert [r for r in recs if r["category"] == "memory"] == []

    def test_memory_downsize_when_headroom_proven(self):
        """Peak 0.9GB of 4GB -> 0.9*1.3=1.17GB -> 2GB < 4GB: advice expected."""
        self._samples([0.02] * 10, [0.9 * 1024**3] * 10, 4 * 1024**3, [10 * 1024**3] * 10)
        recs = self._analyze()
        mem_recs = [r for r in recs if r["category"] == "memory"]
        assert len(mem_recs) == 1
        assert "2 GB" in mem_recs[0]["suggested_value"]
        assert "peak" in mem_recs[0]["rationale"].lower()

    def test_bursty_machine_not_flagged_idle(self):
        """Idle rule uses the median too — bursts must not be averaged away,
        and quiet machines with bursts must not be flagged idle."""
        cpu = [0.0] * 20 + [0.9] * 2
        self._samples(cpu, [50 * 1024**2] * 22, 2 * 1024**3, [10 * 1024**3] * 22)
        recs = self._analyze()
        assert [r for r in recs if r["category"] == "idle"] == []


class TestRetentionAndCoverage:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        old_url = os.environ.get("PVE2_DB_URL")
        self.db = DBAdapter(db_url=f"sqlite:///{tmp_path}/audit_retention.db")
        yield
        if old_url:
            os.environ["PVE2_DB_URL"] = old_url
        else:
            os.environ.pop("PVE2_DB_URL", None)
        import PVE2Services.libs.db_adapter as _dba

        _dba._db_instance = None

    def test_prune_removes_only_old_samples(self):
        from datetime import datetime, timedelta, timezone

        self.db.insert_resource_history("vm-1", "pve", "vm", 0.1, 0.1, 1, 2, 3, 4, 5, 6)
        # manually backdate one row 40 days
        with self.db.engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(text(
                "UPDATE resource_history SET timestamp = :ts WHERE entity_id = 'vm-1'"),
                {"ts": datetime.now(timezone.utc) - timedelta(days=40)},
            )
        self.db.insert_resource_history("vm-1", "pve", "vm", 0.2, 0.2, 1, 2, 3, 4, 5, 6)
        pruned = self.db.prune_resource_history(days=30)
        assert pruned == 1
        remaining = self.db.get_resource_history("vm-1")
        assert len(remaining) == 1

    def test_coverage_reports_first_seen_and_count(self):
        from datetime import datetime

        self.db.insert_resource_history("vm-1", "pve", "vm", 0.1, 0.1, 1, 2, 3, 4, 5, 6)
        self.db.insert_resource_history("vm-1", "pve", "vm", 0.2, 0.2, 1, 2, 3, 4, 5, 6)
        self.db.insert_resource_history("vm-2", "pve", "vm", 0.3, 0.3, 1, 2, 3, 4, 5, 6)
        cov = self.db.get_resource_history_coverage()
        assert cov["vm-1"]["samples"] == 2
        assert cov["vm-2"]["samples"] == 1
        first = cov["vm-1"]["first_seen"]
        assert isinstance(first, str)  # sqlite returns text; endpoint parses it
        datetime.fromisoformat(first)
