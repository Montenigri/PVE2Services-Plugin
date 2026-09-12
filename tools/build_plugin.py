#!/usr/bin/env python
"""Build/sign/publish plugins using the tooling shipped with the core.

The real implementation lives in the installable ``pve2`` package
(``PVE2Services.libs.plugin_build``) and is exposed as the console script
``pve2-build-plugin``. This wrapper only exists so the plugin repo can also be
driven as ``python tools/build_plugin.py ...`` without vendoring the logic.
"""

from __future__ import annotations

try:
    from PVE2Services.libs.plugin_build import (  # noqa: F401
        build_plugin,
        main,
        merge_local_index,
        publish,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - developer guidance
    raise SystemExit(
        "The 'pve2' core package is not installed. Install it first, e.g. "
        "`pip install pve2` (or add the core checkout parent to PYTHONPATH)."
    ) from exc

__all__ = ["build_plugin", "merge_local_index", "publish", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
