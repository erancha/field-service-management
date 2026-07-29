"""Checks that every "Contents:" link in the README jumps to a heading that actually exists.

The README is the public landing page. Each Contents link looks like `[Testing](#testing)` and is
meant to scroll to a matching heading. GitHub builds the `#testing` target automatically from the
heading text: lowercase it, drop punctuation, turn spaces into hyphens. If a link names a target no
heading produces, clicking it on GitHub goes nowhere. This test reproduces that same rule and fails
when a Contents link has no matching heading.
"""
import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"

_CONTENTS_LINK = re.compile(r"\[[^\]]+\]\(#([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)


def _heading_target(heading_text: str) -> str:
    """Build the `#` target GitHub generates for a heading: lowercase, no punctuation, spaces to hyphens."""
    target = heading_text.strip().lower()
    target = re.sub(r"[^\w\s-]", "", target)
    return target.replace(" ", "-")


def test_every_contents_link_reaches_a_heading():
    text = README.read_text(encoding="utf-8")
    real_targets = {_heading_target(h) for h in _HEADING.findall(text)}
    linked_targets = _CONTENTS_LINK.findall(text)

    assert linked_targets, "expected the README to have a Contents list with in-page links"
    missing = sorted(t for t in linked_targets if t not in real_targets)
    assert not missing, f"Contents links point at headings that do not exist: {missing}"
