"""Point-in-time financials from the XBRL company facts API.

Two things make this harder than it looks, and both are handled here rather than
left to the caller.

Tag drift. There is no single tag for revenue. A filer may use Revenues,
RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet or
several others, and which one depends on the filer, the year and the accounting
standard in force. Each concept therefore has an ordered list of candidate tags
and the first one with data wins.

Look-ahead. Every fact carries both the period it describes and the date it was
filed, and those differ by months. A model that uses a figure for a period
ending before the announcement, but disclosed in a filing that appeared after
it, is using information nobody had. So every lookup takes a known_by date and
filters on the filed date, not the period end.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from longstop.edgar.client import EdgarClient

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

ANNUAL_FORMS = ("10-K", "20-F", "40-F")

CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "diluted_shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
    ),
    "basic_shares": ("WeightedAverageNumberOfSharesOutstandingBasic",),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "operating_income": ("OperatingIncomeLoss",),
    "depreciation_amortisation": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "interest_expense": ("InterestExpense", "InterestIncomeExpenseNet", "InterestExpenseDebt"),
    "tax_expense": ("IncomeTaxExpenseBenefit",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "total_debt_noncurrent": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "total_debt_current": ("DebtCurrent", "LongTermDebtCurrent"),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
}


@dataclass(frozen=True)
class Fact:
    value: float
    period_end: str
    filed: str
    form: str
    tag: str
    unit: str

    @property
    def fiscal_year(self) -> int:
        return int(self.period_end[:4])


def company_facts(client: EdgarClient, cik: int) -> dict | None:
    body = client.get(FACTS_URL.format(cik=cik), allow_404=True)
    return json.loads(body) if body is not None else None


def _facts_for_tag(payload: dict, tag: str) -> list[Fact]:
    for namespace in ("us-gaap", "ifrs-full", "dei"):
        block = payload.get("facts", {}).get(namespace, {}).get(tag)
        if not block:
            continue
        out: list[Fact] = []
        for unit, rows in block.get("units", {}).items():
            for row in rows:
                if row.get("val") is None or not row.get("end") or not row.get("filed"):
                    continue
                out.append(
                    Fact(
                        value=float(row["val"]),
                        period_end=row["end"],
                        filed=row["filed"],
                        form=row.get("form", ""),
                        tag=tag,
                        unit=unit,
                    )
                )
        if out:
            return out
    return []


def latest_annual(
    payload: dict,
    concept: str,
    known_by: str | date,
    annual_only: bool = True,
) -> Fact | None:
    """The most recent annual figure for a concept that was public by known_by.

    Filtering on the filed date rather than the period end is the whole point.
    A 10-K for the year ending December is filed in February or March, so a deal
    announced in January cannot have used it.
    """
    cutoff = known_by if isinstance(known_by, str) else known_by.isoformat()
    for tag in CONCEPTS.get(concept, (concept,)):
        facts = [
            f for f in _facts_for_tag(payload, tag)
            if f.filed <= cutoff and (not annual_only or f.form in ANNUAL_FORMS)
        ]
        if facts:
            # Latest period that was actually public, breaking ties on the later
            # filing, which is the restated figure.
            return max(facts, key=lambda f: (f.period_end, f.filed))
    return None


def snapshot(payload: dict, known_by: str | date, concepts: tuple[str, ...] | None = None) -> dict:
    """Every concept available as at a date, with the tag each came from recorded."""
    wanted = concepts or tuple(CONCEPTS)
    out: dict[str, dict | None] = {}
    for concept in wanted:
        fact = latest_annual(payload, concept, known_by)
        out[concept] = (
            {
                "value": fact.value,
                "period_end": fact.period_end,
                "filed": fact.filed,
                "form": fact.form,
                "tag": fact.tag,
                "unit": fact.unit,
            }
            if fact
            else None
        )
    return out
