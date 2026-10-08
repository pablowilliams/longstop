"""Does a deal break, and is the probability worth believing?

Accuracy is not reported here and never will be. Breaks are about two per cent of
resolved deals, so a model answering "closes" every time scores ninety-eight and
has learned nothing. That is the trap this project was built around.

What is reported is calibration, because the number has to be usable as a
probability rather than a ranking, and expected value under the asymmetry that
actually governs the trade: a completion pays a few points of spread, a break
costs twenty or thirty. A model that is right more often and wrong expensively is
worse than useless.

Everything carries a bootstrap interval. With this many events a Brier score
quoted to three decimals without one is false precision.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from longstop.model.features import time_split

# A completion earns the spread; a break costs the premium. The ratio, not the
# level, is what makes accuracy the wrong metric.
GAIN_ON_COMPLETION = 3.0
LOSS_ON_BREAK = 20.0

NUMERIC = ["year", "break_fee_pct", "stated_premium_pct", "equity_value_usd"]
BINARY = ["tender_offer_filing", "going_private", "shell", "has_terms",
          "financing_condition", "hsr", "cfius"]
CATEGORICAL = ["sector", "consideration"]


def _pipeline(kind: str, seed: int) -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    binary = SimpleImputer(strategy="most_frequent")
    categorical = OneHotEncoder(handle_unknown="ignore", min_frequency=25, sparse_output=False)

    pre = ColumnTransformer([
        ("num", numeric, NUMERIC),
        ("bin", binary, BINARY),
        ("cat", categorical, CATEGORICAL),
    ])

    if kind == "logistic":
        # Regularised, because 77 training events against a few dozen dummies
        # separates otherwise.
        base = LogisticRegression(max_iter=2000, C=0.3, class_weight="balanced", random_state=seed)
    else:
        base = HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05, random_state=seed,
        )

    # Platt rather than isotonic: isotonic needs far more events than this and
    # will happily fit a step function to noise.
    return Pipeline([
        ("pre", pre),
        ("cal", CalibratedClassifierCV(base, method="sigmoid", cv=5)),
    ])


def expected_value(probability: np.ndarray, broke: np.ndarray, threshold: float) -> dict:
    """Take every deal the model says is safe enough, and see what it paid."""
    taken = probability <= threshold
    if not taken.any():
        return {"threshold": threshold, "deals_taken": 0, "ev_per_deal": None, "total": 0.0}
    outcomes = np.where(broke[taken] == 1, -LOSS_ON_BREAK, GAIN_ON_COMPLETION)
    return {
        "threshold": round(threshold, 3),
        "deals_taken": int(taken.sum()),
        "share_taken": round(float(taken.mean()), 4),
        "breaks_taken": int(broke[taken].sum()),
        "ev_per_deal": round(float(outcomes.mean()), 4),
        "total": round(float(outcomes.sum()), 2),
    }


def _bootstrap(probability: np.ndarray, broke: np.ndarray, statistic, draws: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(draws):
        index = rng.integers(0, len(broke), len(broke))
        if broke[index].sum() == 0:
            continue
        values.append(statistic(probability[index], broke[index]))
    if not values:
        return {"low": None, "high": None}
    return {
        "low": round(float(np.percentile(values, 2.5)), 4),
        "high": round(float(np.percentile(values, 97.5)), 4),
    }


def fit_and_score(
    frame: pd.DataFrame,
    kind: str = "logistic",
    cutoff_year: int = 2019,
    draws: int = 400,
    seed: int = 0,
) -> dict:
    train, test = time_split(frame, cutoff_year)
    columns = NUMERIC + BINARY + CATEGORICAL

    model = _pipeline(kind, seed)
    model.fit(train[columns], train.broke)
    probability = model.predict_proba(test[columns])[:, 1]
    broke = test.broke.to_numpy()

    base_rate = float(train.broke.mean())
    brier = float(brier_score_loss(broke, probability))
    # Against predicting the training base rate for every deal. Below zero means
    # the model is worse than a constant.
    reference = float(brier_score_loss(broke, np.full_like(probability, base_rate)))
    skill = 1 - brier / reference if reference else 0.0

    bins = min(5, max(2, int(broke.sum() // 8)))
    observed, predicted = calibration_curve(broke, probability, n_bins=bins, strategy="quantile")
    ece = float(np.mean(np.abs(observed - predicted)))

    return {
        "model": kind,
        "trained_on": {"years": f"<{cutoff_year}", "deals": int(len(train)), "breaks": int(train.broke.sum())},
        "tested_on": {"years": f">={cutoff_year}", "deals": int(len(test)), "breaks": int(broke.sum())},
        "base_rate_train": round(base_rate, 4),
        "base_rate_test": round(float(broke.mean()), 4),
        "brier": round(brier, 5),
        "brier_ci": _bootstrap(probability, broke, lambda p, y: brier_score_loss(y, p), draws, seed),
        "brier_of_predicting_the_base_rate": round(reference, 5),
        "brier_skill_score": round(float(skill), 4),
        "ece": round(ece, 4),
        "calibration_curve": [
            {"predicted": round(float(p), 4), "observed": round(float(o), 4)}
            for p, o in zip(predicted, observed)
        ],
        "auc": round(float(roc_auc_score(broke, probability)), 4) if broke.sum() else None,
        "auc_ci": _bootstrap(probability, broke, lambda p, y: roc_auc_score(y, p), draws, seed),
        "expected_value": {
            "gain_on_completion": GAIN_ON_COMPLETION,
            "loss_on_break": LOSS_ON_BREAK,
            "take_everything": expected_value(probability, broke, 1.0),
            "by_threshold": [
                expected_value(probability, broke, t)
                for t in (0.005, 0.01, 0.02, 0.03, 0.05)
            ],
        },
        "accuracy_is_not_reported": (
            f"The test set is {100 * float(broke.mean()):.1f}% breaks, so answering "
            "'closes' every time scores in the nineties and knows nothing."
        ),
    }
