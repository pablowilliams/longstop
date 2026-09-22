"""Keeping the documents and the data in step.

Every figure the README quotes about the universe lives between two markers and
is written there by code. Typing a number into a document by hand is how a
document ends up quoting a figure the data stopped supporting three commits
ago, and the whole argument of this repository is that its numbers are
checkable.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
RENDERED = REPO_ROOT / "results" / "universe.txt"

START = "<!-- universe:start -->"
END = "<!-- universe:end -->"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)


def block(rendered: str) -> str:
    return f"{START}\n```\n{rendered.strip()}\n```\n{END}"


def sync(readme: Path = README, rendered: Path = RENDERED) -> bool:
    """Returns True when the README changed."""
    if not rendered.exists():
        raise FileNotFoundError(f"{rendered} not found. Run make report first.")
    text = readme.read_text()
    if not BLOCK.search(text):
        raise ValueError(f"{readme} has no {START} block to fill.")
    updated = BLOCK.sub(lambda _: block(rendered.read_text()), text)
    if updated == text:
        return False
    readme.write_text(updated)
    return True


def is_in_sync(readme: Path = README, rendered: Path = RENDERED) -> bool:
    match = BLOCK.search(readme.read_text())
    return bool(match) and match.group() == block(rendered.read_text())
