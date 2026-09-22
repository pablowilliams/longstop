"""A company's full filing history, from data.sec.gov.

This is the whole of the outcome labelling. The submissions JSON carries every
filing a CIK has ever made, with the 8-K item codes attached, so whether a deal
closed or broke is answerable from metadata alone. No merger agreement is
downloaded to produce a label, which is what keeps phase 0 cheap enough to run
across twenty-four years.

Companies with more than a thousand filings have their older history split into
additional pages, which are fetched and concatenated here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from longstop.edgar.client import EdgarClient

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
PAGE_URL = "https://data.sec.gov/submissions/{name}"


@dataclass(frozen=True)
class Filing:
    form: str
    filed: str
    items: str
    accession: str
    report_date: str
    primary_document: str = ""

    @property
    def year(self) -> int:
        return int(self.filed[:4])


@dataclass(frozen=True)
class Company:
    cik: int
    name: str
    sic: str
    sic_description: str
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    filings: tuple[Filing, ...]


def _rows(block: dict) -> list[Filing]:
    forms = block.get("form", [])
    return [
        Filing(
            form=forms[i],
            filed=block["filingDate"][i],
            items=block.get("items", [""] * len(forms))[i] or "",
            accession=block["accessionNumber"][i],
            report_date=block.get("reportDate", [""] * len(forms))[i] or "",
            # Authoritative. The filing index's own "type" field returns the icon
            # name rather than the document type, so choosing the primary
            # document from the directory listing means guessing at the largest
            # file and hoping an exhibit is not bigger.
            primary_document=block.get("primaryDocument", [""] * len(forms))[i] or "",
        )
        for i in range(len(forms))
    ]


def fetch_company(client: EdgarClient, cik: int, since: str | None = None) -> Company | None:
    """The filing history, optionally trimmed to what a deal could need.

    A filer's submissions JSON runs to megabytes once its history is long, and
    companies with more than a thousand filings have the rest split into extra
    pages. Fetching all of them for every target turned a thirty minute crawl
    into an eight hour one.

    Passing `since` skips pages that end before that date. The caller sets it a
    few years before the announcement, which keeps the pre-announcement periodic
    reports that prove the filer was a public registrant while discarding the
    1990s.
    """
    body = client.get(SUBMISSIONS_URL.format(cik=cik), allow_404=True)
    if body is None:
        return None
    payload = json.loads(body)

    filings = _rows(payload["filings"]["recent"])
    for page in payload["filings"].get("files", []):
        if since and (page.get("filingTo") or "9999-12-31") < since:
            continue
        older = client.get(PAGE_URL.format(name=page["name"]), allow_404=True)
        if older is not None:
            filings.extend(_rows(json.loads(older)))

    filings.sort(key=lambda f: f.filed)
    return Company(
        cik=int(payload["cik"]),
        name=payload.get("name", ""),
        sic=payload.get("sic", ""),
        sic_description=payload.get("sicDescription", ""),
        tickers=tuple(payload.get("tickers", []) or []),
        exchanges=tuple(payload.get("exchanges", []) or []),
        filings=tuple(filings),
    )
