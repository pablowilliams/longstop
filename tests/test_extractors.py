"""Tests for the two extractors behind one interface.

No network. The model extractor is exercised against a stub, because the point
of the port is that the caller cannot tell which implementation it holds.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from longstop.filings.extractors import (
    DeterministicExtractor,
    ModelExtractor,
    excerpt,
    get_extractor,
)
from longstop.filings.terms import RECONCILED, reconcile

BOILERPLATE = "This proxy statement is dated 1 March. " * 400

PROXY = (
    BOILERPLATE
    + "Each share will be converted into $58.50 per share in cash, without interest. "
    + BOILERPLATE
    + "The consideration represents a premium of approximately 30.0% to the closing "
    "price of the Company's common stock of $45.00 on 14 February. "
    + BOILERPLATE
    + "The Company will pay a termination fee of $95 million. "
    + BOILERPLATE
)


class StubResponse:
    def __init__(self, payload: dict):
        self.content = [SimpleNamespace(type="text", text=json.dumps(payload))]


class StubClient:
    """Records what it was asked, returns what it was told to."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return StubResponse(self.payload)


def test_the_locator_sends_the_passages_not_the_filing():
    passages = excerpt(PROXY)
    assert len(passages) < len(PROXY) / 3
    assert "$58.50 per share in cash" in passages
    assert "premium of approximately 30.0%" in passages
    assert "termination fee of $95 million" in passages


def test_the_locator_respects_its_budget():
    assert len(excerpt(PROXY, max_chars=1200)) <= 1200 + len("\n[...]\n") * 3


def test_a_document_with_no_terms_produces_no_excerpt():
    assert excerpt("An annual report about nothing in particular.").strip() == ""


def test_both_extractors_satisfy_the_same_interface():
    for name in ("deterministic", "model"):
        extractor = get_extractor(name)
        assert hasattr(extractor, "extract")
        assert extractor.name == name
    with pytest.raises(ValueError):
        get_extractor("something else")


def test_the_deterministic_extractor_needs_nothing():
    terms = DeterministicExtractor().extract(PROXY)
    assert terms.cash_per_share == 58.50
    assert reconcile(terms).status == RECONCILED


def test_the_model_extractor_is_measured_by_the_same_check():
    client = StubClient({
        "cash_per_share": 58.50,
        "exchange_ratio": None,
        "stated_premium_pct": 30.0,
        "premium_baseline": "close",
        "unaffected_price": 45.00,
        "termination_fee_usd": 95_000_000,
        "parent_termination_fee_usd": None,
        "equity_value_usd": None,
        "outside_date": None,
    })
    terms = ModelExtractor(client=client).extract(PROXY)
    assert terms.cash_per_share == 58.50
    assert terms.termination_fee_usd == 95_000_000
    assert reconcile(terms).status == RECONCILED


def test_the_model_sees_the_excerpt_and_not_the_whole_filing():
    client = StubClient({name: None for name in (
        "cash_per_share", "exchange_ratio", "stated_premium_pct", "premium_baseline",
        "unaffected_price", "termination_fee_usd", "parent_termination_fee_usd",
        "equity_value_usd", "outside_date",
    )})
    ModelExtractor(client=client).extract(PROXY)
    sent = client.calls[0]["messages"][0]["content"]
    assert len(sent) < len(PROXY) / 3
    assert sent == excerpt(PROXY)


def test_the_request_asks_for_a_validated_schema():
    client = StubClient({"cash_per_share": 1.0, "exchange_ratio": None,
                         "stated_premium_pct": None, "premium_baseline": None,
                         "unaffected_price": None, "termination_fee_usd": None,
                         "parent_termination_fee_usd": None, "equity_value_usd": None,
                         "outside_date": None})
    ModelExtractor(client=client).extract(PROXY)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"]["additionalProperties"] is False


def test_the_booleans_stay_with_the_patterns():
    # A single keyword is what a regular expression is better at than a model,
    # and paying tokens to re-derive it would buy worse answers.
    text = PROXY + " The merger is conditioned on the Hart-Scott-Rodino waiting period."
    client = StubClient({name: None for name in (
        "cash_per_share", "exchange_ratio", "stated_premium_pct", "premium_baseline",
        "unaffected_price", "termination_fee_usd", "parent_termination_fee_usd",
        "equity_value_usd", "outside_date",
    )})
    terms = ModelExtractor(client=client).extract(text)
    assert terms.hsr is True


def test_an_unparsable_response_yields_nothing_rather_than_nonsense():
    class Broken(StubClient):
        def _create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="not json")])

    terms = ModelExtractor(client=Broken({})).extract(PROXY)
    assert terms.cash_per_share is None
    assert terms.stated_premium_pct is None
