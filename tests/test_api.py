from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from longstop.api.app import app

client = TestClient(app)

ACQUIRER = {"net_income": 8e8, "diluted_shares": 4e8, "share_price": 50.0,
            "cash": 1e9, "debt": 2e9, "ebitda": 1.8e9, "book_equity": 5e9}
TARGET = {"net_income": 1.2e8, "diluted_shares": 1e8, "share_price": 20.0,
          "cash": 1.5e8, "debt": 6e8, "ebitda": 3e8, "book_equity": 9e8}


def body(**deal):
    return {
        "acquirer": ACQUIRER,
        "target": TARGET,
        "deal": {"offer_per_share": 26.0, **deal},
        "samples": 400,
    }


def test_health_reports_what_is_loaded():
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert "terminated" in payload["labels"]


def test_the_pro_forma_endpoint_is_a_pure_function_of_its_body():
    first = client.post("/api/proforma", json=body(pretax_synergies=1e8)).json()
    second = client.post("/api/proforma", json=body(pretax_synergies=1e8)).json()
    assert first == second


def test_sources_balance_over_the_wire_too():
    payload = client.post("/api/proforma", json=body(cash_consideration_pct=0.6,
                                                    cash_from_balance_sheet_pct=0.4)).json()
    assert payload["pro_forma"]["sources_and_uses"]["balances"] is True


def test_the_breakeven_travels_with_the_pro_forma():
    payload = client.post("/api/proforma", json=body(offer_per_share=80.0)).json()
    assert payload["pro_forma"]["accretion_pct"] < 0
    assert payload["pro_forma"]["synergies_for_breakeven"] > 0


def test_the_tornado_comes_back_sorted():
    swings = client.post("/api/proforma", json=body()).json()["tornado"]
    assert [s["swing_pp"] for s in swings] == sorted((s["swing_pp"] for s in swings), reverse=True)


def test_the_decomposition_carries_its_own_fit():
    decomposition = client.post("/api/proforma", json=body()).json()["decomposition"]
    assert 0.0 <= decomposition["linear_r_squared"] <= 1.0
    assert sum(decomposition["share_of_variance"].values()) == pytest.approx(1.0, abs=1e-3)
    assert decomposition["dominant"]


@pytest.mark.parametrize(
    "deal",
    [
        {"cash_consideration_pct": 1.5},
        {"tax_rate": 1.0},
        {"offer_per_share": -1.0},
        {"intangible_life_years": 0.0},
    ],
)
def test_impossible_assumptions_are_rejected_at_the_boundary(deal):
    assert client.post("/api/proforma", json=body(**deal)).status_code == 422


def test_a_zero_share_count_cannot_reach_the_model():
    payload = {"acquirer": {**ACQUIRER, "diluted_shares": 0.0}, "target": TARGET,
               "deal": {"offer_per_share": 26.0}}
    assert client.post("/api/proforma", json=payload).status_code == 422


def test_deals_paginate_and_filter():
    page = client.get("/api/deals", params={"limit": 5}).json()
    assert page["limit"] == 5
    assert len(page["rows"]) <= 5
    if page["total"]:
        label = page["rows"][0]["label"]
        filtered = client.get("/api/deals", params={"label": label, "limit": 500}).json()
        assert all(row["label"] == label for row in filtered["rows"])


def test_an_unknown_filter_value_returns_an_empty_page_not_an_error():
    page = client.get("/api/deals", params={"label": "not_a_label"}).json()
    assert page["total"] == 0
    assert page["rows"] == []
