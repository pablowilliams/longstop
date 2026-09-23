"""Extracting deal terms for every episode, from the 8-K that announced it.

The cheap cut, deliberately. The full terms live in the merger agreement filed
as exhibit 2.1 and in the proxy, both of which run to hundreds of pages, and
crawling those for every deal is the largest job in this project. The 8-K that
reports entry into the agreement summarises the terms that matter in a couple of
pages, so it is tried first and the expensive sources stay unspent until the
coverage measured here says whether they are needed.

Finding that 8-K costs nothing. Every target's filing history is already cached
from the outcome pass, so the announcement 8-K is a lookup rather than a fetch.

What this file exists to measure is not the terms. It is the share of extractions
that satisfy the document's own arithmetic, premium against consideration over
unaffected price, because that is a claim the repository makes and has never
tested on a real filing.
"""
from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from longstop.edgar.client import EdgarClient, FetchError
from longstop.edgar.documents import document_text, filing_documents
from longstop.edgar.submissions import Company, Filing, fetch_company
import re

from longstop.filings.confirm import primary_document
from longstop.filings.terms import extract_terms, reconcile
from longstop.universe import forms

REPO_ROOT = Path(__file__).resolve().parents[3]
UNIVERSE = REPO_ROOT / "data" / "universe.jsonl"
TERMS = REPO_ROOT / "data" / "terms.jsonl"

WORKERS = 6

# The 8-K reporting entry into the merger agreement is filed within days of
# signing, which is usually before the proxy. The window reaches back from the
# first proxy filing and a little past it, because amendments and re-signings do
# happen.
LOOKBACK_DAYS = 200
LOOKAHEAD_DAYS = 120

# The 8-K body reports entry into the agreement in legal terms and never states
# the premium or the price it is a premium to. Measured on two hundred real
# deals: cash per share 61%, termination fee 36%, premium and unaffected price
# 0.0% and 0.0%. Those two live in the press release filed alongside as exhibit
# 99.1, which is one more document from an accession already indexed.
#
# Without them there is no arithmetic to check an extraction against, so the
# press release is what makes the reconciliation measurable at all.
PRESS_RELEASE = re.compile(r"(^|[^a-z])(d?ex)-?99", re.IGNORECASE)

FETCH_FAILED = "fetch_failed"
NO_ANNOUNCEMENT_8K = "no_announcement_8k"
NO_DOCUMENT = "no_document"
EXTRACTED = "extracted"

RETRYABLE = {FETCH_FAILED}


def announcement_8k(company: Company, announced: str, last_announcement: str) -> Filing | None:
    """The 8-K reporting entry into a material definitive agreement, nearest signing."""
    start = date.fromisoformat(announced) - timedelta(days=LOOKBACK_DAYS)
    end = date.fromisoformat(last_announcement) + timedelta(days=LOOKAHEAD_DAYS)
    candidates = [
        f for f in company.filings
        if f.form.startswith("8-K")
        and forms.has_item(f.items, forms.ITEM_MATERIAL_AGREEMENT)
        and start <= date.fromisoformat(f.filed) <= end
    ]
    if not candidates:
        return None
    # Nearest to the announcement, which is the signing rather than a later
    # amendment to the same agreement.
    target = date.fromisoformat(announced)
    return min(candidates, key=lambda f: abs((date.fromisoformat(f.filed) - target).days))


def press_release(refs) -> object | None:
    candidates = [
        r for r in refs
        if PRESS_RELEASE.search(r.name) and r.name.lower().endswith((".htm", ".html", ".txt"))
    ]
    return max(candidates, key=lambda r: r.size) if candidates else None


def extract_from_proxy(client: EdgarClient, episode: dict) -> dict:
    """Read the merger proxy instead of the 8-K.

    The 8-K route was measured first because it is cheap, and it tops out at
    around a third of deals: only 38% of announcement 8-Ks attach the merger
    agreement, and the body states the termination fee 36% of the time and the
    unaffected price almost never. The proxy has no such gap. It is filed for
    every deal in this universe, by definition, because that is how the universe
    was built, and it carries the terms summary and the fairness opinion that
    states both the price and the premium.

    It is also much larger, which is the trade the pilot exists to price.
    """
    accessions = episode.get("announcement_accessions") or []
    if not accessions:
        return {"status": NO_ANNOUNCEMENT_8K}
    accession = accessions[0]
    try:
        refs = filing_documents(client, episode["cik"], accession)
        ref = primary_document(refs, "DEFM14A")
        if ref is None:
            return {"status": NO_DOCUMENT, "accession": accession}
        text = document_text(client, episode["cik"], accession, ref.name)
    except FetchError as exc:
        return {"status": FETCH_FAILED, "accession": accession, "error": str(exc)[:160]}
    if text is None:
        return {"status": NO_DOCUMENT, "accession": accession, "document": ref.name}

    terms = extract_terms(text)
    check = reconcile(terms)
    return {
        "status": EXTRACTED,
        "accession": accession,
        "document": ref.name,
        "source": "proxy",
        "chars": len(text),
        "terms": asdict(terms),
        "consideration": terms.consideration,
        "break_fee_pct": terms.break_fee_pct,
        "reconciliation": asdict(check),
    }


def extract_for_episode(client: EdgarClient, episode: dict, company: Company) -> dict:
    filing = announcement_8k(company, episode["announced"], episode["last_announcement"])
    if filing is None:
        return {"status": NO_ANNOUNCEMENT_8K}

    try:
        refs = filing_documents(client, episode["cik"], filing.accession)
        ref = primary_document(refs, filing.form, filing.primary_document or None)
        if ref is None:
            return {"status": NO_DOCUMENT, "accession": filing.accession}
        text = document_text(client, episode["cik"], filing.accession, ref.name)
    except FetchError as exc:
        return {"status": FETCH_FAILED, "accession": filing.accession, "error": str(exc)[:160]}

    if text is None:
        return {"status": NO_DOCUMENT, "accession": filing.accession, "document": ref.name}

    release = press_release(refs)
    release_text = None
    if release is not None:
        try:
            release_text = document_text(client, episode["cik"], filing.accession, release.name)
        except FetchError:
            release_text = None

    combined = text if release_text is None else f"{text}\n\n{release_text}"
    terms = extract_terms(combined)
    check = reconcile(terms)
    return {
        "status": EXTRACTED,
        "accession": filing.accession,
        "document": ref.name,
        "press_release": release.name if release is not None else None,
        "filed": filing.filed,
        "terms": asdict(terms),
        "consideration": terms.consideration,
        "break_fee_pct": terms.break_fee_pct,
        "reconciliation": asdict(check),
    }


def _key(row: dict) -> tuple:
    return (row["cik"], row["announced"])


def extract_all(
    client: EdgarClient,
    since: str | None = None,
    until: str | None = None,
    labels: tuple[str, ...] = ("completed", "completed_shell", "terminated"),
    resume: bool = True,
    workers: int = WORKERS,
    limit: int | None = None,
    source: str = "8k",
) -> dict:
    episodes = [json.loads(line) for line in UNIVERSE.read_text().splitlines() if line]
    wanted = [e for e in episodes if e["label"] in labels]
    if since:
        wanted = [e for e in wanted if e["announced"] >= since]
    if until:
        wanted = [e for e in wanted if e["announced"] < until]
    if limit:
        wanted = wanted[:limit]

    done: dict[tuple, dict] = {}
    if resume and TERMS.exists():
        for line in TERMS.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            if row.get("status") not in RETRYABLE:
                done[_key(row)] = row

    results: list[dict] = [done[_key(e)] for e in wanted if _key(e) in done]
    reused = len(results)
    outstanding = [e for e in wanted if _key(e) not in done]

    write_lock = threading.Lock()
    finished = 0

    def work(episode: dict) -> dict:
        if source == "proxy":
            payload = extract_from_proxy(client, episode)
            row = {
                "cik": episode["cik"], "company": episode["company"],
                "announced": episode["announced"], "label": episode["label"], **payload,
            }
            with write_lock:
                with TERMS.open("a") as fh:
                    fh.write(json.dumps(row) + "\n")
            return row
        try:
            company = fetch_company(
                client,
                episode["cik"],
                since=(
                    date.fromisoformat(episode["announced"]) - timedelta(days=LOOKBACK_DAYS + 400)
                ).isoformat(),
            )
        except FetchError as exc:
            payload = {"status": FETCH_FAILED, "error": str(exc)[:160]}
        else:
            payload = (
                extract_for_episode(client, episode, company)
                if company is not None
                else {"status": NO_ANNOUNCEMENT_8K}
            )
        row = {
            "cik": episode["cik"],
            "company": episode["company"],
            "announced": episode["announced"],
            "label": episode["label"],
            **payload,
        }
        with write_lock:
            with TERMS.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
        return row

    if outstanding:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(work, episode) for episode in outstanding]
            for future in as_completed(futures):
                results.append(future.result())
                finished += 1
                if finished % 250 == 0 or finished == len(outstanding):
                    print(
                        f"[{finished:>5}/{len(outstanding)}] extracted ({reused} reused)",
                        file=sys.stderr,
                        flush=True,
                    )

    results.sort(key=lambda row: (row["announced"], row["cik"]))
    with TERMS.open("w") as fh:
        for row in results:
            fh.write(json.dumps(row) + "\n")

    return summarise_terms(results)


def summarise_terms(rows: list[dict]) -> dict:
    extracted = [r for r in rows if r["status"] == EXTRACTED]
    fields = (
        "cash_per_share", "exchange_ratio", "stated_premium_pct", "unaffected_price",
        "termination_fee_usd", "parent_termination_fee_usd", "equity_value_usd",
        "outside_date", "financing_condition",
    )
    coverage = {
        field: round(
            sum(1 for r in extracted if r["terms"].get(field) not in (None, "")) / len(extracted), 4
        )
        for field in fields
    } if extracted else {}

    with_release = sum(1 for r in extracted if r.get("press_release"))
    checks = Counter(r["reconciliation"]["status"] for r in extracted)
    checkable = checks["reconciled"] + checks["mismatch"]
    errors = sorted(
        r["reconciliation"]["absolute_error_pp"]
        for r in extracted
        if r["reconciliation"]["absolute_error_pp"] is not None
    )
    return {
        "episodes": len(rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "field_coverage": coverage,
        "consideration": dict(Counter(r["consideration"] for r in extracted)),
        "with_press_release": with_release,
        "reconciliation": dict(checks),
        "checkable": checkable,
        "reconciled_share_of_checkable": (
            round(checks["reconciled"] / checkable, 4) if checkable else None
        ),
        "reconciled_share_of_extracted": (
            round(checks["reconciled"] / len(extracted), 4) if extracted else None
        ),
        "premium_error_pp": {
            "n": len(errors),
            "median": errors[len(errors) // 2] if errors else None,
            "p90": errors[(len(errors) * 9) // 10] if errors else None,
        },
        "retry_needed": dict(Counter(r["status"] for r in rows)).get(FETCH_FAILED, 0),
    }
