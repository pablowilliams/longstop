"""How long deals take, and what shifts the hazard of one dying.

Every other number in this project throws away the deals that have not finished.
A deal announced in 2024 and still pending contributes nothing to a completion
rate, and a break is only visible once the target has carried on reporting for a
year, so the most recent years are under-labelled by construction. That is
censoring, and survival analysis is the method built for it: a deal that has gone
250 days without breaking is evidence, even though its outcome is unknown.

Completion and termination compete. A deal that closes can no longer break, so
each outcome censors the other. Two things follow:

  A Kaplan-Meier curve for one of them, treating the other as ordinary
  censoring, estimates a cause-specific quantity and overstates the risk, because
  it implicitly asks what would happen if deals could not close. It is reported
  because the cause-specific hazard is what the Cox model below estimates, and
  the two belong together.

  The honest statement of "what share of deals have broken by day N" is the
  cumulative incidence function, which Aalen-Johansen gives and Kaplan-Meier does
  not. Both are reported, and they disagree, which is the point.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import AalenJohansenFitter, CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import proportional_hazard_test

# Deals that have run longer than this are almost always administrative
# stragglers; the curve is reported to here so the tail does not mislead.
HORIZON_DAYS = 900

COVARIATES = ["tender_offer_filing", "going_private", "shell", "listed"]
TERM_COVARIATES = ["break_fee_pct", "financing_condition", "hsr", "stated_premium_pct"]


def _competing_event(frame: pd.DataFrame) -> pd.Series:
    """0 censored, 1 broke, 2 closed."""
    return frame.observed_break * 1 + frame.observed_close * 2


def curves(frame: pd.DataFrame) -> dict:
    duration = frame.duration_days.clip(upper=HORIZON_DAYS)

    closing = KaplanMeierFitter().fit(duration, frame.observed_close, label="closing")
    breaking = KaplanMeierFitter().fit(duration, frame.observed_break, label="breaking")

    # Aalen-Johansen jitters tied event times, and deal durations tie constantly
    # because they are whole days. Unseeded, the same data gives a different
    # answer every run, which is not a number anyone should quote.
    aj = AalenJohansenFitter(calculate_variance=True, seed=0)
    aj.fit(duration, _competing_event(frame), event_of_interest=1)
    incidence = aj.cumulative_density_
    column = incidence.columns[0]

    def at(day: int) -> float:
        upto = incidence.loc[incidence.index <= day, column]
        return round(float(upto.iloc[-1]), 4) if len(upto) else 0.0

    median_close = closing.median_survival_time_
    return {
        "n": int(len(frame)),
        "breaks": int(frame.observed_break.sum()),
        "closes": int(frame.observed_close.sum()),
        "censored": int(((frame.observed_break + frame.observed_close) == 0).sum()),
        "median_days_to_close": None if np.isinf(median_close) else float(median_close),
        "closed_by_day": {
            str(day): round(float(1 - closing.predict(day)), 4)
            for day in (90, 180, 365, 730)
        },
        # The quantity people mean when they ask how often deals break.
        "cumulative_incidence_of_break": {str(day): at(day) for day in (90, 180, 365, 730)},
        # Kaplan-Meier on breaks alone, which ignores that closing removes the
        # deal from risk and therefore overstates it. Shown next to the above so
        # the gap is visible rather than argued about.
        "naive_km_break_risk": {
            str(day): round(float(1 - breaking.predict(day)), 4)
            for day in (90, 180, 365, 730)
        },
    }


def _design(frame: pd.DataFrame, covariates: list[str]) -> pd.DataFrame:
    design = frame[covariates + ["duration_days", "observed_break"]].copy()
    design["duration_days"] = design.duration_days.clip(upper=HORIZON_DAYS)
    return design.dropna()


def hazard(frame: pd.DataFrame, covariates: list[str] | None = None, penalizer: float = 0.1) -> dict:
    """Cox proportional hazards on the cause-specific hazard of a break.

    Completions are censored, which is the standard cause-specific treatment: the
    coefficients describe the rate of breaking among deals still live, not the
    share of deals that end up broken.

    Penalised, because with this few events an unpenalised fit on sparse dummies
    separates and reports hazard ratios in the thousands.
    """
    covariates = covariates or COVARIATES
    design = _design(frame, covariates)
    events = int(design.observed_break.sum())
    if events < 5 or design.observed_break.nunique() < 2:
        return {"fitted": False, "reason": "too few events to fit", "events": events,
                "n": int(len(design))}

    model = CoxPHFitter(penalizer=penalizer)
    model.fit(design, duration_col="duration_days", event_col="observed_break")
    summary = model.summary

    # Proportional hazards is an assumption, not a given, and a model that
    # violates it is describing an average over time that never held.
    try:
        # .p_value is an array aligned with .summary's index, not a mapping.
        ph = proportional_hazard_test(model, design, time_transform="rank")
        ph_p = {str(name): round(float(row["p"])) if False else round(float(row["p"]), 4)
                for name, row in ph.summary.iterrows()}
    except Exception as exc:  # the test is fragile on sparse designs
        ph_p = {"error": str(exc)[:120]}

    return {
        "fitted": True,
        "n": int(len(design)),
        "events": events,
        "events_per_covariate": round(events / max(len(covariates), 1), 1),
        "concordance": round(float(model.concordance_index_), 4),
        "penalizer": penalizer,
        "hazard_ratios": {
            str(name): {
                "hazard_ratio": round(float(summary.loc[name, "exp(coef)"]), 4),
                "ci_low": round(float(summary.loc[name, "exp(coef) lower 95%"]), 4),
                "ci_high": round(float(summary.loc[name, "exp(coef) upper 95%"]), 4),
                "p": round(float(summary.loc[name, "p"]), 4),
            }
            for name in summary.index
        },
        "proportional_hazards_p": ph_p,
    }
