"""Tests for finding and reading each deal's announcement 8-K."""
from __future__ import annotations

import json

import pytest

from longstop.edgar.client import FetchError
from longstop.edgar.documents import DocumentRef
from longstop.edgar.submissions import Company, Filing
from longstop.filings import deal_terms

ANNOUNCEMENT_8K = """Item 1.01. Entry into a Material Definitive Agreement.

On 19 February 2015 the Company entered into an Agreement and Plan of Merger
under which each share will be converted into the right to receive $58.50 per
share in cash, without interest. The consideration represents a premium of
approximately 30.0% to the closing price of $45.00 on 18 February 2015.

The Company will pay a termination fee of $95 million in specified
circumstances. The transaction values the Company at an equity value of
$3,100 million. Parent's obligations are not subject to any financing
condition. The End Date is December 31, 2015.
"""


def filing(form: str, filed: str, items: str = "", accession: str = "a") -> Filing:
    return Filing(
        form=form, filed=filed, items=items, accession=accession,
        report_date="", primary_document="d8k.htm",
    )


def company(filings: tuple[Filing, ...]) -> Company:
    return Company(
        cik=1, name="Target Inc", sic="3674", sic_description="Semiconductors",
        tickers=("T",), exchanges=("Nasdaq",), filings=filings,
    )


def test_the_nearest_item_101_filing_is_the_signing_not_a_later_amendment():
    subject = company((
        filing("8-K", "2015-02-20", "1.01", "signing"),
        filing("8-K", "2015-06-01", "1.01", "amendment"),
    ))
    found = deal_terms.announcement_8k(subject, "2015-02-19", "2015-04-01")
    assert found.accession == "signing"


def test_an_item_101_filing_far_outside_the_window_is_ignored():
    subject = company((filing("8-K", "2012-01-01", "1.01"),))
    assert deal_terms.announcement_8k(subject, "2015-02-19", "2015-02-19") is None


def test_an_eight_k_without_item_101_is_not_the_announcement():
    subject = company((filing("8-K", "2015-02-20", "2.02,9.01"),))
    assert deal_terms.announcement_8k(subject, "2015-02-19", "2015-02-19") is None


@pytest.fixture
def staged(tmp_path, monkeypatch):
    universe = tmp_path / "universe.jsonl"
    with universe.open("w") as fh:
        for cik in (1, 2):
            fh.write(json.dumps({
                "cik": cik, "company": f"Target {cik}", "announced": "2015-02-19",
                "last_announcement": "2015-04-01", "label": "completed",
            }) + "\n")
    monkeypatch.setattr(deal_terms, "UNIVERSE", universe)
    monkeypatch.setattr(deal_terms, "TERMS", tmp_path / "terms.jsonl")
    monkeypatch.setattr(
        deal_terms, "fetch_company",
        lambda _c, _cik, since=None: company((filing("8-K", "2015-02-20", "1.01"),)),
    )
    monkeypatch.setattr(
        deal_terms, "filing_documents",
        lambda *_: [DocumentRef(name="d8k.htm", kind="text.gif", size=4000)],
    )
    return tmp_path


def test_the_document_verifies_its_own_extraction_end_to_end(staged, monkeypatch):
    monkeypatch.setattr(deal_terms, "document_text", lambda *_: ANNOUNCEMENT_8K)
    stats = deal_terms.extract_all(deal_terms.EdgarClient(), workers=1)
    assert stats["status"]["extracted"] == 2
    assert stats["reconciliation"]["reconciled"] == 2
    assert stats["reconciled_share_of_checkable"] == 1.0
    assert stats["field_coverage"]["termination_fee_usd"] == 1.0
    assert stats["consideration"]["cash"] == 2


def test_one_unreachable_filing_does_not_discard_the_others(staged, monkeypatch):
    def fetch(_client, cik, _accession, _name):
        if cik == 2:
            raise FetchError("dns failed")
        return ANNOUNCEMENT_8K

    monkeypatch.setattr(deal_terms, "document_text", fetch)
    stats = deal_terms.extract_all(deal_terms.EdgarClient(), workers=1)
    assert stats["status"]["extracted"] == 1
    assert stats["retry_needed"] == 1
    rows = [json.loads(l) for l in (staged / "terms.jsonl").read_text().splitlines() if l]
    assert len(rows) == 2


def test_a_rerun_retries_only_what_failed(staged, monkeypatch):
    attempts: list[int] = []

    def flaky(_client, cik, _accession, _name):
        attempts.append(cik)
        if cik == 2 and attempts.count(2) == 1:
            raise FetchError("dns failed")
        return ANNOUNCEMENT_8K

    monkeypatch.setattr(deal_terms, "document_text", flaky)
    deal_terms.extract_all(deal_terms.EdgarClient(), workers=1)
    first = len(attempts)
    stats = deal_terms.extract_all(deal_terms.EdgarClient(), workers=1)
    assert stats["status"]["extracted"] == 2
    assert len(attempts) == first + 1


PRESS_RELEASE_TEXT = """EX-99.1

Acme to acquire Target Inc for $58.50 per share in cash

The purchase price represents a premium of approximately 30.0% to the closing
price of Target's common stock of $45.00 on 18 February 2015, the last trading
day before the announcement.
"""

LEGAL_8K_ONLY = """Item 1.01. Entry into a Material Definitive Agreement.

On 19 February 2015 the Company entered into an Agreement and Plan of Merger.
Each share will be converted into the right to receive $58.50 per share in cash.
The Company will pay a termination fee of $95 million.
"""


def test_without_the_press_release_there_is_no_arithmetic_to_check():
    # Measured on two hundred real deals: the 8-K body states the premium 0.0%
    # of the time, so the reconciliation cannot fire on it alone.
    from longstop.filings.terms import INSUFFICIENT, extract_terms, reconcile

    assert reconcile(extract_terms(LEGAL_8K_ONLY)).status == INSUFFICIENT


def test_the_press_release_supplies_what_the_filing_omits():
    from longstop.filings.terms import RECONCILED, extract_terms, reconcile

    combined = f"{LEGAL_8K_ONLY}\n\n{PRESS_RELEASE_TEXT}"
    terms = extract_terms(combined)
    assert terms.stated_premium_pct == 30.0
    assert terms.unaffected_price == 45.00
    assert reconcile(terms).status == RECONCILED


def test_the_press_release_exhibit_is_recognised():
    refs = [
        DocumentRef(name="d8k.htm", kind="", size=4000),
        DocumentRef(name="dex991.htm", kind="", size=9000),
        DocumentRef(name="dex21.htm", kind="", size=400000),
    ]
    assert deal_terms.press_release(refs).name == "dex991.htm"
    assert deal_terms.press_release([DocumentRef(name="dex21.htm", kind="", size=1)]) is None
