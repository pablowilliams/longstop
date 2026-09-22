"""Turning the universe into the numbers phase 0 is answerable for.

Every rate here carries its denominator. A completion rate quoted without the
count behind it is the single easiest number in this project to misuse, because
it is the base rate that makes accuracy meaningless in phase 2.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from longstop.universe.outcomes import (
    SURVIVAL_DAYS,
    BREAK_LABELS,
    COMPLETED_LABELS,
    EXCLUDED_LABELS,
    LABELS,
    TERMINATED,
    UNRESOLVED,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = REPO_ROOT / "data" / "universe.jsonl"
RESULTS = REPO_ROOT / "results"

RESOLVED = COMPLETED_LABELS + BREAK_LABELS

# The share of a year's episodes carrying any 8-K item evidence, below which the
# break label cannot be trusted for that year.
ITEM_COVERAGE_FLOOR = 0.5


def load(path: Path = UNIVERSE) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def summarise(
    episodes: list[dict],
    index_stats: dict | None = None,
    data_cut: date | None = None,
) -> dict:
    data_cut = data_cut or date.today()
    labels = Counter(e["label"] for e in episodes)
    by_year: dict[int, Counter] = defaultdict(Counter)
    by_year_rows: dict[int, list[dict]] = defaultdict(list)
    for episode in episodes:
        year = int(episode["announced"][:4])
        by_year[year][episode["label"]] += 1
        by_year_rows[year].append(episode)

    resolved = sum(labels[label] for label in RESOLVED)
    completed = sum(labels[label] for label in COMPLETED_LABELS)
    breaks = sum(labels[label] for label in BREAK_LABELS)
    durations = sorted(
        e["days_to_resolution"] for e in episodes
        if e["label"] in COMPLETED_LABELS and e["days_to_resolution"] is not None
    )
    # Whether a deal broke is read from 8-K item 1.02, and the SEC's numbered
    # item scheme only came in during 2004. Before that the label cannot fire,
    # so the early break rate is an artefact rather than a finding. This is
    # measured from the evidence rather than asserted from a date.
    coverage: dict[str, float] = {}
    for year, rows in sorted(by_year_rows.items()):
        with_item = sum(1 for row in rows if any(e.startswith("item") for e in row["evidence"]))
        coverage[str(year)] = round(with_item / len(rows), 4) if rows else 0.0
    usable = [year for year, share in coverage.items() if share >= ITEM_COVERAGE_FLOOR]
    window = {
        "first_usable_year": min(usable) if usable else None,
        "coverage_floor": ITEM_COVERAGE_FLOOR,
        "why": (
            "Break detection depends on 8-K item 1.02. The numbered item scheme "
            "arrived during 2004, so earlier deals cannot carry the evidence and "
            "their break rate is an artefact. Completions are unaffected, because "
            "a deregistration is a form type rather than an item code."
        ),
        # Structural, not statistical. A break usually becomes visible only once
        # the target has carried on reporting for a year after its last deal
        # filing, so any year ending less than that before the data cut is
        # under-labelled by construction however its rate happens to look.
        "right_censored_years": [
            year for year in sorted(by_year_rows)
            if (data_cut - date(year, 12, 31)).days < SURVIVAL_DAYS
        ],
        "data_cut": data_cut.isoformat(),
    }

    shells = [e for e in episodes if e.get("shell")]
    operating = [e for e in episodes if not e.get("shell")]
    operating_labels = Counter(e["label"] for e in operating)
    operating_resolved = sum(operating_labels[label] for label in RESOLVED)

    summary = {
        "episodes": len(episodes),
        "labels": {label: labels[label] for label in LABELS},
        "resolved": resolved,
        "break_events": breaks,
        "break_events_explicit": labels[TERMINATED],
        "completion_rate": round(completed / resolved, 4) if resolved else None,
        "completion_rate_denominator": resolved,
        "shell_episodes": len(shells),
        "operating_company_deals": {
            "episodes": len(operating),
            "resolved": operating_resolved,
            "break_events": sum(operating_labels[label] for label in BREAK_LABELS),
            "completion_rate": round(
                sum(operating_labels[label] for label in COMPLETED_LABELS) / operating_resolved, 4
            ) if operating_resolved else None,
        },
        "unresolved_share": round(labels[UNRESOLVED] / len(episodes), 4) if episodes else None,
        "excluded": {label: labels[label] for label in EXCLUDED_LABELS},
        "sign_to_close_days": {
            "n": len(durations),
            "p10": durations[len(durations) // 10] if durations else None,
            "median": durations[len(durations) // 2] if durations else None,
            "p90": durations[(len(durations) * 9) // 10] if durations else None,
        },
        "by_year": {
            str(year): dict(by_year[year]) for year in sorted(by_year)
        },
        "break_rate_by_year": {
            str(year): round(
                by_year[year][TERMINATED]
                / max(sum(by_year[year][label] for label in RESOLVED), 1),
                4,
            )
            for year in sorted(by_year)
        },
        "announcement_forms": dict(
            Counter(form for e in episodes for form in e["announcement_forms"]).most_common()
        ),
        "top_sic": dict(
            Counter(e["sic_description"] for e in episodes if e["sic_description"]).most_common(15)
        ),
        "item_code_coverage": coverage,
        "reliable_break_window": window,
        "caveats": [
            "Break detection depends on an 8-K item code, and the numbered item "
            "scheme arrived during 2004. Item evidence appears on 2.6% of 2001 "
            "episodes and over 75% from 2012, so any model using breaks should "
            "start from reliable_break_window.first_usable_year, not from 2001. "
            "Completions are unaffected.",
            "The most recent years are right censored. A break is often only "
            "visible once the target has carried on reporting for a year, so "
            "deals announced recently are under-labelled by construction.",
            "Break labels are candidates, not confirmed breaks. 8-K item 1.02 covers "
            "termination of any material definitive agreement, credit facilities "
            "included, so some of these terminated something other than the merger. "
            "One 2020 episode resolves four days after its definitive proxy, which is "
            "not a deal dying. Confirming each break against the 8-K text is the first "
            "job of phase one, and is cheap because breaks are rare.",
            "Episodes labelled unresolved are ones where metadata cannot separate a "
            "tender offer that lapsed quietly from a buyer-side proxy. They are "
            "reported rather than assigned.",
            "S-4 and 425 filings are excluded because their registrant is the acquirer. "
            "Deals where the target filed neither a proxy nor a 14D-9 are therefore "
            "outside this universe.",
        ],
    }
    if index_stats:
        summary["index"] = index_stats
    return summary


def write(summary: dict, rendered: str, results_dir: Path = RESULTS) -> list[Path]:
    """Both the machine-readable summary and the table the README quotes.

    The rendered table is committed so that a figure in the documents and a
    figure in the data cannot drift apart without the diff showing it.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    as_json = results_dir / "universe.json"
    as_text = results_dir / "universe.txt"
    as_json.write_text(json.dumps(summary, indent=2) + "\n")
    as_text.write_text(rendered + "\n")
    return [as_json, as_text]


def render(summary: dict) -> str:
    labels = summary["labels"]
    lines = [
        f"deal episodes            {summary['episodes']:>8,}",
        f"resolved                 {summary['resolved']:>8,}",
        f"break candidates         {summary['break_events']:>8,}"
        "   (unconfirmed: item 1.02 covers any material agreement)",
        f"blank-cheque targets     {summary['shell_episodes']:>8,}"
        "   (segregated: a SPAC merger is a different instrument)",
        "",
        "label                        count     share",
    ]
    total = summary["episodes"] or 1
    for label in LABELS:
        lines.append(f"  {label:<24} {labels[label]:>7,}    {labels[label] / total:>6.1%}")
    rate = summary["completion_rate"]
    lines += [
        "",
        f"completion rate          {rate:>8.1%} of {summary['completion_rate_denominator']:,} resolved"
        if rate is not None else "completion rate               n/a",
        "",
        "sign to close, days (completed deals)",
        f"  n {summary['sign_to_close_days']['n']:,}"
        f"   p10 {summary['sign_to_close_days']['p10']}"
        f"   median {summary['sign_to_close_days']['median']}"
        f"   p90 {summary['sign_to_close_days']['p90']}",
        "",
        "operating companies only (blank cheques removed)",
    ]
    operating = summary["operating_company_deals"]
    lines.append(
        f"  {operating['episodes']:,} episodes, {operating['resolved']:,} resolved, "
        f"{operating['break_events']:,} breaks, completion rate "
        + (f"{operating['completion_rate']:.1%}" if operating["completion_rate"] is not None else "n/a")
    )
    window = summary["reliable_break_window"]
    lines += [
        "",
        "break detection depends on an 8-K item code, which the SEC only numbered from 2004",
        f"  first year above {window['coverage_floor']:.0%} item coverage: "
        f"{window['first_usable_year'] or 'none'}",
        "  earlier years carry completions but cannot carry breaks",
    ]
    censored = window["right_censored_years"]
    if censored:
        lines.append(
            "  right censored, under-labelled by construction: "
            + ", ".join(str(year) for year in censored)
        )
    return "\n".join(lines)
