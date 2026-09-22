"""Tests for the merger model.

The identities are the point. Sources must equal uses, an all-stock deal at a
fair multiple must be roughly neutral, and the solved break-even must actually
produce zero accretion when fed back in. A spreadsheet that fails any of those is
wrong regardless of how reasonable its output looks.
"""
from __future__ import annotations

import pytest

from longstop.finance.proforma import (
    Company,
    Deal,
    build,
    premium,
    synergies_for_breakeven,
)

ACQUIRER = Company(
    net_income=800e6,
    diluted_shares=400e6,
    share_price=50.0,
    cash=1_000e6,
    debt=2_000e6,
    ebitda=1_800e6,
    book_equity=5_000e6,
)
TARGET = Company(
    net_income=120e6,
    diluted_shares=100e6,
    share_price=20.0,
    cash=150e6,
    debt=600e6,
    ebitda=300e6,
    book_equity=900e6,
)


def test_sources_equal_uses_in_an_all_cash_deal():
    result = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0, cash_consideration_pct=1.0,
                                          cash_from_balance_sheet_pct=0.5, transaction_fees=40e6))
    assert result.sources_and_uses.balances
    assert result.sources_and_uses.total_uses == pytest.approx(
        26.0 * 100e6 + 600e6 + 40e6
    )


def test_sources_equal_uses_in_a_mixed_deal():
    result = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0, cash_consideration_pct=0.6,
                                          cash_from_balance_sheet_pct=0.3))
    assert result.sources_and_uses.balances


def test_an_all_stock_deal_issues_shares_and_borrows_nothing():
    result = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0, cash_consideration_pct=0.0,
                                          refinance_target_debt=False))
    assert result.shares_issued == pytest.approx(26.0 * 100e6 / 50.0)
    assert result.sources_and_uses.new_debt == 0.0


def test_the_premium_is_the_premium():
    assert premium(26.0, 20.0) == pytest.approx(30.0)
    with pytest.raises(ValueError):
        premium(26.0, 0.0)


def test_a_cash_deal_turns_on_earnings_yield_against_the_after_tax_cost_of_debt():
    # Not on the P/E comparison, which is the intuition that gets this wrong.
    # The deal needs 3,050m of new debt once the target's 600m of debt is
    # refinanced and its 150m of cash is applied, against 120m of acquired
    # earnings. Neutral is where 120m equals 3,050m * rate * (1 - tax), which is
    # a rate of 5.25%. Either side of that line the sign flips.
    def accretion(rate: float) -> float:
        return build(
            ACQUIRER, TARGET,
            Deal(offer_per_share=26.0, cash_consideration_pct=1.0,
                 new_debt_rate=rate, tax_rate=0.25),
        ).accretion_pct

    assert accretion(0.04) > 0
    assert accretion(0.06) < 0
    crossover = 120e6 / (3_050e6 * 0.75)
    assert accretion(crossover - 0.0005) > 0
    assert accretion(crossover + 0.0005) < 0


def test_a_ruinous_premium_is_dilutive():
    result = build(ACQUIRER, TARGET, Deal(offer_per_share=80.0, cash_consideration_pct=1.0,
                                          new_debt_rate=0.09))
    assert result.accretion_pct < 0


def test_the_solved_breakeven_actually_breaks_even():
    # The closed form has to survive being fed back into the model.
    from dataclasses import replace

    deal = Deal(offer_per_share=80.0, cash_consideration_pct=1.0, new_debt_rate=0.09,
                transaction_fees=60e6, intangible_step_up=500e6)
    required = synergies_for_breakeven(ACQUIRER, TARGET, deal)
    checked = build(ACQUIRER, TARGET, replace(deal, pretax_synergies=required))
    assert checked.accretion_pct == pytest.approx(0.0, abs=1e-6)


def test_a_deal_already_accretive_needs_negative_synergies_to_be_neutral():
    deal = Deal(offer_per_share=22.0, cash_consideration_pct=1.0, new_debt_rate=0.04)
    assert synergies_for_breakeven(ACQUIRER, TARGET, deal) < 0


def test_goodwill_is_price_less_book_equity_less_the_step_up():
    result = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0, intangible_step_up=400e6))
    assert result.goodwill == pytest.approx(26.0 * 100e6 - 900e6 - 400e6)


def test_synergies_lift_pro_forma_leverage_denominator_not_just_earnings():
    without = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0))
    with_synergies = build(ACQUIRER, TARGET, Deal(offer_per_share=26.0, pretax_synergies=200e6))
    assert with_synergies.pro_forma_net_debt_to_ebitda < without.pro_forma_net_debt_to_ebitda


def test_impossible_assumptions_are_refused_not_silently_clamped():
    with pytest.raises(ValueError):
        Deal(offer_per_share=26.0, cash_consideration_pct=1.4)
    with pytest.raises(ValueError):
        Deal(offer_per_share=26.0, tax_rate=1.0)
    with pytest.raises(ValueError):
        Company(net_income=1.0, diluted_shares=0.0, share_price=1.0).eps


def test_more_cash_on_hand_than_the_deal_needs_does_not_become_negative_debt():
    rich = Company(net_income=800e6, diluted_shares=400e6, share_price=50.0,
                   cash=20_000e6, debt=0.0, ebitda=1_800e6, book_equity=5_000e6)
    result = build(rich, TARGET, Deal(offer_per_share=26.0, cash_from_balance_sheet_pct=1.0))
    assert result.sources_and_uses.new_debt == 0.0
    assert result.sources_and_uses.balances
