"""Assembling the deal universe, in two stages.

Stage one reads the quarterly filing indexes and keeps the target-side merger
filings. Stage two asks data.sec.gov what each of those targets filed afterwards
and derives an outcome from it.

Both stages are resumable and neither is all-or-nothing. Stage one caches the
filtered rows per quarter. Stage two caches every response and records the
targets it could not reach rather than discarding the ones it could, which is a
lesson from losing a six thousand target crawl to a single DNS failure.

Stage two is threaded. The SEC allows ten requests a second and the limiter keeps
the total below that, but a filer's submissions JSON runs to megabytes, so one
request at a time waits on the network rather than on the allowance. Serially it
projected to over eight hours.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from longstop.edgar.client import EdgarClient, FetchError
from longstop.edgar.index import IndexRow, iter_quarters, quarter_rows
from longstop.edgar.submissions import Company, fetch_company
from longstop.universe import forms
from longstop.universe.episodes import DEFAULT_GAP_DAYS, group_episodes
from longstop.universe.outcomes import label_episode

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data"
ANNOUNCEMENTS = DATA / "announcements.jsonl"
UNIVERSE = DATA / "universe.jsonl"
INDEX_CACHE = DATA / "cache" / "index"

WORKERS = 8

# History is trimmed either side of the announcement, so the pre-announcement
# periodic reports that prove the filer was a public registrant survive the trim.
HISTORY_LEAD_DAYS = 1200


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_announcements(client: EdgarClient, start: int, end: int) -> dict:
    """Stage one. Returns index coverage statistics."""
    rows: list[IndexRow] = []
    seen_total = 0
    unparsed_total = 0
    missing: list[str] = []

    quarters = list(iter_quarters(start, end))
    for position, (year, quarter) in enumerate(quarters, start=1):
        result = quarter_rows(client, year, quarter, forms.is_announcement, INDEX_CACHE)
        if result is None:
            missing.append(f"{year}Q{quarter}")
            continue
        quarter_hits, seen, unparsed = result
        rows.extend(quarter_hits)
        seen_total += seen
        unparsed_total += unparsed
        _log(
            f"[{position:>3}/{len(quarters)}] {year}Q{quarter}  "
            f"{len(quarter_hits):>4} announcements from {seen:>7} filings"
            + (f"  ({unparsed} unparsed)" if unparsed else "")
        )

    ANNOUNCEMENTS.parent.mkdir(parents=True, exist_ok=True)
    with ANNOUNCEMENTS.open("w") as fh:
        for row in sorted(rows, key=lambda r: (r.filed, r.cik)):
            fh.write(json.dumps(asdict(row)) + "\n")

    return {
        "quarters_requested": len(quarters),
        "quarters_missing": missing,
        "filings_scanned": seen_total,
        "rows_unparsed": unparsed_total,
        "announcement_filings": len(rows),
        "distinct_ciks": len({row.cik for row in rows}),
    }


def _announcements_by_cik() -> tuple[dict[int, list[tuple[str, str, str]]], dict[int, str]]:
    by_cik: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
    names: dict[int, str] = {}
    for line in ANNOUNCEMENTS.read_text().splitlines():
        if not line:
            continue
        row = json.loads(line)
        by_cik[row["cik"]].append((row["form"], row["filed"], Path(row["path"]).stem))
        names.setdefault(row["cik"], row["company"])
    return by_cik, names


def resolution_dates(company: Company) -> list[str]:
    """Dates on which some deal of this company's ended.

    A termination reported under item 1.02, or a deregistration. These separate
    one company's consecutive deals from one company's single long deal, which a
    time gap on its own cannot do.
    """
    marks: list[str] = []
    for filing in company.filings:
        if forms.is_deregistration(filing.form):
            marks.append(filing.filed)
        elif filing.form.startswith("8-K") and forms.has_item(filing.items, forms.ITEM_TERMINATION):
            marks.append(filing.filed)
    return sorted(marks)


def _episode_rows(
    cik: int,
    company: Company,
    fallback_name: str,
    announcements: list[tuple[str, str, str]],
    gap_days: int,
    data_cut: date,
) -> list[dict]:
    rows: list[dict] = []
    marks = resolution_dates(company)
    episodes = group_episodes(cik, fallback_name, announcements, gap_days, marks)
    for position, episode in enumerate(episodes):
        following = episodes[position + 1].announced if position + 1 < len(episodes) else None
        outcome = label_episode(
            announced=episode.announced,
            last_announcement=episode.last_announcement,
            filings=company.filings,
            data_cut=data_cut,
            next_announcement=following,
        )
        rows.append(
            {
                "cik": cik,
                "company": company.name or episode.company,
                "sic": company.sic,
                "sic_description": company.sic_description,
                "shell": forms.is_shell_sic(company.sic) or outcome.label == "completed_shell",
                "tickers": list(company.tickers),
                "exchanges": list(company.exchanges),
                "announced": episode.announced,
                "last_announcement": episode.last_announcement,
                "announcement_forms": episode.forms,
                "announcement_accessions": [acc for _, _, acc in episode.filings],
                "label": outcome.label,
                "resolved_on": outcome.resolved_on,
                "days_to_resolution": outcome.days_to_resolution,
                "resolved_accession": outcome.resolved_accession,
                "resolved_form": outcome.resolved_form,
                "resolved_document": outcome.resolved_document,
                "evidence": list(outcome.evidence),
            }
        )
    return rows


def build_universe(
    client: EdgarClient, gap_days: int = DEFAULT_GAP_DAYS, workers: int = WORKERS
) -> dict:
    """Stage two. Returns episode and labelling statistics."""
    if not ANNOUNCEMENTS.exists():
        raise FileNotFoundError(f"{ANNOUNCEMENTS} not found. Run stage one first.")

    by_cik, names = _announcements_by_cik()
    data_cut = date.today()
    episodes_out: list[dict] = []
    no_submissions: list[int] = []
    unreachable: list[int] = []
    total = len(by_cik)

    def load(cik: int) -> tuple[int, Company | None]:
        earliest = min(filed for _, filed, _ in by_cik[cik])
        since = (date.fromisoformat(earliest) - timedelta(days=HISTORY_LEAD_DAYS)).isoformat()
        return cik, fetch_company(client, cik, since=since)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load, cik): cik for cik in sorted(by_cik)}
        for future in as_completed(futures):
            done += 1
            cik = futures[future]
            try:
                cik, company = future.result()
            except FetchError as exc:
                unreachable.append(cik)
                _log(f"  ! {cik} unreachable, continuing: {exc}")
                continue
            if company is None:
                no_submissions.append(cik)
                continue
            episodes_out.extend(
                _episode_rows(
                    cik, company, names.get(cik, ""), by_cik[cik], gap_days, data_cut
                )
            )
            if done % 250 == 0 or done == total:
                _log(
                    f"[{done:>5}/{total}] targets resolved, {len(episodes_out)} episodes, "
                    f"cache hits {client.stats['hits']}"
                )

    with UNIVERSE.open("w") as fh:
        for episode in sorted(episodes_out, key=lambda e: (e["announced"], e["cik"])):
            fh.write(json.dumps(episode) + "\n")

    return {
        "targets": total,
        "targets_without_submissions": len(no_submissions),
        "targets_unreachable": len(unreachable),
        "unreachable_ciks": unreachable[:50],
        "episodes": len(episodes_out),
        "episode_gap_days": gap_days,
        "workers": workers,
        "data_cut": data_cut.isoformat(),
    }
