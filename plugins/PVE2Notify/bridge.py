"""Cross-plugin notification bridge for PVE2Notify.

Other plugins (PVE2NUT, future ones) call ``send_notification`` to deliver
messages through the channels already configured in PVE2Notify
(Discord / Slack / Mattermost / Telegram) — a single notification system
per instance, no per-plugin webhook duplication.
"""

import logging

try:
    from PVE2Services.libs.connector_config import ConnectorConfig
except ImportError:
    ConnectorConfig = None

logger = logging.getLogger("pve2notify.bridge")

NOTIFIER_CONNECTOR_ID = "pve2notify"


async def send_notification(title: str, description: str = "",
                            fields: list | None = None,
                            event_type: str = "custom",
                            source: str = "PVE2Services") -> dict:
    """Send a generic notification to every configured provider.

    Returns {"sent", "providers", "errors"} — never raises: notification
    failures must not break the calling plugin's operation.
    """
    result = {"sent": 0, "providers": 0, "errors": []}
    if not ConnectorConfig:
        result["errors"].append("Config manager unavailable")
        return result
    try:
        config = ConnectorConfig().get_config(NOTIFIER_CONNECTOR_ID)
    except Exception as e:
        result["errors"].append(f"Cannot read PVE2Notify config: {e}")
        return result

    if not config.get("enabled"):
        result["errors"].append("PVE2Notify not enabled")
        return result

    from .providers import create_providers
    providers = create_providers(config)
    result["providers"] = len(providers)
    if not providers:
        result["errors"].append("No notification providers configured")
        return result

    for p in providers:
        name = type(p).__name__.replace("Provider", "").lower()
        try:
            if await p.send_generic(title, description, fields or [],
                                    event_type, source):
                result["sent"] += 1
            else:
                result["errors"].append(f"{name}: rejected")
        except Exception as e:
            result["errors"].append(f"{name}: {e}")
    if result["errors"]:
        logger.warning("Notification delivery incomplete: %s", result["errors"])
    return result
