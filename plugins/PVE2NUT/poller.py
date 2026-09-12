"""PVE2NUT poller — query NUT servers, group devices, persist readings,
detect status changes and deliver notifications through PVE2Notify.

Redundancy model: N servers, M UPS devices, N:M relationships allowed.
A logical UPS is identified by its device name: the same name seen on
multiple servers collapses into one device whose *serving server* is the
first reachable one in configuration order (failover). History and events
are keyed by device name, so charts stay continuous across failovers.
"""

import asyncio
import logging

from .nut_client import NUTClient, NUTError

logger = logging.getLogger("pve2nut")

EVENT_TITLES = {
    "on_battery": "UPS On Battery",
    "low_battery": "UPS Low Battery",
    "ups_online": "UPS Back Online",
    "comm_lost": "UPS Communication Lost",
    "comm_restored": "UPS Communication Restored",
}

STATUS_TOKENS_CRITICAL = {"LB", "FSD"}


def classify_status(status: str) -> dict:
    """Map an ups.status token list to a normalized state + human label."""
    tokens = set((status or "").upper().split())
    if "LB" in tokens:
        return {"state": "low_battery", "label": "Low Battery"}
    if "OB" in tokens or "DISCHRG" in tokens:
        return {"state": "on_battery", "label": "On Battery"}
    if "HB" in tokens or "RB" in tokens:
        return {"state": "replace_battery", "label": "Replace Battery"}
    if "FSD" in tokens:
        return {"state": "shutdown", "label": "Forced Shutdown"}
    if "BYPASS" in tokens:
        return {"state": "bypass", "label": "Bypass"}
    if "OFF" in tokens:
        return {"state": "off", "label": "Off"}
    if "OL" in tokens or "CHRG" in tokens:
        return {"state": "online", "label": "Online"}
    return {"state": "unknown", "label": "Unknown"}


def _f(value) -> float | None:
    """Parse a NUT variable value to float; None when absent/invalid."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_metrics(vars: dict) -> dict:
    """Charted metrics extracted from a raw NUT vars dict."""
    return {
        "battery_charge": _f(vars.get("battery.charge")),
        "battery_runtime": _f(vars.get("battery.runtime")),
        "ups_load": _f(vars.get("ups.load")),
        "realpower": _f(vars.get("ups.realpower")),
        "apparent_power": _f(vars.get("ups.power")),
        "input_voltage": _f(vars.get("input.voltage")),
        "output_voltage": _f(vars.get("output.voltage")),
        "battery_voltage": _f(vars.get("battery.voltage")),
    }


def server_label(server: dict) -> str:
    return (server.get("label") or "").strip() or \
        f"{server.get('host', '?')}:{server.get('port', 3493)}"


def _poll_server(server: dict) -> dict:
    """Query one NUT server: {ok, ups: {name: vars}, descriptions, error}."""
    label = server_label(server)
    try:
        with NUTClient(server["host"], server.get("port", 3493),
                       username=server.get("username", ""),
                       password=server.get("password", "")) as client:
            devices = client.list_ups()
            ups = {}
            descriptions = {}
            for device in devices:
                name = device["name"]
                try:
                    ups[name] = client.list_vars(name)
                except NUTError as e:
                    logger.warning("Server %s: cannot read vars of %s: %s", label, name, e)
                    ups[name] = {}
                descriptions[name] = device.get("description", "")
            return {"ok": True, "ups": ups, "descriptions": descriptions, "error": ""}
    except NUTError as e:
        return {"ok": False, "ups": {}, "descriptions": {}, "error": str(e)}


def poll_servers(servers: list[dict]) -> tuple[dict, list[dict]]:
    """Poll all enabled servers.

    Returns (devices, server_results):
      devices: {ups_name: {name, description, vars, servers, serving_server}}
      server_results: [{label, ok, error, ups_count}]
    """
    devices: dict[str, dict] = {}
    server_results = []
    for server in servers:
        if not server.get("enabled", True):
            continue
        label = server_label(server)
        result = _poll_server(server)
        server_results.append({
            "label": label,
            "ok": result["ok"],
            "error": result.get("error", ""),
            "ups_count": len(result["ups"]),
        })
        if not result["ok"]:
            logger.warning("Server %s unreachable: %s", label, result.get("error"))
            continue
        for name, vars_ in result["ups"].items():
            entry = devices.setdefault(name, {
                "name": name, "description": "", "vars": {},
                "servers": [], "serving_server": "",
            })
            entry["servers"].append(label)
            entry["description"] = result["descriptions"].get(name, "") or entry["description"]
            # Primary = first reachable server in configuration order.
            if not entry["serving_server"] and vars_:
                entry["serving_server"] = label
                entry["vars"] = vars_
    return devices, server_results


def _transition_event(prev_state: str, new_state: str) -> str | None:
    """Map a status transition to a notification event type (None = no event)."""
    if new_state == "low_battery":
        return "low_battery" if prev_state != "low_battery" else None
    if new_state == "on_battery":
        return "on_battery" if prev_state not in ("on_battery", "low_battery") else None
    if new_state == "online" and prev_state in ("on_battery", "low_battery"):
        return "ups_online"
    return None


async def run_poll(config: dict, db, notify: bool = True) -> dict:
    """Full poll cycle: read, persist, diff, notify, prune.

    Returns {"devices", "servers", "events", "notified", "errors"}.
    """
    errors: list[str] = []
    servers = [s for s in (config.get("servers") or []) if s.get("enabled", True)]
    devices, server_results = await asyncio.to_thread(poll_servers, servers)

    events: list[dict] = []
    for result in server_results:
        if not result["ok"]:
            errors.append(f"{result['label']}: {result['error']}")

    for name, entry in devices.items():
        vars_ = entry["vars"]
        status = vars_.get("ups.status", "")
        metrics = extract_metrics(vars_)
        if not status:
            # Device visible but vars unreadable — skip reading, note error.
            errors.append(f"{name}: no readable variables")
            continue
        # Evaluated before this poll's writes: was the device comm_lost?
        prior_last = db.get_nut_events(name, limit=1)
        was_lost = bool(prior_last and prior_last[0].get("event_type") == "comm_lost")

        previous = db.get_last_nut_reading(name)
        prev_status = (previous or {}).get("status", "")
        db.save_nut_reading(name, status=status, vars=vars_, **metrics)

        new_state = classify_status(status)["state"]
        if prev_status:
            prev_state = classify_status(prev_status)["state"]
            event_type = _transition_event(prev_state, new_state)
            if event_type:
                detail = f"{classify_status(prev_status)['label']} -> {classify_status(status)['label']}"
                db.save_nut_event(name, event_type, from_status=prev_status,
                                  to_status=status, detail=detail)
                events.append({"ups_name": name, "event_type": event_type,
                               "from_status": prev_status, "to_status": status,
                               "detail": detail})

        # Communication restored: a device that disappeared earlier is back.
        if was_lost:
            db.save_nut_event(name, "comm_restored", to_status=status,
                              detail=f"reachable via {entry['serving_server']}")
            events.append({"ups_name": name, "event_type": "comm_restored",
                           "to_status": status})

    # Communication lost: devices seen before but absent from this poll.
    known = set(db.get_nut_devices())
    for name in sorted(known - set(devices)):
            last_event = db.get_nut_events(name, limit=1)
            if last_event and last_event[0].get("event_type") == "comm_lost":
                continue
            detail = "device not visible on any configured server"
            db.save_nut_event(name, "comm_lost", detail=detail)
            events.append({"ups_name": name, "event_type": "comm_lost",
                           "detail": detail})

    notified = 0
    if notify:
        notified = await _notify(events, config)

    prune_days = max(1, int(config.get("prune_days", 30) or 30))
    db.prune_nut_history(days=prune_days)
    db.prune_nut_events(days=prune_days * 3)

    device_list = []
    for name, entry in devices.items():
        status = entry["vars"].get("ups.status", "")
        info = classify_status(status)
        device_list.append({
            "name": name,
            "description": entry["description"],
            "status": status,
            "state": info["state"],
            "label": info["label"],
            "metrics": extract_metrics(entry["vars"]),
            "vars": entry["vars"],
            "serving_server": entry["serving_server"],
            "servers": entry["servers"],
        })

    return {
        "devices": device_list,
        "servers": server_results,
        "events": events,
        "notified": notified,
        "errors": errors,
    }


async def _notify(events: list[dict], config: dict) -> int:
    """Send events through the PVE2Notify bridge (best effort, never raises)."""
    if not events:
        return 0
    try:
        from PVE2Services.plugins.PVE2Notify.bridge import send_notification
    except ImportError:
        logger.warning("PVE2Notify bridge unavailable — notifications skipped")
        return 0
    sent = 0
    for event in events:
        if not config.get(f"notify_{event['event_type']}", True):
            continue
        ups = event["ups_name"]
        fields = [
            {"name": "UPS", "value": ups},
            {"name": "Status", "value": event.get("to_status") or "-"},
        ]
        if event.get("from_status"):
            fields.append({"name": "Previous", "value": event["from_status"]})
        if event.get("detail"):
            fields.append({"name": "Detail", "value": event["detail"]})
        try:
            result = await send_notification(
                f"{EVENT_TITLES.get(event['event_type'], 'UPS Event')} — {ups}",
                description="Power event reported by NUT.",
                fields=fields,
                event_type=event["event_type"],
                source="PVE2NUT",
            )
            if result.get("sent"):
                sent += 1
            elif result.get("errors"):
                logger.warning("Notification for %s not delivered: %s", ups, result["errors"])
        except Exception:
            logger.exception("Bridge notification failed for %s", ups)
    return sent


def find_serving_server(config: dict, devices: dict, ups_name: str) -> dict | None:
    """Server config dict currently serving an UPS (for commands/clients)."""
    entry = (devices or {}).get(ups_name)
    serving = (entry or {}).get("serving_server")
    for server in config.get("servers") or []:
        if server_label(server) == serving and server.get("enabled", True):
            return server
    return None
