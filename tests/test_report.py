"""The committed numbers must be the numbers the code produces.

This is the check that makes the README falsifiable. If the labelling rules
change and the tables do not, CI fails rather than leaving a document quoting a
figure the data no longer supports.
"""
from pathlib import Path

import pytest

from longstop import report

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "data" / "universe.jsonl"
RESULTS = ROOT / "results" / "universe.txt"

pytestmark = pytest.mark.skipif(
    not UNIVERSE.exists() or not RESULTS.exists(),
    reason="universe not built; run make universe",
)


def test_committed_table_matches_a_fresh_render():
    summary = report.summarise(report.load(UNIVERSE))
    assert report.render(summary).strip() == RESULTS.read_text().strip()


def test_every_episode_carries_a_known_label():
    from longstop.universe.outcomes import LABELS

    for episode in report.load(UNIVERSE):
        assert episode["label"] in LABELS


def test_resolved_episodes_carry_a_resolution_date():
    from longstop.universe.outcomes import BREAK_LABELS, COMPLETED_LABELS

    for episode in report.load(UNIVERSE):
        if episode["label"] in COMPLETED_LABELS + BREAK_LABELS:
            assert episode["resolved_on"], episode
            assert episode["days_to_resolution"] is not None
            assert episode["days_to_resolution"] >= 0


def test_the_readme_quotes_the_numbers_the_code_produced():
    from longstop import docs

    if not docs.RENDERED.exists():
        import pytest as _pytest

        _pytest.skip("universe not built")
    assert docs.is_in_sync(), "README is stale. Run make report."
