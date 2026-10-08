"""Assembling the design matrix, and refusing to put the answer in it.

Two rules decide whether anything downstream means anything.

Nothing known only after the announcement may be a feature. days_to_resolution
and resolved_on are outcomes. So is the resolving accession. A model given those
would score beautifully and have learned that deals which closed, closed.

A break is only a break once its own 8-K says so. The universe labels an episode
terminated when the target files item 1.02 and carries on reporting, and reading
those documents showed that half of them terminated a credit facility, a lease or
an employee share plan rather than a merger. Those are not negatives either,
because the deal's real outcome is unknown, so they leave the frame entirely and
the report says how many left.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data"

WINDOW_START = "2007-01-01"   # first year with usable 8-K item coverage
WINDOW_END = "2025-01-01"     # the latest year is right censored by construction

COMPLETED = ("completed", "completed_shell")

# Features the filing states at announcement. Everything else is an outcome.
TERM_FIELDS = (
    "cash_per_share", "exchange_ratio", "stated_premium_pct",
    "termination_fee_usd", "parent_termination_fee_usd", "equity_value_usd",
)
FLAG_FIELDS = ("financing_condition", "go_shop", "hsr", "cfius", "tender_offer")

LEAKY = frozenset({
    "resolved_on", "days_to_resolution", "resolved_accession", "resolved_form",
    "resolved_document", "evidence", "label",
})


def _read(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _sector(sic: str) -> str:
    """SIC division. Two digits is enough signal and keeps the dummies countable."""
    digits = "".join(ch for ch in (sic or "") if ch.isdigit())
    return digits[:2] if len(digits) >= 2 else "unknown"


def build_frame(
    data_cut: date | None = None,
    window_end: str = WINDOW_END,
    include_pending: bool = False,
) -> pd.DataFrame:
    """The design matrix.

    include_pending adds deals that have not resolved yet, as censored
    observations. The classifier cannot use them, because they have no label.
    Survival analysis can, and that is most of the reason to use it: a deal that
    has run 250 days without breaking is evidence even though nobody knows how it
    ends. Pending is used and unresolved is not: pending means the outcome has
    not happened, unresolved means the filings could not show what happened, and
    treating the second as censored would quietly assume it had not.
    """
    data_cut = data_cut or date.today()
    universe = _read("universe.jsonl")
    verdicts = {(r["cik"], r["announced"]): r for r in _read("breaks.jsonl")}
    terms = {(r["cik"], r["announced"]): r for r in _read("terms.jsonl")}

    rows: list[dict] = []
    for episode in universe:
        if not (WINDOW_START <= episode["announced"] < window_end):
            continue
        label = episode["label"]
        allowed = COMPLETED + ("terminated",) + (("pending",) if include_pending else ())
        if label not in allowed:
            continue

        key = (episode["cik"], episode["announced"])
        if label == "pending":
            broke = None
        elif label == "terminated":
            status = verdicts.get(key, {}).get("status")
            if status != "confirmed":
                # Not shown to be a merger termination. Its real outcome is
                # unknown, so it is neither a positive nor a negative.
                continue
            broke = 1
        else:
            broke = 0

        announced = date.fromisoformat(episode["announced"])
        forms = " ".join(episode.get("announcement_forms") or [])
        row = {
            "cik": episode["cik"],
            "company": episode["company"],
            "announced": episode["announced"],
            "year": announced.year,
            "broke": broke,
            # Known at announcement, from the filing index alone.
            "sector": _sector(episode.get("sic", "")),
            "tender_offer_filing": int("14D9" in forms or "TO-T" in forms),
            "going_private": int("13E3" in forms),
            "shell": int(bool(episode.get("shell"))),
            "listed": int(bool(episode.get("tickers"))),
        }

        extracted = terms.get(key)
        if extracted and extracted.get("status") == "extracted":
            values = extracted["terms"]
            for field in TERM_FIELDS:
                row[field] = values.get(field)
            for field in FLAG_FIELDS:
                flag = values.get(field)
                row[field] = None if flag is None else int(bool(flag))
            row["break_fee_pct"] = extracted.get("break_fee_pct")
            row["consideration"] = extracted.get("consideration") or "unknown"
            row["has_terms"] = 1
        else:
            for field in TERM_FIELDS + FLAG_FIELDS:
                row[field] = None
            row["break_fee_pct"] = None
            row["consideration"] = "unknown"
            row["has_terms"] = 0

        # Survival framing. Completion and termination compete for the same deal,
        # so each is the other's censoring event, and deals never resolved are
        # censored at the data cut.
        resolved = episode.get("days_to_resolution")
        if resolved is None:
            row["duration_days"] = (data_cut - announced).days
            row["observed_break"] = 0
            row["observed_close"] = 0
        else:
            row["duration_days"] = max(int(resolved), 1)
            row["observed_break"] = broke
            row["observed_close"] = 1 - broke

        rows.append(row)

    frame = pd.DataFrame(rows)
    if not include_pending and len(frame):
        frame = frame[frame.broke.notna()].copy()
        frame["broke"] = frame.broke.astype(int)
    assert not (LEAKY & set(frame.columns)), "an outcome field reached the design matrix"
    return frame


def time_split(frame: pd.DataFrame, cutoff_year: int = 2019) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on the past, test on the future.

    A random split would let the model learn from 2022 to predict 2014, which is
    not a thing anyone can do, and would flatter every number that follows.
    """
    return frame[frame.year < cutoff_year].copy(), frame[frame.year >= cutoff_year].copy()
