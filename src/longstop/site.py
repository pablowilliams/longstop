"""Building the static payload the dashboard reads.

The console talks to the API when one is running. Deployed, there is no API and
no server at all, so the same views read committed JSON instead. That keeps the
published site free to host and impossible to break at three in the morning, and
it means the numbers on the page are the numbers in the repository rather than
whatever a running process happened to hold.

The universe file is six megabytes because it carries evidence strings and
accession numbers for every episode. The browser needs none of that, so this
writes a slimmed view and leaves the full record where it belongs, in the
repository, for anyone checking the work.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"
RESULTS = REPO_ROOT / "results"
SITE_DATA = REPO_ROOT / "console" / "public" / "data"

DEAL_FIELDS = (
    "cik", "company", "sic_description", "tickers", "announced", "label",
    "resolved_on", "days_to_resolution", "announcement_forms", "evidence", "shell",
)
BREAK_FIELDS = (
    "cik", "company", "announced", "resolved_on", "days_to_resolution",
    "status", "reasons", "break_fee_usd", "document", "excerpt",
)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _slim(rows: list[dict], keep: tuple[str, ...]) -> list[dict]:
    return [{k: row.get(k) for k in keep if k in row} for row in rows]


def golden_proforma() -> dict:
    """Reference outputs for the TypeScript port to be checked against.

    The merger model exists once, in Python, and is reimplemented in TypeScript so
    the deployed page can move a slider without a server. Two implementations of
    the same arithmetic is exactly the situation where they quietly drift apart,
    so the Python one writes its answers here and the TypeScript test fails if it
    disagrees.
    """
    from longstop.finance.proforma import Company, Deal, build, synergies_for_breakeven
    from longstop.finance.sensitivity import tornado, variance_decomposition

    acquirer = Company(
        net_income=800e6, diluted_shares=400e6, share_price=50.0,
        cash=1_000e6, debt=2_000e6, ebitda=1_800e6, book_equity=5_000e6,
    )
    target = Company(
        net_income=120e6, diluted_shares=100e6, share_price=20.0,
        cash=150e6, debt=600e6, ebitda=300e6, book_equity=900e6,
    )
    cases = {
        "base": Deal(offer_per_share=26.0, cash_consideration_pct=0.6,
                     cash_from_balance_sheet_pct=0.4, new_debt_rate=0.06,
                     tax_rate=0.25, pretax_synergies=100e6, transaction_fees=50e6,
                     intangible_step_up=400e6),
        "all_cash": Deal(offer_per_share=26.0, cash_consideration_pct=1.0),
        "all_stock": Deal(offer_per_share=26.0, cash_consideration_pct=0.0,
                          refinance_target_debt=False),
        "ruinous": Deal(offer_per_share=80.0, cash_consideration_pct=1.0,
                        new_debt_rate=0.09, transaction_fees=60e6,
                        intangible_step_up=500e6),
    }

    out: dict = {
        "acquirer": asdict(acquirer),
        "target": asdict(target),
        "cases": {},
    }
    for name, deal in cases.items():
        result = build(acquirer, target, deal)
        payload = asdict(result)
        payload["sources_and_uses"] = asdict(result.sources_and_uses)
        payload["sources_and_uses"]["total_uses"] = result.sources_and_uses.total_uses
        payload["sources_and_uses"]["total_sources"] = result.sources_and_uses.total_sources
        # Properties are not fields, so asdict leaves them out. The TypeScript
        # port computes them, so they have to be in the golden file to be checked.
        payload["sources_and_uses"]["balances"] = result.sources_and_uses.balances
        out["cases"][name] = {
            "deal": asdict(deal),
            "pro_forma": payload,
            "synergies_for_breakeven": synergies_for_breakeven(acquirer, target, deal),
            "tornado": [
                {"assumption": s.assumption, "low_value": s.low_value,
                 "high_value": s.high_value, "accretion_at_low": s.accretion_at_low,
                 "accretion_at_high": s.accretion_at_high}
                for s in tornado(acquirer, target, deal)
            ],
        }
    # One decomposition, on the base case, with a fixed seed. The sampler differs
    # between languages so the shares are compared loosely; the point is that the
    # ordering and magnitudes agree, not that two different RNGs match bit for bit.
    decomposition = variance_decomposition(acquirer, target, cases["base"], samples=4000, seed=0)
    out["decomposition"] = {
        "share_of_variance": decomposition.share_of_variance,
        "dominant": decomposition.dominant,
        "base_accretion_pct": decomposition.base_accretion_pct,
    }
    return out


def build_site_data(out_dir: Path = SITE_DATA) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_path = RESULTS / "universe.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    deals = _slim(_read(DATA / "universe.jsonl"), DEAL_FIELDS)
    breaks = _slim(_read(DATA / "breaks.jsonl"), BREAK_FIELDS)
    terms = _read(DATA / "terms.jsonl")

    written: dict[str, int] = {}
    for name, payload in (
        ("summary.json", summary),
        ("deals.json", deals),
        ("breaks.json", breaks),
        ("terms.json", terms),
        ("golden-proforma.json", golden_proforma()),
    ):
        path = out_dir / name
        # Separators without spaces, because this ships over the wire.
        path.write_text(json.dumps(payload, separators=(",", ":")))
        written[name] = path.stat().st_size

    return {
        "written_to": str(out_dir),
        "files": {name: f"{size / 1024:.0f}KB" for name, size in written.items()},
        "deals": len(deals),
        "breaks": len(breaks),
        "terms": len(terms),
    }
