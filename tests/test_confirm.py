"""The regression tests for losing work, twice.

The universe crawl lost six thousand resolved targets to one DNS failure. Break
confirmation then lost a hundred and seventy five verdicts to another one, in a
different file, for the same reason. Both are covered here.
"""
from __future__ import annotations

import json

import pytest

from longstop.edgar.client import FetchError
from longstop.edgar.documents import DocumentRef
from longstop.filings import confirm

MERGER_8K = """On 1 March 2019 the Company entered into an Agreement and Plan of Merger
(the "Merger Agreement").

Item 1.02. Termination of a Material Definitive Agreement.

On 26 June 2020 the Merger Agreement was terminated following the antitrust
action brought by the Department of Justice.
"""


class StubClient:
    stats = {"hits": 0, "misses": 0, "retries": 0}


def episode(cik: int, accession: str = "0001-19-000001") -> dict:
    return {
        "cik": cik,
        "company": f"Target {cik}",
        "announced": "2019-01-10",
        "resolved_on": "2020-06-26",
        "days_to_resolution": 533,
        "resolved_accession": accession,
        "resolved_form": "8-K",
        "resolved_document": "d8k.htm",
        "label": "terminated",
    }


@pytest.fixture
def staged(tmp_path, monkeypatch):
    universe = tmp_path / "universe.jsonl"
    with universe.open("w") as fh:
        for cik in (1, 2, 3):
            fh.write(json.dumps(episode(cik)) + "\n")
    monkeypatch.setattr(confirm, "UNIVERSE", universe)
    monkeypatch.setattr(confirm, "BREAKS", tmp_path / "breaks.jsonl")
    monkeypatch.setattr(
        confirm, "filing_documents",
        lambda _c, _cik, _acc: [DocumentRef(name="d8k.htm", kind="text.gif", size=1000)],
    )
    return tmp_path


def test_one_unreachable_filing_does_not_discard_the_verdicts_already_made(staged, monkeypatch):
    def fetch(_client, cik, _accession, _name):
        if cik == 2:
            raise FetchError("dns failed")
        return MERGER_8K

    monkeypatch.setattr(confirm, "document_text", fetch)
    stats = confirm.confirm_all(StubClient(), workers=1)

    assert stats["status"]["confirmed"] == 2
    assert stats["retry_needed"] == 1
    rows = [json.loads(l) for l in (staged / "breaks.jsonl").read_text().splitlines() if l]
    assert len(rows) == 3
    assert {row["cik"] for row in rows if row["status"] == "confirmed"} == {1, 3}


def test_a_rerun_retries_only_what_failed(staged, monkeypatch):
    attempts: list[int] = []

    def flaky(_client, cik, _accession, _name):
        attempts.append(cik)
        if cik == 2 and attempts.count(2) == 1:
            raise FetchError("dns failed")
        return MERGER_8K

    monkeypatch.setattr(confirm, "document_text", flaky)
    confirm.confirm_all(StubClient(), workers=1)
    first_pass = len(attempts)

    stats = confirm.confirm_all(StubClient(), workers=1)
    assert stats["reused_from_previous_run"] == 2
    assert stats["status"]["confirmed"] == 3
    assert len(attempts) == first_pass + 1, "only the failure should have been retried"


def test_the_final_file_holds_one_row_per_candidate_not_an_append_log(staged, monkeypatch):
    monkeypatch.setattr(confirm, "document_text", lambda *_: MERGER_8K)
    confirm.confirm_all(StubClient(), workers=1)
    confirm.confirm_all(StubClient(), workers=1)
    rows = [json.loads(l) for l in (staged / "breaks.jsonl").read_text().splitlines() if l]
    assert len(rows) == 3


def test_the_named_primary_document_beats_the_largest_file():
    refs = [
        DocumentRef(name="d8k.htm", kind="text.gif", size=4_000),
        DocumentRef(name="dex21.htm", kind="text.gif", size=400_000),
    ]
    assert confirm.primary_document(refs, "8-K", "d8k.htm").name == "d8k.htm"
    # And without the name, the exhibit is still avoided on its own merits.
    assert confirm.primary_document(refs, "8-K").name == "d8k.htm"


def test_threading_does_not_change_the_file(staged, monkeypatch):
    monkeypatch.setattr(confirm, "document_text", lambda *_: MERGER_8K)
    confirm.confirm_all(StubClient(), workers=1)
    single = (staged / "breaks.jsonl").read_text()
    (staged / "breaks.jsonl").unlink()
    confirm.confirm_all(StubClient(), workers=6, resume=False)
    assert (staged / "breaks.jsonl").read_text() == single


def test_candidates_before_the_usable_window_are_skipped(staged, monkeypatch):
    universe = staged / "universe.jsonl"
    with universe.open("a") as fh:
        old = episode(9)
        old["announced"] = "2002-04-01"
        fh.write(json.dumps(old) + "\n")
    monkeypatch.setattr(confirm, "document_text", lambda *_: MERGER_8K)
    stats = confirm.confirm_all(StubClient(), workers=1, since="2007-01-01")
    assert stats["excluded_count"] == 1
    assert stats["candidates"] == 3


def test_an_exhibit_is_not_mistaken_for_the_filing():
    # dex1029.htm is a settlement agreement. Taking the largest HTML file
    # classified it instead of the 8-K.
    refs = [
        DocumentRef(name="d8k.htm", kind="text.gif", size=4_000),
        DocumentRef(name="dex1029.htm", kind="text.gif", size=400_000),
        DocumentRef(name="ex99-1.htm", kind="text.gif", size=90_000),
    ]
    assert confirm.primary_document(refs, "8-K").name == "d8k.htm"


def test_a_filing_named_for_its_form_wins_over_a_bigger_sibling():
    refs = [
        DocumentRef(name="form8k102004.htm", kind="text.gif", size=5_000),
        DocumentRef(name="attachment.htm", kind="text.gif", size=50_000),
    ]
    assert confirm.primary_document(refs, "8-K").name == "form8k102004.htm"
