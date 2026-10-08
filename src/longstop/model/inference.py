"""Do the terms carry information, as opposed to help a prediction?

Those are different questions and they want different tools. A classifier is
scored on how well it ranks; it will happily use a feature whose coefficient
cannot be distinguished from zero, and gives no way to say so. The question this
project asks in its first line is whether deal protection terms carry information
about the break, and answering it needs an interval on each coefficient.

So this is a plain logit with standard errors, fitted on complete cases, and
reported with confidence intervals and the count of events behind them. An odds
ratio whose interval crosses one is reported as crossing one rather than as a
finding.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import PerfectSeparationWarning

# Ten events per parameter is the usual rule of thumb for a logit; below that the
# coefficients are unstable and the intervals know it.
EVENTS_PER_PARAMETER = 10


def fit(frame: pd.DataFrame, covariates: list[str], label: str = "broke") -> dict:
    design = frame[covariates + [label]].dropna()
    events = int(design[label].sum())
    if events < 5 or design[label].nunique() < 2:
        return {"fitted": False, "reason": "too few events", "events": events, "n": int(len(design))}

    # Drop anything constant in the complete-case subset, which separates.
    usable = [c for c in covariates if design[c].nunique() > 1]
    dropped = sorted(set(covariates) - set(usable))
    if not usable:
        return {"fitted": False, "reason": "no covariate varies in the complete cases",
                "events": events, "n": int(len(design))}

    exog = sm.add_constant(design[usable].astype(float), has_constant="add")
    try:
        # Separation surfaces as a warning and then as "Singular matrix", which
        # tells a reader nothing. Promote it so the refusal says what happened.
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            result = sm.Logit(design[label].astype(int), exog).fit(disp=0, maxiter=200)
    except PerfectSeparationWarning:
        return {"fitted": False,
                "reason": "perfect separation: a covariate predicts the outcome exactly "
                          "in these complete cases, so the coefficient is not identified",
                "events": events, "n": int(len(design)),
                "events_per_parameter": round(events / (len(usable) + 1), 1)}
    except Exception as exc:
        return {"fitted": False,
                "reason": f"{exc}"[:140] + " (usually separation at this few events)",
                "events": events, "n": int(len(design))}

    if not result.mle_retvals.get("converged", True):
        return {"fitted": False, "reason": "maximum likelihood did not converge, which on "
                                           "this few events means separation",
                "events": events, "n": int(len(design))}

    odds = np.exp(result.params)
    # Separation shows up as an astronomically wide interval rather than an
    # error. An odds ratio of ten to the twelfth is not a finding about mergers.
    spans = np.exp(result.conf_int())
    if (spans[1] / spans[0].clip(lower=1e-12) > 1e6).any():
        return {"fitted": False,
                "reason": "at least one coefficient is separated; the interval spans "
                          "many orders of magnitude and the estimate is meaningless",
                "events": events, "n": int(len(design)),
                "events_per_parameter": round(events / (len(usable) + 1), 1)}
    ci = np.exp(result.conf_int())
    terms = {}
    for name in result.params.index:
        if name == "const":
            continue
        low, high = float(ci.loc[name, 0]), float(ci.loc[name, 1])
        terms[str(name)] = {
            "odds_ratio": round(float(odds[name]), 4),
            "ci_low": round(low, 4),
            "ci_high": round(high, 4),
            "p": round(float(result.pvalues[name]), 4),
            # The only reading that matters at this sample size.
            "crosses_one": bool(low <= 1.0 <= high),
        }

    informative = [name for name, v in terms.items() if not v["crosses_one"]]
    return {
        "fitted": True,
        "n": int(len(design)),
        "events": events,
        "parameters": len(usable) + 1,
        "events_per_parameter": round(events / (len(usable) + 1), 1),
        "underpowered": events / (len(usable) + 1) < EVENTS_PER_PARAMETER,
        "dropped_as_constant": dropped,
        "pseudo_r_squared": round(float(result.prsquared), 4),
        "llr_p": round(float(result.llr_pvalue), 6),
        "odds_ratios": terms,
        "carry_information": informative,
        "verdict": (
            f"{len(informative)} of {len(terms)} terms have an odds ratio whose 95% "
            "interval excludes one."
        ),
    }
