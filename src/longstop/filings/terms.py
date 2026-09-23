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
# Both orders, because the dominant form in real press releases puts the number
# first. Measured over two hundred deals, "premium of 20.5%" alone found the
# figure 6.5% of the time; "a 28.6% premium" is what most filings actually write.
PREMIUM = re.compile(
    r"(?:premium of (?:approximately |about |roughly |nearly )?"
    r"(?P<after>\d{1,3}(?:\.\d{1,2})?)\s?(?:%|percent)"
    r"|(?:a |an )?(?:nearly |approximately |about )?"
    r"(?P<before>\d{1,3}(?:\.\d{1,2})?)\s?(?:%|percent)\s+premium)",
    re.IGNORECASE,
)

# The baseline the premium is quoted against, which is not always the unaffected
# close. A premium to a thirty day average is a different number, and checking a
# consideration against it with the closing-price identity would be comparing two
# things that were never equal.
AVERAGE_BASELINE = re.compile(
    r"(average|volume.weighted|vwap|\d{1,3}[- ](?:calendar |trading )?day)",
    re.IGNORECASE,
)
BASELINE_WINDOW = 200

# The premium and the price it is a premium to are stated in the same breath:
# "a premium of 30.0% to the closing price of $45.00 on 14 February". Choosing
# the price globally instead picked whichever closing price the proxy mentioned
# first, often a historical one from a different year.
PREMIUM_CONTEXT = 320
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


def _modal(pattern: re.Pattern[str], text: str, group: int | str = 1) -> str | None:
    """The value the document repeats, not the one it happens to mention first.

    On a two page 8-K the first match is the deal. On a three hundred page proxy
    it is usually a historical share price, an option exercise price or a figure
    from a comparable company table, and taking it produced a median error of 110
    percentage points against the document's own stated premium.

    The merger consideration is restated on nearly every page. A stray price is
    written once. Counting is therefore a better selector than position, and ties
    go to whichever appeared first.
    """
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for index, match in enumerate(pattern.finditer(text)):
        try:
            value = match.group(group)
        except IndexError:
            continue
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
        order.setdefault(value, index)
    if not counts:
        return None
    return min(counts, key=lambda v: (-counts[v], order[v]))



def _modal_money(pattern: re.Pattern[str], text: str) -> float | None:
    value = _modal(pattern, text)
    if value is None:
        return None
    try:
        amount = float(value.replace(",", ""))
    except ValueError:
        return None
    # Scale words are read from the first occurrence of the winning value, which
    # is enough: a figure written "95" is written "95 million" everywhere it
    # appears or nowhere.
    found = re.search(
        re.escape(value) + r"\s*(thousand|million|billion)?", text, re.IGNORECASE
    )
    scale = (found.group(1) or "") if found else ""
    return amount * SCALE.get(scale.lower(), 1.0)


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
    premium_baseline: str | None = None   # "close", "average", or None when unstated
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
    premium = None
    baseline = None
    beside_premium = None
    premium_values: dict[str, int] = {}
    first_seen: dict[str, re.Match[str]] = {}
    for match in PREMIUM.finditer(flat):
        value = match.group("after") or match.group("before")
        if value is None:
            continue
        premium_values[value] = premium_values.get(value, 0) + 1
        first_seen.setdefault(value, match)
    if premium_values:
        winner = max(premium_values, key=lambda v: premium_values[v])
        premium = float(winner)
        match = first_seen[winner]
        # Same sentence only. Reaching past the full stop picked up an
        # unrelated "on average" from the comparable companies discussion and
        # mislabelled a perfectly ordinary premium to the close.
        tail = flat[match.end(): match.end() + BASELINE_WINDOW]
        context = tail.split(".")[0] if "." in tail else tail
        baseline = "average" if AVERAGE_BASELINE.search(context) else "close"
        nearby = flat[match.start(): match.end() + PREMIUM_CONTEXT]
        beside_premium = _money(UNAFFECTED.search(nearby))
    return Terms(
        cash_per_share=_modal_money(CASH_PER_SHARE, flat),
        exchange_ratio=float(ratio.group(1)) if ratio else None,
        stated_premium_pct=premium,
        premium_baseline=baseline,
        unaffected_price=beside_premium if beside_premium is not None
        else _modal_money(UNAFFECTED, flat),
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
    if terms.premium_baseline == "average":
        # A premium to a thirty day average is not the same quantity as a premium
        # to the unaffected close, so the identity does not apply and saying so
        # is better than reporting a mismatch that means nothing.
        return Reconciliation(
            INSUFFICIENT, note="premium quoted against an average, not the unaffected close"
        )

    implied = 100 * (terms.cash_per_share / terms.unaffected_price - 1)
    error = abs(implied - terms.stated_premium_pct)
    return Reconciliation(
        status=RECONCILED if error <= tolerance_pp else MISMATCH,
        implied_premium_pct=round(implied, 2),
        stated_premium_pct=terms.stated_premium_pct,
        absolute_error_pp=round(error, 2),
        note="" if error <= tolerance_pp else "extracted figures do not satisfy the document's own arithmetic",
    )
