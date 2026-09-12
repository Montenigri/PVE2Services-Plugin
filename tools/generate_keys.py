#!/usr/bin/env python
"""Generate the ed25519 signing keypair via the installed ``pve2`` package.

Console script equivalent: ``pve2-generate-keys``.
"""

from __future__ import annotations

try:
    from PVE2Services.libs.plugin_keys import main  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - developer guidance
    raise SystemExit(
        "The 'pve2' core package is not installed. Install it first, e.g. "
        "`pip install pve2` (or add the core checkout parent to PYTHONPATH)."
    ) from exc

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
