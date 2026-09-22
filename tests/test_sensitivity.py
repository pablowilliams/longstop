"""Tests for the sensitivity views, including the project's own prediction.

The prediction is that synergies and the financing mix dominate the accretion
answer. It is asserted here, so if it stops being true on this deal the suite
says so rather than the README quietly continuing to claim it.
"""
from __future__ import annotations

import pytest

from longstop.finance.proforma import Company, Deal, build
from longstop.finance.sensitivity import (
    DEFAULT_RANGES,
    tornado,
    variance_decomposition,
)

ACQUIRER = Company(net_income=800e6, diluted_shares=400e6, share_price=50.0,
                   cash=1_000e6, debt=2_000e6, ebitda=1_800e6, book_equity=5_000e6)
TARGET = Company(net_income=120e6, diluted_shares=100e6, share_price=20.0,
                 cash=150e6, debt=600e6, ebitda=300e6, book_equity=900e6)
DEAL = Deal(offer_per_share=26.0, cash_consideration_pct=0.6,
            cash_from_balance_sheet_pct=0.4, new_debt_rate=0.06,
            tax_rate=0.25, pretax_synergies=100e6, transaction_fees=50e6)


def test_the_tornado_is_ordered_by_how_much_each_assumption_moves_the_answer():
    swings = tornado(ACQUIRER, TARGET, DEAL)
    assert [s.assumption for s in swings]
    assert all(
        swings[i].swing_pp >= swings[i + 1].swing_pp for i in range(len(swings) - 1)
    )


def test_every_default_assumption_moves_the_answer_on_a_deal_that_uses_it():
    for swing in tornado(ACQUIRER, TARGET, DEAL):
        assert swing.swing_pp > 0, swing.assumption


def test_an_assumption_the_structure_makes_irrelevant_shows_a_zero_swing():
    # An all-new-debt deal draws nothing from the balance sheet, so the yield
    # forgone on that cash cannot matter. A zero row is information about the
    # structure, not a defect, and it is left in the table for that reason.
    from dataclasses import replace

    all_borrowed = replace(DEAL, cash_from_balance_sheet_pct=0.0)
    swings = {s.assumption: s for s in tornado(ACQUIRER, TARGET, all_borrowed)}
    assert swings["forgone_cash_yield"].swing_pp == 0.0
    assert swings["new_debt_rate"].swing_pp > 0.0


def test_the_assumptions_asserted_with_least_evidence_dominate():
    # The claim the repository makes about merger models. The first version of
    # this test asserted that the financing mix mattered too. It does not: the
    # cash against stock split contributes almost nothing, while the synergy
    # figure, its phasing and the intangible step-up account for most of the
    # answer. If this stops being true the documents have to change with it.
    result = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=3000, seed=1)
    shares = result.share_of_variance

    assert result.dominant[0] == "pretax_synergies"
    asserted = (
        shares["pretax_synergies"] + shares["synergy_phasing"] + shares["intangible_step_up"]
    )
    assert asserted > 0.7, shares
    assert shares["cash_consideration_pct"] < 0.05, shares
    assert shares["pretax_synergies"] > shares["new_debt_rate"]


def test_the_shares_are_reported_with_the_fit_that_produced_them():
    # First-order shares are exact for a linear model and an approximation
    # otherwise, so the R squared travels with them.
    result = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=1500, seed=2)
    assert 0.0 <= result.linear_r_squared <= 1.0
    assert result.linear_r_squared > 0.5
    assert sum(result.share_of_variance.values()) == pytest.approx(1.0, abs=1e-3)


def test_the_point_estimate_is_shown_to_be_a_choice_not_a_finding():
    # The base case sits inside a distribution wide enough to change the sign,
    # which is the argument against quoting it on its own.
    result = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=1500, seed=3)
    assert result.p5 < result.base_accretion_pct < result.p95
    assert 0.0 < result.sign_flips < 1.0


def test_it_is_reproducible():
    a = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=500, seed=7)
    b = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=500, seed=7)
    assert a == b


def test_an_assumption_pinned_to_one_value_explains_nothing():
    ranges = dict(DEFAULT_RANGES, tax_rate=(0.25, 0.25))
    result = variance_decomposition(ACQUIRER, TARGET, DEAL, ranges, samples=800, seed=4)
    assert result.share_of_variance["tax_rate"] == 0.0


def test_the_base_case_matches_the_model_run_directly():
    result = variance_decomposition(ACQUIRER, TARGET, DEAL, samples=200, seed=5)
    assert result.base_accretion_pct == pytest.approx(
        build(ACQUIRER, TARGET, DEAL).accretion_pct, abs=1e-4
    )
