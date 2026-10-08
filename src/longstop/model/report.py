"""Running every model and writing what they found.

Nothing here reports a point estimate without the count behind it, and nothing
reports accuracy at all.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

from longstop.model import completion, conformal, inference, survival
from longstop.model.features import build_frame

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "results"

ALWAYS_AVAILABLE = ["tender_offer_filing", "going_private", "shell", "listed"]
DEAL_TERMS = ["break_fee_pct", "financing_condition", "hsr", "stated_premium_pct"]


def run(seed: int = 0) -> dict:
    warnings.filterwarnings("ignore")

    labelled = build_frame()
    censored = build_frame(include_pending=True, window_end="2026-12-31")

    return {
        "frame": {
            "deals": int(len(labelled)),
            "confirmed_breaks": int(labelled.broke.sum()),
            "with_extracted_terms": int(labelled.has_terms.sum()),
            "excluded": (
                "Episodes labelled terminated whose 8-K did not confirm a merger "
                "termination are dropped rather than counted either way, because "
                "their real outcome is unknown."
            ),
        },
        "survival": {
            "curves": survival.curves(censored),
            "hazard_always_available": survival.hazard(censored, survival.COVARIATES),
            "hazard_with_terms": survival.hazard(censored, survival.TERM_COVARIATES),
        },
        "completion": {
            "logistic": completion.fit_and_score(labelled, "logistic", seed=seed),
            "boosted": completion.fit_and_score(labelled, "boosted", seed=seed),
        },
        "inference": {
            "always_available": inference.fit(labelled, ALWAYS_AVAILABLE),
            "deal_terms": inference.fit(labelled, DEAL_TERMS),
        },
        "conformal": {
            "time_split": conformal.coverage(labelled, split="time", seed=seed),
            "random_split_diagnostic": conformal.coverage(labelled, split="random", seed=seed),
        },
    }


def write(payload: dict, results_dir: Path = RESULTS) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "model.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def render(payload: dict) -> str:
    frame = payload["frame"]
    curves = payload["survival"]["curves"]
    logistic = payload["completion"]["logistic"]
    conditional = next(
        m for m in payload["conformal"]["time_split"]["methods"]
        if m["method"] == "class-conditional"
    )
    corrected = next(
        m for m in payload["conformal"]["time_split"]["methods"]
        if m["method"] == "marginal, non-empty corrected"
    )

    lines = [
        f"deals                    {frame['deals']:>8,}",
        f"confirmed breaks         {frame['confirmed_breaks']:>8,}",
        f"with extracted terms     {frame['with_extracted_terms']:>8,}",
        "",
        "survival, competing risks",
        f"  median days to close   {curves['median_days_to_close']}",
        f"  broken by day 730      {curves['cumulative_incidence_of_break']['730']:.2%}"
        "   (cumulative incidence)",
        f"  the same, naively      {curves['naive_km_break_risk']['730']:.2%}"
        "   (Kaplan-Meier, ignores that closing removes a deal from risk)",
        "",
        "completion model, calibration not accuracy",
        f"  tested on              {logistic['tested_on']['deals']:,} deals, "
        f"{logistic['tested_on']['breaks']} breaks",
        f"  Brier                  {logistic['brier']}  "
        f"[{logistic['brier_ci']['low']}, {logistic['brier_ci']['high']}]",
        f"  skill over base rate   {logistic['brier_skill_score']}",
        f"  AUC                    {logistic['auc']}  "
        f"[{logistic['auc_ci']['low']}, {logistic['auc_ci']['high']}]",
        f"  ECE                    {logistic['ece']}",
        "",
        "conformal prediction, 90% asked for",
        f"  marginal               {corrected['coverage']:.1%} overall, "
        f"{(corrected['coverage_on_breaks'] or 0):.1%} on breaks",
        f"  class-conditional      {conditional['coverage_on_completions']:.1%} on completions, "
        f"{(conditional['coverage_on_breaks'] or 0):.1%} on breaks",
        "  marginal coverage can be met while covering no breaks at all",
    ]
    return "\n".join(lines)
