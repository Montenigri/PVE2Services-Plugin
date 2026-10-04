# PVE2Services — Plugins

First-party plugins for [PVE2Services](https://github.com/Montenigri/pve2service-core).
This repo is the source of truth for every plugin that ships with (or extends)
the PVE2 core.

## Distribution model

There are three independent trust channels:

| Channel | Sources | How it reaches the core | Trust tier |
|---|---|---|---|
| **First-party open** (this repo) | the plugins below | bundled into the core image at build time (the core release workflow checks out this repo at a pinned ref and copies the plugin dirs in) | `trusted` |
| **First-party closed** | a private repo | built + signed with the project signing key and pulled from the plugin store at startup (`PVE2_PLUGINS_INSTALL`) | `trusted` |
| **Third-party** | any external repo | installed from the store or dropped into `plugins/` | `third_party` |

The plugins listed in [`plugins/bundled_plugins.txt`](plugins/bundled_plugins.txt)
are the *first-party open* set and are bundled by the core. Everything listed in
[`plugins/store_plugins.txt`](plugins/store_plugins.txt) is additionally built,
signed and published to the plugin store by the release workflow. Add new,
independently-released first-party plugins there.

> **v1 status — bundled-only.** The plugin **store is not active yet**: the v1
> open-source release ships the *first-party open* (bundled) plugins only. The
> store channel and its signing/publish workflow are in place but remain
> dormant until the first store plugin is published.

## Layout

```
plugins/<id>/
├── plugin.yaml      # validated manifest: id, name, version, core_compat, ...
├── __init__.py      # exports load_plugin(app)
└── ...              # code, schemas, providers, frontend
tests/               # plugin test-suite (runs against the installed pve2 wheel)
tools/               # thin wrappers around the core build/sign tooling
```

## Development

Requires the core package (the plugin test-suite imports `PVE2Services.libs.*`
and `PVE2Services.core.*`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest

# Either install the pinned core (the tag matching this plugin release):
pip install "pve2 @ git+https://github.com/Montenigri/pve2service-core.git@v0.1.0"
# ...or install the wheel attached to the core GitHub release:
pip install /path/to/pve2-0.1.0-py3-none-any.whl
# ...or point at a local core checkout (parent of the PVE2Services/ package dir):
export PYTHONPATH=/path/to/PVE2Services-Core

ruff check .
pytest -q tests
```

When running locally the test harness sets `PVE2_PLUGINS_DIR` to this repo's
`plugins/` directory and wires the `PVE2Services.plugins` namespace, so the core
app under test loads the very modules the tests import.

## Building and publishing to the store

The private signing key is **never** committed: it lives in the repo secret
`PVE2_PLUGIN_SIGNING_KEY` (and, for local runs, a secure local path).

```bash
export PVE2_PLUGIN_SIGNING_KEY=/secure/pve2_signing.pem
python tools/build_plugin.py plugins/PVE2Backup            # build + sign
PVE2_STORE_ENDPOINT=http://localhost:19000 \
    python tools/build_plugin.py plugins/PVE2Backup --publish
```

See [`docs/PLUGIN_STORE.md`](https://github.com/Montenigri/pve2service-core/blob/main/docs/PLUGIN_STORE.md)
in the core repo for the full store reference, and
[`PLUGIN_DEVELOPMENT.md`](PLUGIN_DEVELOPMENT.md) for the manifest/plugin contract.

## Disclaimer

PVE2Services and these plugins are an independent project and are **not
affiliated with, endorsed by, or sponsored by Proxmox Server Solutions GmbH**.
"Proxmox" is a trademark of its respective owner and is used here only to
describe interoperability.
