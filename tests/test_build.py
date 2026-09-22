"""The regression test for the failure that cost a full crawl.

Stage two resolved six thousand targets, hit one transient DNS failure, and
exited with nothing written. Everything it had done was in memory. A long crawl
has to survive a bad host.
"""
from __future__ import annotations

import json

import pytest

from longstop.edgar.client import FetchError
from longstop.edgar.submissions import Company, Filing
from longstop.universe import build


class StubClient:
    """Stands in for EdgarClient. Only the progress log touches it here."""

    stats = {"hits": 0, "misses": 0, "retries": 0}


def _company(cik: int) -> Company:
    return Company(
        cik=cik,
        name=f"Target {cik}",
        sic="3674",
        sic_description="Semiconductors",
        tickers=("T",),
        exchanges=("Nasdaq",),
        filings=(
            Filing("10-K", "2018-03-01", "", "a", ""),
            Filing("25-NSE", "2019-05-02", "", "b", ""),
        ),
    )


@pytest.fixture
def staged(tmp_path, monkeypatch):
    announcements = tmp_path / "announcements.jsonl"
    with announcements.open("w") as fh:
        for cik in (1, 2, 3):
            fh.write(json.dumps({
                "form": "DEFM14A", "company": f"Target {cik}", "cik": cik,
                "filed": "2019-01-10", "path": f"edgar/data/{cik}/0000000-19-000001.txt",
            }) + "\n")
    monkeypatch.setattr(build, "ANNOUNCEMENTS", announcements)
    monkeypatch.setattr(build, "UNIVERSE", tmp_path / "universe.jsonl")
    return tmp_path


def test_one_unreachable_target_does_not_discard_the_others(staged, monkeypatch):
    def fetch(_client, cik, since=None):
        assert since and since < "2019-01-10", "history must be trimmed, not truncated"
        if cik == 2:
            raise FetchError("dns failed")
        return _company(cik)

    monkeypatch.setattr(build, "fetch_company", fetch)
    stats = build_stats = build.build_universe(client=StubClient(), workers=1)

    assert build_stats["targets_unreachable"] == 1
    assert build_stats["unreachable_ciks"] == [2]
    assert stats["episodes"] == 2

    written = [json.loads(l) for l in (staged / "universe.jsonl").read_text().splitlines() if l]
    assert [row["cik"] for row in written] == [1, 3]
    assert {row["label"] for row in written} == {"completed"}


def test_a_target_with_no_submissions_is_counted_separately(staged, monkeypatch):
    monkeypatch.setattr(
        build, "fetch_company",
        lambda _c, cik, since=None: None if cik == 3 else _company(cik),
    )
    stats = build.build_universe(client=StubClient(), workers=1)
    assert stats["targets_without_submissions"] == 1
    assert stats["episodes"] == 2


def test_the_crawl_is_threaded_but_the_output_is_deterministic(staged, monkeypatch):
    # Episodes come back in completion order from the pool and are sorted before
    # they are written, so the file does not depend on which worker finished first.
    monkeypatch.setattr(build, "fetch_company", lambda _c, cik, since=None: _company(cik))
    build.build_universe(client=StubClient(), workers=1)
    single = (staged / "universe.jsonl").read_text()
    build.build_universe(client=StubClient(), workers=8)
    threaded = (staged / "universe.jsonl").read_text()
    assert single == threaded
