"""The committed README, memo and report must equal a fresh rendering of their templates."""

import json

import pytest

from src import config, render_readme

pytestmark = pytest.mark.skipif(
    not (config.TABLES / "key_numbers.json").exists(), reason="key numbers not built"
)


def test_documents_match_rendered_templates():
    for target, text in render_readme.render_all().items():
        assert target.exists(), f"{target} not rendered"
        assert target.read_text(encoding="utf-8") == text, f"{target} is out of date"


def test_every_placeholder_has_a_number():
    numbers = json.loads((config.TABLES / "key_numbers.json").read_text(encoding="utf-8"))
    for template in render_readme.TARGETS:
        if template.exists():
            render_readme.render_text(template.read_text(encoding="utf-8"), numbers)


def test_missing_placeholder_raises():
    with pytest.raises(KeyError):
        render_readme.render_text("{{ nope }}", {})
