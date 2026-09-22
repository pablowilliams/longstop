"""The merger consequences model: sources and uses, then accretion or dilution.

This is the arithmetic a deal team does in a spreadsheet, written down so it can
be tested. Nothing here is clever. What it is, is explicit: every line has a
name, every assumption is an input rather than a hardcoded number, and the
synergy break-even is solved in closed form rather than by nudging a cell until
the answer goes to zero.

The break-even is the number worth having. Accretion is linear in synergies, so
the level of synergy required to make a deal EPS neutral falls straight out, and
comparing it against the synergy management announced is a far more informative
question than whether the deal is accretive at somebody's assumption.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Company:
    """Standalone financials. Shares are in units, everything else in currency."""

    net_income: float
    diluted_shares: float
    share_price: float
    cash: float = 0.0
    debt: float = 0.0
    ebitda: float = 0.0
    book_equity: float = 0.0

    @property
    def eps(self) -> float:
        if self.diluted_shares == 0:
            raise ValueError("diluted_shares cannot be zero")
        return self.net_income / self.diluted_shares

    @property
    def market_cap(self) -> float:
        return self.share_price * self.diluted_shares


@dataclass(frozen=True)
class Deal:
    """The offer and how it is paid for.

    cash_consideration_pct splits the offer between cash and acquirer stock.
    The cash portion is then funded from the acquirer's balance sheet and new
    debt in the proportion given by cash_from_balance_sheet_pct.
    """

    offer_per_share: float
    cash_consideration_pct: float = 1.0
    cash_from_balance_sheet_pct: float = 0.0
    new_debt_rate: float = 0.06
    forgone_cash_yield: float = 0.02
    tax_rate: float = 0.25
    pretax_synergies: float = 0.0
    synergy_phasing: float = 1.0
    transaction_fees: float = 0.0
    refinance_target_debt: bool = True
    intangible_step_up: float = 0.0
    intangible_life_years: float = 10.0

    def __post_init__(self) -> None:
        for name in ("cash_consideration_pct", "cash_from_balance_sheet_pct", "synergy_phasing"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {value}")
        if not 0.0 <= self.tax_rate < 1.0:
            raise ValueError(f"tax_rate must be in [0, 1), got {self.tax_rate}")


@dataclass(frozen=True)
class SourcesAndUses:
    equity_purchase_price: float
    target_debt_refinanced: float
    transaction_fees: float
    cash_from_balance_sheet: float
    new_debt: float
    new_equity: float
    target_cash_acquired: float

    @property
    def total_uses(self) -> float:
        return self.equity_purchase_price + self.target_debt_refinanced + self.transaction_fees

    @property
    def total_sources(self) -> float:
        return (
            self.cash_from_balance_sheet
            + self.new_debt
            + self.new_equity
            + self.target_cash_acquired
        )

    @property
    def balances(self) -> bool:
        return abs(self.total_sources - self.total_uses) < 1.0


@dataclass(frozen=True)
class ProForma:
    sources_and_uses: SourcesAndUses
    shares_issued: float
    pro_forma_shares: float
    pro_forma_net_income: float
    pro_forma_eps: float
    acquirer_standalone_eps: float
    accretion_pct: float
    premium_pct: float
    goodwill: float
    pro_forma_net_debt: float
    pro_forma_net_debt_to_ebitda: float | None
    after_tax_synergies: float
    incremental_interest: float
    forgone_interest: float
    incremental_amortisation: float


def premium(offer_per_share: float, unaffected_price: float) -> float:
    if unaffected_price <= 0:
        raise ValueError("unaffected_price must be positive")
    return 100.0 * (offer_per_share / unaffected_price - 1.0)


def build(acquirer: Company, target: Company, deal: Deal) -> ProForma:
    equity_price = deal.offer_per_share * target.diluted_shares
    cash_portion = equity_price * deal.cash_consideration_pct
    stock_portion = equity_price - cash_portion

    debt_refinanced = target.debt if deal.refinance_target_debt else 0.0
    cash_needed = cash_portion + debt_refinanced + deal.transaction_fees

    from_balance_sheet = min(
        cash_needed * deal.cash_from_balance_sheet_pct,
        max(acquirer.cash, 0.0),
    )
    new_debt = cash_needed - from_balance_sheet - target.cash
    if new_debt < 0:
        # More cash available than the deal needs. The excess is not a negative
        # borrowing, it simply is not raised.
        from_balance_sheet += new_debt
        new_debt = 0.0

    shares_issued = stock_portion / acquirer.share_price if acquirer.share_price > 0 else 0.0

    sources_and_uses = SourcesAndUses(
        equity_purchase_price=equity_price,
        target_debt_refinanced=debt_refinanced,
        transaction_fees=deal.transaction_fees,
        cash_from_balance_sheet=from_balance_sheet,
        new_debt=new_debt,
        new_equity=stock_portion,
        target_cash_acquired=target.cash,
    )

    after_tax = 1.0 - deal.tax_rate
    after_tax_synergies = deal.pretax_synergies * deal.synergy_phasing * after_tax
    incremental_interest = new_debt * deal.new_debt_rate * after_tax
    forgone_interest = from_balance_sheet * deal.forgone_cash_yield * after_tax
    incremental_amortisation = (
        (deal.intangible_step_up / deal.intangible_life_years) * after_tax
        if deal.intangible_life_years > 0
        else 0.0
    )

    pro_forma_net_income = (
        acquirer.net_income
        + target.net_income
        + after_tax_synergies
        - incremental_interest
        - forgone_interest
        - incremental_amortisation
    )
    pro_forma_shares = acquirer.diluted_shares + shares_issued
    pro_forma_eps = pro_forma_net_income / pro_forma_shares
    standalone_eps = acquirer.eps

    goodwill = (
        equity_price
        - target.book_equity
        - deal.intangible_step_up
    )
    pro_forma_ebitda = acquirer.ebitda + target.ebitda + deal.pretax_synergies * deal.synergy_phasing
    pro_forma_net_debt = (
        acquirer.debt + new_debt + (0.0 if deal.refinance_target_debt else target.debt)
        - max(acquirer.cash - from_balance_sheet, 0.0)
    )

    return ProForma(
        sources_and_uses=sources_and_uses,
        shares_issued=shares_issued,
        pro_forma_shares=pro_forma_shares,
        pro_forma_net_income=pro_forma_net_income,
        pro_forma_eps=pro_forma_eps,
        acquirer_standalone_eps=standalone_eps,
        accretion_pct=100.0 * (pro_forma_eps / standalone_eps - 1.0),
        premium_pct=premium(deal.offer_per_share, target.share_price),
        goodwill=goodwill,
        pro_forma_net_debt=pro_forma_net_debt,
        pro_forma_net_debt_to_ebitda=(
            pro_forma_net_debt / pro_forma_ebitda if pro_forma_ebitda > 0 else None
        ),
        after_tax_synergies=after_tax_synergies,
        incremental_interest=incremental_interest,
        forgone_interest=forgone_interest,
        incremental_amortisation=incremental_amortisation,
    )


def synergies_for_breakeven(acquirer: Company, target: Company, deal: Deal) -> float:
    """Pre-tax synergies at which the deal is exactly EPS neutral.

    Solved rather than searched. Pro forma net income is linear in synergies and
    the share count does not depend on them, so:

        required after-tax synergies = standalone EPS * pro forma shares
                                       - pro forma net income excluding synergies

    Returns the pre-tax figure, which is how synergies are announced. It can come
    back negative, which means the deal is already accretive without any.
    """
    without = build(acquirer, target, replace(deal, pretax_synergies=0.0))
    required_after_tax = (
        acquirer.eps * without.pro_forma_shares - without.pro_forma_net_income
    )
    denominator = (1.0 - deal.tax_rate) * deal.synergy_phasing
    if denominator == 0:
        raise ValueError("synergies cannot move EPS when phasing is zero")
    return required_after_tax / denominator
