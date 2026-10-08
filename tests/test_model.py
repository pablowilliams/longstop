"""Tests for the modelling layer.

These assert properties, not numbers. The numbers move when the terms extraction
advances; the properties are what make them worth reading.
"""
from __future__ import annotations

import warnings
from datetime import date

import numpy as np
import pandas as pd
import pytest

from longstop.model import completion, conformal, inference, survival
from longstop.model.features import LEAKY, build_frame, time_split

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    built = build_frame()
    if built.empty or built.broke.sum() < 20:
        pytest.skip("universe not built; run make universe and make breaks")
    return built


def test_no_outcome_field_reaches_the_design_matrix(frame):
    # days_to_resolution and resolved_on are outcomes. A model given them would
    # score beautifully and have learned that deals which closed, closed.
    assert not (LEAKY & set(frame.columns))


def test_the_split_trains_on_the_past_only(frame):
    train, test = time_split(frame, 2019)
    assert train.year.max() < 2019 <= test.year.min()
    assert len(train) and len(test)


def test_unconfirmed_breaks_are_excluded_rather_than_counted_either_way(frame):
    # Half the raw item 1.02 label terminated something other than a merger. The
    # real outcome of those deals is unknown, so they are neither class.
    import json
    from pathlib import Path

    universe = Path(__file__).resolve().parents[1] / "data" / "universe.jsonl"
    raw = [json.loads(line) for line in universe.read_text().splitlines() if line]
    in_window = [
        r for r in raw
        if "2007-01-01" <= r["announced"] < "2025-01-01" and r["label"] == "terminated"
    ]
    assert frame.broke.sum() < len(in_window)


def test_pending_deals_are_censored_not_dropped():
    # A deal that has run 250 days without breaking is evidence even though
    # nobody knows how it ends. That is the whole reason for survival analysis.
    labelled = build_frame()
    censored = build_frame(include_pending=True, window_end="2026-12-31")
    if len(censored) == len(labelled):
        pytest.skip("no pending deals in this universe")
    unresolved = censored[(censored.observed_break == 0) & (censored.observed_close == 0)]
    assert len(unresolved) > 0


def test_competing_risks_and_naive_km_disagree(frame):
    # Kaplan-Meier on breaks alone pretends a deal that closed could still break,
    # so it overstates the risk. If these two ever agree, something is wrong.
    result = survival.curves(frame)
    incidence = result["cumulative_incidence_of_break"]["730"]
    naive = result["naive_km_break_risk"]["730"]
    assert naive > incidence
    assert 0 < incidence < 0.2


def test_the_hazard_model_reports_events_per_covariate(frame):
    fitted = survival.hazard(frame, survival.COVARIATES)
    if not fitted["fitted"]:
        pytest.skip(fitted["reason"])
    assert fitted["events_per_covariate"] > 0
    for name, value in fitted["hazard_ratios"].items():
        assert value["ci_low"] <= value["hazard_ratio"] <= value["ci_high"], name


def test_accuracy_is_never_reported(frame):
    scored = completion.fit_and_score(frame, "logistic", draws=50)
    assert "accuracy" not in scored
    assert "accuracy_is_not_reported" in scored


def test_every_headline_number_carries_an_interval(frame):
    scored = completion.fit_and_score(frame, "logistic", draws=50)
    for key in ("brier_ci", "auc_ci"):
        assert scored[key]["low"] is not None
        assert scored[key]["low"] <= scored[key]["high"]


def test_expected_value_respects_the_asymmetry():
    # A completion pays three, a break costs twenty. Taking a book of deals that
    # all broke must lose, whatever the model said.
    probability = np.array([0.01, 0.02, 0.03])
    broke = np.array([1, 1, 1])
    result = completion.expected_value(probability, broke, 1.0)
    assert result["ev_per_deal"] == -completion.LOSS_ON_BREAK

    result = completion.expected_value(probability, np.array([0, 0, 0]), 1.0)
    assert result["ev_per_deal"] == completion.GAIN_ON_COMPLETION


def test_a_tighter_threshold_takes_fewer_deals(frame):
    scored = completion.fit_and_score(frame, "logistic", draws=50)
    taken = [row["deals_taken"] for row in scored["expected_value"]["by_threshold"]]
    assert taken == sorted(taken)


def test_inference_refuses_a_separated_fit():
    # A perfectly predictive dummy separates, and a logit then reports an odds
    # ratio of ten to the twelfth with an infinite interval. That is not a
    # finding about mergers.
    rows = pd.DataFrame({
        "broke": [0] * 60 + [1] * 10,
        "giveaway": [0] * 60 + [1] * 10,
        "noise": list(np.random.default_rng(0).normal(size=70)),
    })
    result = inference.fit(rows, ["giveaway", "noise"])
    assert result["fitted"] is False
    assert "separation" in result["reason"]


def test_inference_reports_whether_each_interval_crosses_one(frame):
    result = inference.fit(frame, ["tender_offer_filing", "going_private", "shell"])
    if not result["fitted"]:
        pytest.skip(result["reason"])
    for name, value in result["odds_ratios"].items():
        assert value["crosses_one"] == (value["ci_low"] <= 1.0 <= value["ci_high"]), name


def test_marginal_conformal_coverage_can_hide_the_rare_class(frame):
    # The guarantee is marginal. With breaks at two per cent a method can satisfy
    # it while covering no breaks at all, which is the finding worth keeping.
    result = conformal.coverage(frame, confidence_level=0.9, split="time")
    marginal = next(m for m in result["methods"] if m["method"] == "marginal, non-empty corrected")
    conditional = next(m for m in result["methods"] if m["method"] == "class-conditional")
    assert conditional["coverage_on_breaks"] > marginal["coverage_on_breaks"]


def test_coverage_holds_when_the_data_is_actually_exchangeable(frame):
    # Conformal promises coverage under exchangeability. A temporal split breaks
    # that assumption, so the random split is the control that separates "the
    # method is broken" from "the world moved".
    result = conformal.coverage(frame, confidence_level=0.9, split="random")
    conditional = next(m for m in result["methods"] if m["method"] == "class-conditional")
    assert conditional["coverage_on_completions"] >= 0.85
    assert conditional["coverage_on_breaks"] >= 0.80


def test_current_listing_status_is_treated_as_leakage(frame):
    # The submissions API reports a company's CURRENT tickers. An acquired target
    # delisted and has none; one whose deal broke still trades. 39.7% of breaks
    # carried a ticker against 5.1% of completions, and a logit given it reported
    # an odds ratio of 11.4. It is the outcome wearing a disguise.
    assert "listed" not in frame.columns
    assert "tickers" not in frame.columns


def test_implausible_break_fees_are_dropped_not_modelled(frame):
    # A termination fee is one to four per cent of equity value. Half the
    # computed values exceeded 100% and the largest was 3e14%, which is the
    # extractor pairing a fee with the wrong number, not an unusual deal.
    fees = frame.break_fee_pct.dropna()
    if fees.empty:
        pytest.skip("no break fees extracted")
    assert fees.max() <= 20.0
    assert fees.min() > 0
    assert 1.0 < fees.median() < 8.0
