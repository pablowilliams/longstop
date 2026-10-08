"""Prediction sets with a coverage guarantee that does not need a big sample.

Everything else here leans on having enough events for an asymptotic argument.
There are about a hundred and twenty confirmed breaks, which is not enough, and
pretending otherwise is how small-sample work goes wrong. Conformal prediction
asks only for exchangeable data and returns a set of labels that contains the
true one at least as often as you asked, whatever the model.

The catch, and the reason this file reports two methods rather than one:

  The standard guarantee is **marginal**. It promises coverage averaged over all
  deals. With breaks at two or three per cent, a method can hit ninety per cent
  overall while covering almost no breaks at all, simply by being right about
  completions. Measured here, the marginal method does exactly that.

  **Class-conditional** calibration fixes it by computing a separate threshold
  from the calibration deals of each class, so the promise holds within breaks
  rather than on average across a population that is almost entirely
  completions. It is the version worth having when the rare class is the point.

The marginal version comes from MAPIE, which for a binary target supports only
the LAC score. LAC can return an empty set, and an empty set cannot contain
anything, so empty sets are reported rather than hidden. Where a set is empty the
non-empty correction adds the most likely label: that can only ever add labels,
so the guarantee survives and becomes conservative.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from mapie.classification import SplitConformalClassifier
from sklearn.model_selection import train_test_split

from longstop.model.completion import BINARY, CATEGORICAL, NUMERIC, _pipeline
from longstop.model.features import time_split


def _conformal_quantile(scores: np.ndarray, confidence_level: float) -> float:
    """The finite-sample corrected quantile. The (n+1) is what makes it valid."""
    n = len(scores)
    if n == 0:
        return np.inf
    rank = int(np.ceil((n + 1) * confidence_level))
    if rank > n:
        return np.inf  # too few calibration points to promise this level
    return float(np.sort(scores)[rank - 1])


def _class_conditional(
    calib_probability: np.ndarray, calib_truth: np.ndarray,
    test_probability: np.ndarray, confidence_level: float,
) -> np.ndarray:
    """A threshold per class, so the promise holds inside the rare class too."""
    sets = np.zeros((len(test_probability), 2), dtype=bool)
    for label in (0, 1):
        held = calib_truth == label
        scores = 1 - calib_probability[held, label]
        quantile = _conformal_quantile(scores, confidence_level)
        sets[:, label] = (1 - test_probability[:, label]) <= quantile
    return sets


def _summarise(sets: np.ndarray, truth: np.ndarray, label: str) -> dict:
    contains = sets[np.arange(len(truth)), truth]
    size = sets.sum(axis=1)
    broke = truth == 1
    return {
        "method": label,
        "coverage": round(float(contains.mean()), 4),
        "coverage_on_breaks": round(float(contains[broke].mean()), 4) if broke.any() else None,
        "coverage_on_completions": round(float(contains[~broke].mean()), 4),
        "set_sizes": {
            "empty": round(float((size == 0).mean()), 4),
            "singleton": round(float((size == 1).mean()), 4),
            "both_labels": round(float((size == 2).mean()), 4),
        },
        "mean_set_size": round(float(size.mean()), 4),
    }


def coverage(
    frame: pd.DataFrame,
    confidence_level: float = 0.9,
    cutoff_year: int = 2019,
    seed: int = 0,
    split: str = "time",
) -> dict:
    """split="time" trains on the past and tests on the future, which is the only
    honest way to score a forecast. It also violates the one assumption conformal
    prediction makes, exchangeability, because deals from 2007 and 2023 are not
    draws from the same distribution.

    split="random" is not a defensible way to evaluate a forecast and is offered
    only as a diagnostic: it restores exchangeability, so comparing the two
    separates "the method is broken" from "the world moved".
    """
    columns = NUMERIC + BINARY + CATEGORICAL
    if split == "random":
        train, test = train_test_split(
            frame, test_size=0.33, random_state=seed, stratify=frame.broke,
        )
    else:
        train, test = time_split(frame, cutoff_year)

    # The calibration deals must not have trained the model, or the guarantee is
    # void. Split the training years again rather than borrowing from the test.
    fit_part, calib_part = train_test_split(
        train, test_size=0.3, random_state=seed, stratify=train.broke,
    )

    model = _pipeline("logistic", seed)
    model.fit(fit_part[columns], fit_part.broke)
    truth = test.broke.to_numpy()

    marginal = SplitConformalClassifier(
        estimator=model, confidence_level=confidence_level, prefit=True,
        conformity_score="lac", random_state=seed,
    )
    marginal.conformalize(calib_part[columns], calib_part.broke)
    _, raw = marginal.predict_set(test[columns])
    raw = np.asarray(raw)
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    raw = raw.astype(bool)

    test_probability = model.predict_proba(test[columns])
    corrected = raw.copy()
    empty = ~corrected.any(axis=1)
    corrected[empty, test_probability[empty].argmax(axis=1)] = True

    conditional = _class_conditional(
        model.predict_proba(calib_part[columns]), calib_part.broke.to_numpy(),
        test_probability, confidence_level,
    )

    results = [
        _summarise(raw, truth, "marginal (MAPIE, LAC)"),
        _summarise(corrected, truth, "marginal, non-empty corrected"),
        _summarise(conditional, truth, "class-conditional"),
    ]
    return {
        "confidence_level": confidence_level,
        "split": split,
        "exchangeable": split == "random",
        "calibrated_on": int(len(calib_part)),
        "calibration_breaks": int(calib_part.broke.sum()),
        "tested_on": int(len(truth)),
        "breaks_in_test": int(truth.sum()),
        "methods": results,
        "finding": (
            "Marginal coverage can be met while covering almost no breaks, "
            "because the population is almost entirely completions. The "
            "class-conditional thresholds are what make the promise mean "
            "something for the rare outcome."
        ),
    }
