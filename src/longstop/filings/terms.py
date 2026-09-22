"""Deal terms, read out of the filing that announced them.

The useful trick in this file is the reconciliation. A merger proxy states the
per-share consideration, the unaffected share price and the premium, in three
different places and usually hundreds of pages apart. Those three numbers are
arithmetically related, so an extraction can be checked against the document
itself:

    premium = consideration / unaffected price - 1

When the extracted figures satisfy that identity, all three were read correctly
and no annotator was needed to say so. When they do not, something was misread
and the extraction says so instead of reporting a number.

This is what makes extraction accuracy measurable on real filings without a
labelled set, and it is the same reason the premium is read from the document
rather than fetched from a price series: free price data is missing precisely
the securities that delisted, which is to say precisely the deals that closed.

Everything here is deterministic. No model is called, and the language-model
adapter that handles what these patterns abstain on sits behind the same
interface so the benchmark still reproduces without a key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "": 1.0}

CASH_PER_SHARE = re.compile(
    r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s*(?:per share|in cash|for each share|"
    r"in cash for each|per share in cash)",
    re.IGNORECASE,
)
EXCHANGE_RATIO = re.compile(
    r"(\d\.\d{2,6})\s+(?:validly issued,? fully paid.{0,40}?)?shares? of\b[^.]{0,80}?common stock",
    re.IGNORECASE,
)
PREMIUM = re.compile(
    r"premium of (?:approximately |about |roughly )?(\d{1,3}(?:\.\d{1,2})?)\s?(?:%|percent)",
    re.IGNORECASE,
)
UNAFFECTED = re.compile(
    r"closing (?:sale |market )?price(?: per share)? of (?:[^.$]{0,80}?)\$\s?(\d{1,4}(?:\.\d{1,4})?)",
    re.IGNORECASE,
)
TERMINATION_FEE = re.compile(
    r"(?<!parent )(?<!reverse )(?:company )?termination fee(?: of| equal to| in the amount of)?\s*"
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(thousand|million|billion)?",
    re.IGNORECASE,
)
PARENT_FEE = re.compile(
    r"(?:parent termination fee|reverse termination fee)(?: of| equal to)?\s*"
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(thousand|million|billion)?",
    re.IGNORECASE,
)
EQUITY_VALUE = re.compile(
    r"(?:equity value|aggregate consideration|transaction value(?:d)?|enterprise value)"
    r"[^.$]{0,80}\$\s?([\d,]+(?:\.\d+)?)\s*(thousand|million|billion)?",
    re.IGNORECASE,
)
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
OUTSIDE_DATE = re.compile(
    rf'(?:"?(?:end date|outside date|termination date)"?)[^.]{{0,120}}?'
    rf"((?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}})",
    re.IGNORECASE,
)
NO_FINANCING_CONDITION = re.compile(
    r"(?:not (?:subject to|conditioned (?:up)?on) (?:any |a )?financing|"
    r"no financing condition)",
    re.IGNORECASE,
)
FINANCING_CONDITION = re.compile(r"financing condition", re.IGNORECASE)
GO_SHOP = re.compile(r"go.?shop", re.IGNORECASE)
HSR = re.compile(r"hart.scott.rodino|hsr act", re.IGNORECASE)
CFIUS = re.compile(r"\bcfius\b|committee on foreign investment", re.IGNORECASE)
TENDER_OFFER = re.compile(r"\b(?:tender offer|exchange offer)\b", re.IGNORECASE)

RECONCILED = "reconciled"
MISMATCH = "mismatch"
INSUFFICIENT = "insufficient"


def flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _money(match: re.Match[str] | None) -> float | None:
    """Amount times its scale word, for patterns that have one and those that do not.

    A per-share price is written "$58.50" with no scale word; a fee is written
    "$95 million" with one. Both go through here, so the scale group is optional.
    """
    if match is None:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    scale = (match.group(2) or "") if match.re.groups >= 2 else ""
    return amount * SCALE.get(scale.lower(), 1.0)


@dataclass(frozen=True)
class Terms:
    cash_per_share: float | None = None
    exchange_ratio: float | None = None
    stated_premium_pct: float | None = None
    unaffected_price: float | None = None
    termination_fee_usd: float | None = None
    parent_termination_fee_usd: float | None = None
    equity_value_usd: float | None = None
    outside_date: str | None = None
    financing_condition: bool | None = None
    go_shop: bool = False
    hsr: bool = False
    cfius: bool = False
    tender_offer: bool = False

    @property
    def consideration(self) -> str:
        if self.cash_per_share and self.exchange_ratio:
            return "cash_and_stock"
        if self.cash_per_share:
            return "cash"
        if self.exchange_ratio:
            return "stock"
        return "unknown"

    @property
    def break_fee_pct(self) -> float | None:
        """The fee as a share of equity value, the way a deal team quotes it."""
        if self.termination_fee_usd and self.equity_value_usd:
            return round(100 * self.termination_fee_usd / self.equity_value_usd, 3)
        return None


@dataclass(frozen=True)
class Reconciliation:
    status: str
    implied_premium_pct: float | None = None
    stated_premium_pct: float | None = None
    absolute_error_pp: float | None = None
    note: str = ""


def extract_terms(text: str) -> Terms:
    flat = flatten(text)
    financing: bool | None = None
    if NO_FINANCING_CONDITION.search(flat):
        financing = False
    elif FINANCING_CONDITION.search(flat):
        financing = True
    ratio = EXCHANGE_RATIO.search(flat)
    return Terms(
        cash_per_share=_money(CASH_PER_SHARE.search(flat)),
        exchange_ratio=float(ratio.group(1)) if ratio else None,
        stated_premium_pct=float(PREMIUM.search(flat).group(1)) if PREMIUM.search(flat) else None,
        unaffected_price=_money(UNAFFECTED.search(flat)),
        termination_fee_usd=_money(TERMINATION_FEE.search(flat)),
        parent_termination_fee_usd=_money(PARENT_FEE.search(flat)),
        equity_value_usd=_money(EQUITY_VALUE.search(flat)),
        outside_date=OUTSIDE_DATE.search(flat).group(1) if OUTSIDE_DATE.search(flat) else None,
        financing_condition=financing,
        go_shop=bool(GO_SHOP.search(flat)),
        hsr=bool(HSR.search(flat)),
        cfius=bool(CFIUS.search(flat)),
        tender_offer=bool(TENDER_OFFER.search(flat)),
    )


def reconcile(terms: Terms, tolerance_pp: float = 1.5) -> Reconciliation:
    """Check the extraction against the document's own arithmetic.

    A cash deal states the price, the unaffected price and the premium. The three
    must agree, and when they do the extraction verified itself.
    """
    if terms.cash_per_share is None or terms.unaffected_price in (None, 0):
        return Reconciliation(INSUFFICIENT, note="no cash price or no unaffected price found")
    if terms.stated_premium_pct is None:
        return Reconciliation(INSUFFICIENT, note="no stated premium found")

    implied = 100 * (terms.cash_per_share / terms.unaffected_price - 1)
    error = abs(implied - terms.stated_premium_pct)
    return Reconciliation(
        status=RECONCILED if error <= tolerance_pp else MISMATCH,
        implied_premium_pct=round(implied, 2),
        stated_premium_pct=terms.stated_premium_pct,
        absolute_error_pp=round(error, 2),
        note="" if error <= tolerance_pp else "extracted figures do not satisfy the document's own arithmetic",
    )
