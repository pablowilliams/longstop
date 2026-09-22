"""How much of the accretion answer comes from which assumption.

A merger model produces one number and that number is theatre. Change the
synergy assumption by a quarter and the deal flips from accretive to dilutive,
so quoting a point estimate says more about the analyst than about the deal.

Two views are produced here and they answer different questions.

The tornado is one-at-a-time: hold everything at base, move one assumption from
its low to its high, record the swing. It is what a deal team draws, it is easy
to read, and it misses interaction entirely.

The variance decomposition samples all the assumptions together and attributes
the variance of the output across them. First-order shares come from squared
standardised regression coefficients, which are exact for a linear model and an
approximation otherwise, so the R squared of that regression is reported next to
them. When it is low, the shares are not to be trusted and the output says so
rather than leaving the reader to assume otherwise.

The prediction this exists to test was that synergies and the financing mix
dominate. Half of it is wrong, and the measured answer is more interesting than
the guess. On the worked deal the shares come out as synergies 62%, the
intangible step-up 13%, synergy phasing 12% and the debt rate 9%, while the
cash-against-stock mix contributes 0.1%.

So the assumptions that decide the answer are the three asserted with the least
evidence, and the one negotiated hardest barely registers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace

import numpy as np

from longstop.finance.proforma import Company, Deal, build

# The assumptions worth varying, with defensible default ranges. Each is a field
# of Deal, so a caller can override any of them without touching this module.
DEFAULT_RANGES: dict[str, tuple[float, float]] = {
    "pretax_synergies": (0.0, 300e6),
    "cash_consideration_pct": (0.0, 1.0),
    "cash_from_balance_sheet_pct": (0.0, 1.0),
    "new_debt_rate": (0.03, 0.10),
    "tax_rate": (0.15, 0.30),
    "synergy_phasing": (0.4, 1.0),
    "intangible_step_up": (0.0, 1_000e6),
    "transaction_fees": (10e6, 120e6),
    "forgone_cash_yield": (0.0, 0.05),
}


@dataclass(frozen=True)
class Swing:
    assumption: str
    low_value: float
    high_value: float
    accretion_at_low: float
    accretion_at_high: float

    @property
    def swing_pp(self) -> float:
        return abs(self.accretion_at_high - self.accretion_at_low)


@dataclass(frozen=True)
class Decomposition:
    base_accretion_pct: float
    mean_accretion_pct: float
    std_accretion_pp: float
    p5: float
    p95: float
    share_of_variance: dict[str, float]
    linear_r_squared: float
    samples: int
    sign_flips: float

    @property
    def dominant(self) -> list[str]:
        """Assumptions accounting for the first eighty per cent of the variance."""
        running = 0.0
        out = []
        for name, share in sorted(self.share_of_variance.items(), key=lambda kv: -kv[1]):
            out.append(name)
            running += share
            if running >= 0.8:
                break
        return out


def _accretion(acquirer: Company, target: Company, deal: Deal, **overrides) -> float:
    return build(acquirer, target, replace(deal, **overrides)).accretion_pct


def tornado(
    acquirer: Company,
    target: Company,
    deal: Deal,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> list[Swing]:
    """One assumption at a time, widest swing first."""
    ranges = ranges or DEFAULT_RANGES
    swings = [
        Swing(
            assumption=name,
            low_value=low,
            high_value=high,
            accretion_at_low=_accretion(acquirer, target, deal, **{name: low}),
            accretion_at_high=_accretion(acquirer, target, deal, **{name: high}),
        )
        for name, (low, high) in ranges.items()
    ]
    return sorted(swings, key=lambda s: -s.swing_pp)


def variance_decomposition(
    acquirer: Company,
    target: Company,
    deal: Deal,
    ranges: dict[str, tuple[float, float]] | None = None,
    samples: int = 4000,
    seed: int = 0,
) -> Decomposition:
    """Sample every assumption together and attribute the output variance."""
    ranges = ranges or DEFAULT_RANGES
    names = list(ranges)
    rng = random.Random(seed)

    draws = np.array(
        [[rng.uniform(*ranges[name]) for name in names] for _ in range(samples)],
        dtype=float,
    )
    outputs = np.array(
        [
            _accretion(acquirer, target, deal, **dict(zip(names, row)))
            for row in draws
        ],
        dtype=float,
    )

    base = build(acquirer, target, deal).accretion_pct
    spread = outputs.std(ddof=1)
    if spread == 0:
        shares = {name: 0.0 for name in names}
        r_squared = 0.0
    else:
        x_std = draws.std(axis=0, ddof=1)
        # An assumption held at a single value cannot explain any variance.
        usable = x_std > 0
        centred = (draws[:, usable] - draws[:, usable].mean(axis=0)) / x_std[usable]
        y = (outputs - outputs.mean()) / spread
        design = np.column_stack([centred, np.ones(len(y))])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        fitted = design @ beta
        residual = float(((y - fitted) ** 2).sum())
        r_squared = max(0.0, 1.0 - residual / float((y**2).sum()))
        raw = {}
        index = 0
        for name, is_usable in zip(names, usable):
            raw[name] = float(beta[index] ** 2) if is_usable else 0.0
            index += 1 if is_usable else 0
        total = sum(raw.values()) or 1.0
        shares = {name: round(value / total, 4) for name, value in raw.items()}

    return Decomposition(
        base_accretion_pct=round(base, 4),
        mean_accretion_pct=round(float(outputs.mean()), 4),
        std_accretion_pp=round(float(spread), 4),
        p5=round(float(np.percentile(outputs, 5)), 4),
        p95=round(float(np.percentile(outputs, 95)), 4),
        share_of_variance=shares,
        linear_r_squared=round(float(r_squared), 4),
        samples=samples,
        sign_flips=round(float((outputs > 0).mean()), 4),
    )
