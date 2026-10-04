# Contributing to PVE2Services Plugins

Thank you for your interest in contributing to the PVE2Services plugin
collection. This document explains how to set up your environment, add or
change a plugin, and get your change merged.

For the full plugin contract (manifest fields, shared libraries, audit
logging, security rules) read [`PLUGIN_DEVELOPMENT.md`](PLUGIN_DEVELOPMENT.md).

## Getting started

1. Fork the repository and clone your fork.
2. Create a branch for your change:
   ```bash
   git checkout -b feat/your-feature
   ```
3. Make your change, add tests, and run the checks below.

## Development setup

Requires Python 3.11 or higher.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest

# Install the pinned core (the tag matching this plugin release), or use a
# local core checkout:
pip install "pve2 @ git+https://github.com/Montenigri/pve2service-core.git@v0.1.0"
# export PYTHONPATH=/path/to/PVE2Services-Core

ruff check .
pytest -q tests
```

The test harness wires the plugin namespace and sets `PVE2_PLUGINS_DIR` to this
repo's `plugins/` directory, so the core app under test loads the very modules
the tests import.

## Adding or changing a plugin

A plugin is a directory under `plugins/` with a validated `plugin.yaml` and an
`__init__.py` exporting `load_plugin(app)`. See
[`PLUGIN_DEVELOPMENT.md`](PLUGIN_DEVELOPMENT.md) for the required endpoints and
the shared libraries (`db_adapter`, `connector_config`, `errors`, `http`,
`scheduler`, `audit`).

When you add a plugin:

- add its directory to [`plugins/bundled_plugins.txt`](plugins/bundled_plugins.txt)
  if it ships with the core;
- add a `README.md` inside the plugin directory;
- add tests under `tests/`;
- record real operations in the central audit log.

### Exposing read-only data to the assistant (Winky)

Plugins can expose read-only tools to the PVE2LLM assistant by adding an `mcp:`
block to `plugin.yaml` and a `mcp_tools.py` module. Only `read_only: true` tools
are ever offered to the model. See the "MCP Tools (Winky assistant)" section of
[`PLUGIN_DEVELOPMENT.md`](PLUGIN_DEVELOPMENT.md).

## Code style

- `ruff check .` must pass (config in `pyproject.toml`).
- Match the style of neighbouring files; keep functions focused and documented.
- Never log secrets (tokens, passwords, webhooks, SSH keys).

## Pull request process

1. Ensure `ruff check .` and `pytest -q tests` pass locally.
2. Keep the PR focused; describe the motivation and the user-visible behaviour.
3. Update `PLUGIN_DEVELOPMENT.md` / `README.md` and `CHANGELOG.md` when relevant.
4. A maintainer reviews and merges. CI (lint + tests) must be green.

## Reporting issues

Open a GitHub issue using the provided template. For security problems, follow
[`SECURITY.md`](SECURITY.md) instead — do **not** open a public issue.
