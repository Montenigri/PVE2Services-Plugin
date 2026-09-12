import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from PVE2Services.libs.db_adapter import DBAdapter
from sqlalchemy import text

logger = logging.getLogger("pve2audit.analyzer")


DEFAULT_THRESHOLDS = {
    "cpu_under": 15,
    "cpu_over": 80,
    "mem_under": 40,
    "mem_over": 80,
    "disk_over": 80,
    "idle_cpu_pct": 2,
    "idle_mem_mb": 256,
    "idle_days": 14,
}


class Analyzer:
    """Read resource_history and produce rightsizing recommendations."""

    def __init__(self, db: DBAdapter, thresholds: Optional[Dict[str, Any]] = None,
                 entity_names: Optional[Dict[str, Any]] = None):
        self.db = db
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        # entity_names: entity_id -> {"name": str, "cores": int} from PVE2Core's cache
        self._entity_specs = entity_names or {}

    def run(self, window_days: int = 30) -> Dict[str, int]:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        created = 0
        errors = 0

        entity_ids = self._get_entity_ids(since)
        entity_meta = self._get_entity_meta(since)
        entity_names = {k: v.get("name", "") for k, v in self._entity_specs.items()} if self._entity_specs else self._get_entity_names()
        entity_cores = {k: v.get("cores", 1) for k, v in self._entity_specs.items()} if self._entity_specs else {}
        for entity_id in entity_ids:
            samples = self.db.get_resource_history(entity_id, since=since, limit=5000)
            if not samples:
                continue

            meta = entity_meta.get(entity_id, {})
            try:
                recs = self._analyze_entity(
                    entity_id, samples,
                    entity_name=entity_names.get(entity_id, entity_id),
                    entity_type=meta.get("entity_type", ""),
                    node=meta.get("node", ""),
                    cores=entity_cores.get(entity_id, 1),
                    window_days=window_days,
                )
                for rec in recs:
                    existing = self.db.get_recommendations(
                        entity_id=entity_id, category=rec["category"], active_only=True
                    )
                    if existing:
                        continue
                    self.db.save_recommendation(**rec)
                    created += 1
            except Exception as e:
                logger.exception("Error analyzing %s: %s", entity_id, e)
                errors += 1

        if self.thresholds.get("node_balance_enabled", True):
            try:
                balance_recs = self._analyze_node_balance()
                for rec in balance_recs:
                    existing = self.db.get_recommendations(
                        entity_id=rec["entity_id"], category="node_balance", active_only=True
                    )
                    if existing:
                        continue
                    self.db.save_recommendation(**rec)
                    created += 1
            except Exception as e:
                logger.exception("Error analyzing node balance: %s", e)
                errors += 1

        logger.info("Analyzer: %d recommendations created, %d errors", created, errors)
        return {"created": created, "errors": errors}

    def _get_entity_ids(self, since: datetime) -> List[str]:
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT entity_id FROM resource_history WHERE timestamp >= :since ORDER BY entity_id"),
                {"since": since},
            ).fetchall()
            return [r[0] for r in rows]

    def _get_entity_meta(self, since: datetime) -> Dict[str, Dict[str, str]]:
        """Map entity_id -> {node, entity_type} from recent resource_history samples."""
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT entity_id, node, entity_type FROM resource_history "
                    "WHERE timestamp >= :since"
                ),
                {"since": since},
            ).fetchall()
        meta: Dict[str, Dict[str, str]] = {}
        for r in rows:
            m = dict(r._mapping)
            entry = meta.setdefault(m["entity_id"], {"node": "", "entity_type": ""})
            if m.get("node") and not entry["node"]:
                entry["node"] = m["node"]
            if m.get("entity_type") and not entry["entity_type"]:
                entry["entity_type"] = m["entity_type"]
        return meta

    def _get_entity_names(self) -> Dict[str, str]:
        """Map entity_id -> human name from sync_state.entity_data (written by PVE2Core)."""
        try:
            states = self.db.get_all_sync_states()
        except Exception:
            return {}
        names: Dict[str, str] = {}
        for s in states:
            try:
                data = json.loads(s.get("entity_data") or "{}")
            except (TypeError, ValueError):
                continue
            if data.get("name"):
                names[s["id"]] = data["name"]
        return names

    @staticmethod
    def _median(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        n = len(s)
        mid = n // 2
        return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2

    @staticmethod
    def _p95(values: List[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)
        return s[idx]

    def _analyze_entity(self, entity_id: str, samples: List[Dict[str, Any]],
                        entity_name: str = "", entity_type: str = "",
                        node: str = "", cores: int = 1,
                        window_days: int = 30) -> List[Dict[str, Any]]:
        """Median-based rightsizing with burst protection.

        Statistics come from the full sample history in the window (collected
        every 15-30 min), not from a single reading:
        - median = the "typical" load; bursts don't skew it
        - max/p95 = burst ceiling; a downsize is only proposed when even the
          bursts fit the smaller allocation
        """
        recs: List[Dict[str, Any]] = []
        cores_allocated = max(1, int(cores or 1))

        cpu_vals = [s.get("cpu_avg") or 0 for s in samples]
        cpu_burst_vals = [s.get("cpu_max") or 0 for s in samples]
        mem_used_vals = [s.get("mem_used") or 0 for s in samples]
        mem_max_vals = [s.get("mem_max") or 0 for s in samples]
        disk_pct_vals = [
            (s.get("disk_used") or 0) / (s.get("disk_max") or 0) * 100
            for s in samples if s.get("disk_max")
        ]

        cpu_median = self._median(cpu_vals)
        cpu_p95 = self._p95(cpu_vals)
        cpu_burst_max = max(cpu_burst_vals) if cpu_burst_vals else 0
        cpu_median_pct = cpu_median * 100
        cpu_p95_pct = cpu_p95 * 100
        cpu_burst_pct = cpu_burst_max * 100

        mem_peak = max(mem_used_vals) if mem_used_vals else 0
        mem_max = max(mem_max_vals) if mem_max_vals else 0
        mem_median = self._median(mem_used_vals)
        mem_pct_median = (self._median([
            (s.get("mem_used") or 0) / (s.get("mem_max") or 0) * 100
            for s in samples if s.get("mem_max")
        ]))
        disk_pct_median = self._median(disk_pct_vals)

        cpu_under = self.thresholds["cpu_under"]
        cpu_over = self.thresholds["cpu_over"]
        mem_under_pct = self.thresholds["mem_under"]
        mem_over_pct = self.thresholds["mem_over"]
        disk_over_pct = self.thresholds["disk_over"]
        idle_cpu = self.thresholds["idle_cpu_pct"]
        idle_mem_mb = self.thresholds["idle_mem_mb"]

        def gb(value_bytes: float) -> str:
            return f"{value_bytes / (1024 ** 3):.1f} GB"

        window_txt = f"{window_days}-day window"

        if cpu_median_pct < cpu_under:
            if cpu_burst_pct < 60:
                suggested = max(1, cores_allocated - 1)
                recs.append(self._make_rec(entity_id, "cpu", "warning",
                    f"{cores_allocated} vCPU @ {cpu_median_pct:.0f}% median (peak {cpu_burst_pct:.0f}%)",
                    f"{suggested} vCPU",
                    f"Median CPU {cpu_median_pct:.0f}% over the {window_txt}, bursts never above {cpu_burst_pct:.0f}% — "
                    f"reduce from {cores_allocated} to {suggested} vCPUs and re-measure",
                    entity_name=entity_name, entity_type=entity_type, node=node))
            # else: bursty workload — median is low but bursts need the cores;
            # downsizing would break it, so we deliberately stay silent.

        if cpu_p95_pct > cpu_over:
            suggested = max(cores_allocated + 1, math.ceil(cores_allocated * (cpu_p95_pct / 100) * 1.5))
            recs.append(self._make_rec(entity_id, "cpu", "warning",
                f"{cores_allocated} vCPU @ {cpu_median_pct:.0f}% median (p95 {cpu_p95_pct:.0f}%)",
                f"{suggested} vCPU",
                f"CPU p95 at {cpu_p95_pct:.0f}% over the {window_txt} — sustained pressure, consider increasing vCPUs",
                entity_name=entity_name, entity_type=entity_type, node=node))

        current_mb = int((mem_max or 0) / 1048576)
        if mem_pct_median < mem_under_pct:
            # Suggest peak usage + 30% headroom, rounded up to whole GB — and
            # only if that is actually smaller than today's allocation.
            suggested_mb = max(512, math.ceil(mem_peak * 1.3 / (1024 ** 3)) * 1024)
            if suggested_mb < current_mb:
                recs.append(self._make_rec(entity_id, "memory", "info",
                    f"{gb(mem_max)} @ {mem_pct_median:.0f}% median (peak {gb(mem_peak)})",
                    f"{suggested_mb // 1024} GB",
                    f"Median memory {mem_pct_median:.0f}% over the {window_txt}; peak {gb(mem_peak)} + 30% headroom fits "
                    f"{suggested_mb // 1024} GB — safe reduction from {gb(mem_max)}",
                    entity_name=entity_name, entity_type=entity_type, node=node))

        if mem_pct_median > mem_over_pct:
            suggested_mb = max(math.ceil(mem_max / (1024 ** 3)) + 1, math.ceil(mem_peak * 1.3 / (1024 ** 3))) * 1024
            recs.append(self._make_rec(entity_id, "memory", "warning",
                f"{gb(mem_max)} @ {mem_pct_median:.0f}% median (peak {gb(mem_peak)})",
                f"{suggested_mb // 1024} GB",
                f"Median memory {mem_pct_median:.0f}% over the {window_txt} — increase from {gb(mem_max)} to {suggested_mb // 1024} GB",
                entity_name=entity_name, entity_type=entity_type, node=node))

        if disk_pct_median > disk_over_pct:
            recs.append(self._make_rec(entity_id, "disk", "critical",
                f"{disk_pct_median:.0f}% disk used (median)",
                "Investigate and grow disk",
                f"Disk utilization median {disk_pct_median:.0f}% over the {window_txt} — above {disk_over_pct}% threshold",
                entity_name=entity_name, entity_type=entity_type, node=node))

        mem_median_mb = mem_median / 1048576
        if cpu_median_pct < idle_cpu and mem_median_mb < idle_mem_mb:
            if cpu_burst_pct < 50:
                recs.append(self._make_rec(entity_id, "idle", "info",
                    f"CPU {cpu_median_pct:.1f}% / mem {mem_median_mb:.0f} MB (median)",
                    "Consider shutdown or consolidation",
                    f"Median CPU {cpu_median_pct:.1f}% and memory {mem_median_mb:.0f} MB over the {window_txt} — "
                    f"a stopped machine frees all its CPU and RAM instantly",
                    entity_name=entity_name, entity_type=entity_type, node=node))
            # else: bursts to a significant fraction of its cores — not a
            # shutdown candidate even though the median looks idle.

        return recs

    def _make_rec(self, entity_id: str, category: str, severity: str,
                  current_value: str, suggested_value: str,
                  rationale: str, entity_name: str = "",
                  entity_type: str = "", node: str = "") -> Dict[str, Any]:
        return {
            "entity_id": entity_id,
            "entity_name": entity_name or entity_id,
            "entity_type": entity_type,
            "node": node,
            "category": category,
            "severity": severity,
            "current_value": current_value,
            "suggested_value": suggested_value,
            "rationale": rationale,
        }

    def _analyze_node_balance(self) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []
        since = datetime.now(timezone.utc) - timedelta(days=1)

        with self.db.engine.connect() as conn:
            rows = conn.execute(text("""SELECT node,
                COUNT(DISTINCT entity_id) as total_vms,
                AVG(cpu_avg) as node_cpu_avg
                FROM resource_history WHERE timestamp >= :since
                GROUP BY node"""), {"since": since}).fetchall()

        if not rows:
            return recs

        allocations = [dict(r._mapping) for r in rows]
        avg_cpu = sum(a.get("node_cpu_avg", 0) or 0 for a in allocations) / len(allocations)

        for a in allocations:
            dev = ((a["node_cpu_avg"] or 0) - avg_cpu) / max(avg_cpu, 0.01) * 100
            if dev > 30:
                recs.append({
                    "entity_id": f"node-{a['node']}",
                    "entity_name": f"Node {a['node']}",
                    "entity_type": "node",
                    "node": a["node"],
                    "category": "node_balance",
                    "severity": "warning",
                    "current_value": f"{a['node_cpu_avg']*100:.0f}% CPU (cluster avg {avg_cpu*100:.0f}%)",
                    "suggested_value": "Migrate VMs to reduce load",
                    "rationale": f"Node {a['node']} CPU is {dev:.0f}% above cluster average — consider migrating VMs",
                })

        return recs
