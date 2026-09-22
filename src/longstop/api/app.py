"""The backend the console talks to.

Read-only over the built dataset, except for the pro forma endpoint, which is a
pure function of its request body: same assumptions in, same numbers out, no
state. That is what lets the console's assumption panel move a slider and get an
answer without a job queue.

Nothing here computes a probability, because nothing in the repository is
entitled to yet. When it does, it will arrive with an interval attached.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from longstop.api.schemas import (
    BreakRow,
    DealPage,
    DealRow,
    DecompositionOut,
    ProFormaRequest,
    ProFormaResponse,
    SourcesAndUsesOut,
    SwingOut,
)
from longstop.finance import proforma as pf
from longstop.finance.sensitivity import tornado, variance_decomposition
from longstop.universe.outcomes import LABELS

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data"
RESULTS = REPO_ROOT / "results"
CONSOLE_DIST = REPO_ROOT / "console" / "dist"

app = FastAPI(
    title="Longstop",
    version="0.1.0",
    description=(
        "Deal outcomes derived from EDGAR filings, and the merger arithmetic that "
        "goes with them. Analysis of public filings. Not advice."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@lru_cache(maxsize=1)
def universe() -> list[dict]:
    return _read_jsonl(DATA / "universe.jsonl")


@lru_cache(maxsize=1)
def breaks() -> list[dict]:
    return _read_jsonl(DATA / "breaks.jsonl")


@lru_cache(maxsize=1)
def summary() -> dict:
    path = RESULTS / "universe.json"
    return json.loads(path.read_text()) if path.exists() else {}


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "episodes": len(universe()),
        "breaks_confirmed": len(breaks()),
        "labels": list(LABELS),
    }


@app.get("/api/universe/summary")
def universe_summary() -> dict:
    data = summary()
    if not data:
        raise HTTPException(503, "universe not built. Run make universe.")
    return data


@app.get("/api/deals", response_model=DealPage)
def deals(
    label: str | None = None,
    year: int | None = None,
    q: str | None = None,
    shell: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> DealPage:
    rows = universe()
    if label:
        rows = [r for r in rows if r["label"] == label]
    if year:
        rows = [r for r in rows if r["announced"][:4] == str(year)]
    if shell is not None:
        rows = [r for r in rows if bool(r.get("shell")) is shell]
    if q:
        needle = q.lower()
        rows = [
            r for r in rows
            if needle in r["company"].lower()
            or needle in " ".join(r.get("tickers") or []).lower()
        ]
    window = rows[offset: offset + limit]
    return DealPage(
        total=len(rows),
        offset=offset,
        limit=limit,
        rows=[DealRow(**{k: v for k, v in r.items() if k in DealRow.model_fields}) for r in window],
    )


@app.get("/api/breaks", response_model=list[BreakRow])
def confirmed_breaks(status: str | None = None) -> list[BreakRow]:
    rows = breaks()
    if status:
        rows = [r for r in rows if r["status"] == status]
    return [BreakRow(**{k: v for k, v in r.items() if k in BreakRow.model_fields}) for r in rows]


@app.post("/api/proforma", response_model=ProFormaResponse)
def build_proforma(request: ProFormaRequest) -> ProFormaResponse:
    acquirer = pf.Company(**request.acquirer.model_dump())
    target = pf.Company(**request.target.model_dump())
    try:
        deal = pf.Deal(**request.deal.model_dump())
        result = pf.build(acquirer, target, deal)
        breakeven = pf.synergies_for_breakeven(acquirer, target, deal)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    sources = result.sources_and_uses
    swings = tornado(acquirer, target, deal)
    decomposition = variance_decomposition(
        acquirer, target, deal, samples=request.samples, seed=request.seed
    )

    payload = asdict(result)
    payload.pop("sources_and_uses")
    return ProFormaResponse(
        pro_forma={
            **payload,
            "sources_and_uses": SourcesAndUsesOut(
                **asdict(sources),
                total_uses=sources.total_uses,
                total_sources=sources.total_sources,
                balances=sources.balances,
            ),
            "synergies_for_breakeven": breakeven,
            "announced_synergies_required_note": (
                "Synergies required for EPS neutrality, solved rather than searched. "
                "A negative figure means the deal is accretive without any."
            ),
        },
        tornado=[SwingOut(**asdict(s), swing_pp=s.swing_pp) for s in swings],
        decomposition=DecompositionOut(**asdict(decomposition), dominant=decomposition.dominant),
    )


# The built console, when there is one. Mounted last so it cannot shadow the API.
if CONSOLE_DIST.exists():
    app.mount("/assets", StaticFiles(directory=CONSOLE_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(CONSOLE_DIST / "index.html")
