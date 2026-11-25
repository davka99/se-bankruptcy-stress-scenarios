"""Render README.md, the decision memo and the Quarto report from templates and
reports/tables/key_numbers.json. Numbers are never typed into these documents by hand.

    python -m src.render_readme
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src import config

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

TARGETS = {
    config.DOCS / "README.template.md": config.ROOT / "README.md",
    config.DOCS / "decision_memo.template.md": config.REPORTS / "decision_memo.md",
    config.DOCS / "report.template.qmd": config.REPORTS / "site" / "index.qmd",
}


def render_text(template: str, numbers: dict) -> str:
    def sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in numbers:
            raise KeyError(f"Placeholder '{key}' missing from key_numbers.json")
        return str(numbers[key])

    return PLACEHOLDER.sub(sub, template)


def render_all(numbers: dict | None = None) -> dict[Path, str]:
    numbers = numbers or json.loads((config.TABLES / "key_numbers.json").read_text("utf-8"))
    out = {}
    for template, target in TARGETS.items():
        if template.exists():
            out[target] = render_text(template.read_text(encoding="utf-8"), numbers)
    return out


def main() -> None:
    for target, text in render_all().items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
