"""Running the break classifier over every candidate in the universe.

This is affordable precisely because breaks are rare. Confirming every deal
would mean tens of thousands of documents; confirming every break means a few
hundred, and the break is the variable the rest of the project depends on.

Two properties matter as much as the classification itself.

It does not lose work. The first version held every verdict in memory and wrote
at the end, so a single unresolvable host at candidate 175 of 451 discarded all
175. That is the same mistake the universe crawl made, in a second place, and it
is fixed the same way: failures are recorded as verdicts of their own and the
run carries on.

It resumes. Results are keyed by filing, so a re-run reads what is already there,
retries only what failed, and costs nothing for what did not.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from longstop.edgar.client import EdgarClient, FetchError
from longstop.edgar.documents import DocumentRef, document_text, filing_documents
from longstop.filings.breaks import NO_DOCUMENT, classify
from longstop.filings.sections import item_sections
from longstop.universe.forms import ITEM_TERMINATION

REPO_ROOT = Path(__file__).resolve().parents[3]
UNIVERSE = REPO_ROOT / "data" / "universe.jsonl"
BREAKS = REPO_ROOT / "data" / "breaks.jsonl"

FETCH_FAILED = "fetch_failed"

# Statuses worth retrying on a later run. A classification is final; an
# unreachable host is not.
RETRYABLE = {FETCH_FAILED}

ACCESSION_TXT = "-"

# EDGAR names exhibits in a handful of recognisable ways: dex1029.htm, ex99-1.htm,
# form8k102004ex10.htm. The fallback used to take the largest HTML file, which on
# one filing meant classifying a settlement agreement instead of the 8-K.
EXHIBIT_NAME = re.compile(r"(^|[^a-z])(d?ex|exhibit)[-_]?\d", re.IGNORECASE)
EIGHT_K_NAME = re.compile(r"8-?k", re.IGNORECASE)

# Two requests per candidate, both latency-bound. The shared rate limiter keeps
# the total below the SEC's ceiling whatever this is set to.
WORKERS = 6


def primary_document(
    refs: list[DocumentRef], form: str, named: str | None = None
) -> DocumentRef | None:
    """The document that reports the item.

    The filing's own directory listing is not usable for this: its "type" field
    returns the icon name, "text.gif", rather than the document type. So the
    primary document recorded in the submissions API is used when there is one,
    and taking the largest HTML file is only a fallback, which a long exhibit
    can beat.
    """
    if named:
        for ref in refs:
            if ref.name == named:
                return ref
    typed = [r for r in refs if r.kind.strip().upper() == form.strip().upper()]
    if typed:
        return max(typed, key=lambda r: r.size)

    candidates = [
        r for r in refs
        if r.name.lower().endswith((".htm", ".html")) and not r.name.lower().startswith("r")
    ]
    if candidates:
        def rank(ref: DocumentRef) -> tuple[int, int, int]:
            looks_like_exhibit = bool(EXHIBIT_NAME.search(ref.name))
            names_the_form = bool(EIGHT_K_NAME.search(ref.name))
            # Not an exhibit first, then one that names the form, then size.
            return (0 if looks_like_exhibit else 1, 1 if names_the_form else 0, ref.size)

        return max(candidates, key=rank)

    plain = [r for r in refs if r.name.lower().endswith(".txt") and ACCESSION_TXT not in r.name]
    return max(plain, key=lambda r: r.size) if plain else None


def _empty(status: str, document: str | None = None) -> dict:
    return {
        "status": status,
        "reasons": [],
        "break_fee_usd": None,
        "excerpt": "",
        "evidence": [],
        "document": document,
    }


def confirm_episode(client: EdgarClient, episode: dict) -> dict:
    cik = episode["cik"]
    accession = episode.get("resolved_accession")
    form = episode.get("resolved_form") or "8-K"
    if not accession:
        return _empty(NO_DOCUMENT)

    try:
        refs = filing_documents(client, cik, accession)
        ref = primary_document(refs, form, episode.get("resolved_document"))
        if ref is None:
            return _empty(NO_DOCUMENT)
        text = document_text(client, cik, accession, ref.name)
    except FetchError as exc:
        return _empty(FETCH_FAILED) | {"excerpt": str(exc)[:200]}

    if text is None:
        return _empty(NO_DOCUMENT, ref.name)

    # The whole document goes in as well, so the abbreviations it defines for
    # itself can be resolved. Sections routinely say nothing more than that "the
    # BCA was terminated".
    verdict = classify(item_sections(text).get(ITEM_TERMINATION), text)
    payload = asdict(verdict)
    payload["reasons"] = list(verdict.reasons)
    payload["evidence"] = list(verdict.evidence)
    payload["document"] = ref.name
    return payload


def _key(row: dict) -> tuple:
    return (row["cik"], row["announced"], row.get("accession") or row.get("resolved_accession"))


def confirm_all(
    client: EdgarClient,
    labels: tuple[str, ...] = ("terminated",),
    resume: bool = True,
    workers: int = WORKERS,
    since: str | None = None,
) -> dict:
    """`since` drops candidates announced before it.

    Break detection needs an 8-K item code and the SEC only numbered items from
    2004, so candidates from before that carry a label the evidence cannot
    support. Reading their filings spends requests to produce verdicts that were
    never going to mean anything.
    """
    episodes = [json.loads(line) for line in UNIVERSE.read_text().splitlines() if line]
    candidates = [e for e in episodes if e["label"] in labels]
    excluded = 0
    if since:
        before = len(candidates)
        candidates = [e for e in candidates if e["announced"] >= since]
        excluded = before - len(candidates)

    done: dict[tuple, dict] = {}
    if resume and BREAKS.exists():
        for line in BREAKS.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            if row.get("status") not in RETRYABLE:
                done[_key(row)] = row

    results: list[dict] = []
    reused = 0
    outstanding: list[dict] = []
    for episode in candidates:
        key = _key(episode)
        if key in done:
            results.append(done[key])
            reused += 1
        else:
            outstanding.append(episode)

    write_lock = threading.Lock()
    finished = 0

    def work(episode: dict) -> dict:
        verdict = confirm_episode(client, episode)
        row = {
            "cik": episode["cik"],
            "company": episode["company"],
            "announced": episode["announced"],
            "resolved_on": episode["resolved_on"],
            "days_to_resolution": episode["days_to_resolution"],
            "accession": episode.get("resolved_accession"),
            **verdict,
        }
        # Written as it goes. Losing a hundred and seventy five verdicts to one
        # bad host happened once and does not need to happen twice.
        with write_lock:
            with BREAKS.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
        return row

    if outstanding:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(work, episode) for episode in outstanding]
            for future in as_completed(futures):
                results.append(future.result())
                finished += 1
                if finished % 25 == 0 or finished == len(outstanding):
                    print(
                        f"[{finished:>4}/{len(outstanding)}] confirmed "
                        f"({reused} reused)",
                        file=sys.stderr,
                        flush=True,
                    )

    # Sorted and rewritten once, so the file holds one row per candidate in a
    # deterministic order rather than the append log that got it there.
    results.sort(key=lambda row: (row["announced"], row["cik"]))
    with BREAKS.open("w") as fh:
        for row in results:
            fh.write(json.dumps(row) + "\n")

    statuses = Counter(r["status"] for r in results)
    reasons = Counter(reason for r in results for reason in r["reasons"])
    fees = [r["break_fee_usd"] for r in results if r["break_fee_usd"]]
    return {
        "candidates": len(candidates),
        "excluded_before": since,
        "excluded_count": excluded,
        "reused_from_previous_run": reused,
        "status": dict(statuses),
        "reasons": dict(reasons.most_common()),
        "break_fee_extracted": len(fees),
        "retry_needed": statuses.get(FETCH_FAILED, 0),
        "written_to": str(BREAKS),
    }
