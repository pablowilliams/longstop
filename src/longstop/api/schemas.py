"""Request and response shapes for the API.

Typed on both sides deliberately. The console mirrors these models, so a field
renamed here breaks the build there rather than rendering as undefined.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyIn(BaseModel):
    net_income: float
    diluted_shares: float = Field(gt=0)
    share_price: float = Field(gt=0)
    cash: float = 0.0
    debt: float = 0.0
    ebitda: float = 0.0
    book_equity: float = 0.0


class DealIn(BaseModel):
    offer_per_share: float = Field(gt=0)
    cash_consideration_pct: float = Field(default=1.0, ge=0.0, le=1.0)
    cash_from_balance_sheet_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    new_debt_rate: float = Field(default=0.06, ge=0.0, le=1.0)
    forgone_cash_yield: float = Field(default=0.02, ge=0.0, le=1.0)
    tax_rate: float = Field(default=0.25, ge=0.0, lt=1.0)
    pretax_synergies: float = 0.0
    synergy_phasing: float = Field(default=1.0, ge=0.0, le=1.0)
    transaction_fees: float = 0.0
    refinance_target_debt: bool = True
    intangible_step_up: float = 0.0
    intangible_life_years: float = Field(default=10.0, gt=0)


class ProFormaRequest(BaseModel):
    acquirer: CompanyIn
    target: CompanyIn
    deal: DealIn
    samples: int = Field(default=2000, ge=200, le=20000)
    seed: int = 0


class SwingOut(BaseModel):
    assumption: str
    low_value: float
    high_value: float
    accretion_at_low: float
    accretion_at_high: float
    swing_pp: float


class SourcesAndUsesOut(BaseModel):
    equity_purchase_price: float
    target_debt_refinanced: float
    transaction_fees: float
    cash_from_balance_sheet: float
    new_debt: float
    new_equity: float
    target_cash_acquired: float
    total_uses: float
    total_sources: float
    balances: bool


class ProFormaOut(BaseModel):
    sources_and_uses: SourcesAndUsesOut
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
    synergies_for_breakeven: float
    announced_synergies_required_note: str


class DecompositionOut(BaseModel):
    base_accretion_pct: float
    mean_accretion_pct: float
    std_accretion_pp: float
    p5: float
    p95: float
    share_of_variance: dict[str, float]
    linear_r_squared: float
    samples: int
    sign_flips: float
    dominant: list[str]


class ProFormaResponse(BaseModel):
    pro_forma: ProFormaOut
    tornado: list[SwingOut]
    decomposition: DecompositionOut


class DealRow(BaseModel):
    cik: int
    company: str
    sic_description: str = ""
    tickers: list[str] = []
    announced: str
    label: str
    resolved_on: str | None = None
    days_to_resolution: int | None = None
    announcement_forms: list[str] = []
    evidence: list[str] = []
    shell: bool = False


class DealPage(BaseModel):
    total: int
    offset: int
    limit: int
    rows: list[DealRow]


class BreakRow(BaseModel):
    cik: int
    company: str
    announced: str
    resolved_on: str | None = None
    days_to_resolution: int | None = None
    status: str
    reasons: list[str] = []
    break_fee_usd: float | None = None
    document: str | None = None
    excerpt: str = ""
