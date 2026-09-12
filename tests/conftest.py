"""Shared pytest configuration for the pve2-plugins repo.

The plugins depend on the core library (``PVE2Services.libs.*`` and
``PVE2Services.core.*``): install the ``pve2`` wheel first (``pip install pve2``)
or put the parent of a core checkout on ``PYTHONPATH``.

This conftest wires the *plugin* half of the namespace so that:
  * ``import PVE2Services.plugins.<Dir>`` resolves to this repo's ``plugins/``;
  * the core app loads those same modules (identity preserved) instead of the
    ``pve2_external_*`` namespace used for arbitrary external checkouts.

It also mirrors the core test fixture that resets the DB-backed rate limiters
between tests, so login/credential flows are deterministic.
"""

import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = REPO_ROOT / "plugins"

# The repo root holds `tools/`; expose it like the core conftest does.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The core app must discover THIS plugins dir...
os.environ.setdefault("PVE2_PLUGINS_DIR", str(PLUGINS_DIR))
# TestClient talks plain HTTP, so secure-only cookies must be off.
os.environ.setdefault("PVE2_SESSION_SECURE", "false")

# ...with a dedicated test DB (respect an explicit PVE2_DB_URL, e.g. Postgres).
if not os.environ.get("PVE2_DB_URL"):
    _test_db = str(REPO_ROOT / "pve2_test.db")
    os.environ["PVE2_DB_URL"] = f"sqlite:///{_test_db}"
    if os.path.exists(_test_db):
        os.remove(_test_db)

# Force the loader to treat PLUGINS_DIR as the core's own plugins dir, so it
# imports plugins as ``PVE2Services.plugins.<Dir>`` (same module objects the
# tests import directly) rather than pve2_external_*.
from PVE2Services.libs import plugin_loader  # noqa: E402

plugin_loader.REPO_PLUGINS_DIR = PLUGINS_DIR

import PVE2Services  # noqa: E402

try:
    import PVE2Services.plugins as _plugins_pkg  # noqa: E402
except ModuleNotFoundError:  # wheel built without a plugins/ dir
    _plugins_pkg = types.ModuleType("PVE2Services.plugins")
    _plugins_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["PVE2Services.plugins"] = _plugins_pkg
    PVE2Services.plugins = _plugins_pkg  # type: ignore[attr-defined]

if str(PLUGINS_DIR) not in _plugins_pkg.__path__:  # type: ignore[attr-defined]
    _plugins_pkg.__path__.append(str(PLUGINS_DIR))  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_rate_limiter(tmp_path):
    """Reset rate limiter state and keep audit logs out of the repo."""
    try:
        from PVE2Services.core.wiki_service.app.auth import reset_all_rate_limiters
    except ImportError:
        yield
        return

    try:
        from PVE2Services.libs.audit import audit as _audit

        _audit.configure(log_dir=tmp_path / "audit_logs")
        _audit.reset()
    except ImportError:
        pass

    reset_all_rate_limiters()
    yield
    reset_all_rate_limiters()
