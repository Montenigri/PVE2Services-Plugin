"""PVE2Wiki frontend — served at /admin/pve2wiki."""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def build_page(configured: bool = False) -> str:
    return (_TEMPLATES_DIR / "pve2wiki_admin.html").read_text(encoding="utf-8")
