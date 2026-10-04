"""PVE2LLM frontend — served at /admin/pve2llm.

The page lives in ``templates/pve2llm_admin.html`` (like the other plugins); the
assistant name is substituted at render time.
"""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def build_page(assistant_name: str = "Winky") -> str:
    html = (_TEMPLATES_DIR / "pve2llm_admin.html").read_text(encoding="utf-8")
    return html.replace("__ASSISTANT__", assistant_name)
