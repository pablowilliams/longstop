"""Two extractors behind one interface, measured by the same check.

The deterministic extractor is patterns. It decides fast, costs nothing, needs no
key, and on the proxy pilot 7 of its 8 checkable extractions satisfied the
document's own arithmetic. What it cannot do is read prose it was not written
for, and merger proxies are not written to a template.

The model extractor is Claude behind the same interface. It is not here to
replace the patterns; it is here to be measured against them on the same
documents with the same identity, so the comparison is objective rather than a
matter of taste:

    premium = consideration / unaffected price - 1

Two things keep it honest. The deterministic path stays the default, so the
benchmark reproduces with no key and no spend. And the model never sees the
whole filing: a proxy runs to hundreds of pages, most of it boilerplate, so the
locator picks the passages where terms are actually stated and sends those. That
is cheaper, and it is also better, because a model given three hundred pages of
which two matter has the same problem the patterns had.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import fields
from typing import Protocol

from longstop.filings.terms import Terms, extract_terms

DEFAULT_MODEL = "claude-opus-5"

# Where terms are stated. The locator is deliberately generous: a passage that
# turns out to be irrelevant costs a few hundred tokens, while a missing one
# costs the field.
ANCHORS = re.compile(
    r"(merger consideration|per share in cash|termination fee|break.?up fee|"
    r"premium of|% premium|percent premium|unaffected|closing (?:sale |market )?price|"
    r"outside date|end date|financing condition|equity value|exchange ratio|"
    r"aggregate consideration|go.?shop|no.?shop)",
    re.IGNORECASE,
)
WINDOW_CHARS = 700
MAX_EXCERPT_CHARS = 30_000


def excerpt(text: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    """The passages where terms are stated, in document order, deduplicated."""
    flat = re.sub(r"[ \t]+", " ", text)
    spans: list[tuple[int, int]] = []
    for match in ANCHORS.finditer(flat):
        start = max(0, match.start() - WINDOW_CHARS // 2)
        end = min(len(flat), match.end() + WINDOW_CHARS // 2)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))

    out: list[str] = []
    budget = max_chars
    for start, end in spans:
        piece = flat[start:end]
        if len(piece) > budget:
            out.append(piece[:budget])
            break
        out.append(piece)
        budget -= len(piece)
    return "\n[...]\n".join(out)


# Only the fields a filing states in prose. Booleans the patterns already read
# reliably from single keywords are left to them.
MODEL_FIELDS = (
    "cash_per_share",
    "exchange_ratio",
    "stated_premium_pct",
    "premium_baseline",
    "unaffected_price",
    "termination_fee_usd",
    "parent_termination_fee_usd",
    "equity_value_usd",
    "outside_date",
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(MODEL_FIELDS),
    "properties": {
        "cash_per_share": {
            "type": ["number", "null"],
            "description": "Cash paid per target share under the merger agreement. "
            "Not a historical trading price, not an option exercise price.",
        },
        "exchange_ratio": {
            "type": ["number", "null"],
            "description": "Acquirer shares issued per target share, for stock consideration.",
        },
        "stated_premium_pct": {
            "type": ["number", "null"],
            "description": "The premium the filing states, in percent. 28.6 means 28.6%.",
        },
        "premium_baseline": {
            "type": ["string", "null"],
            "enum": ["close", "average", None],
            "description": "What the premium is quoted against: the unaffected closing "
            "price, or an average such as a 30 day VWAP.",
        },
        "unaffected_price": {
            "type": ["number", "null"],
            "description": "The target's share price the premium is measured from. "
            "Only the target's price, never the acquirer's.",
        },
        "termination_fee_usd": {
            "type": ["number", "null"],
            "description": "Fee the target pays the acquirer, in dollars, not millions.",
        },
        "parent_termination_fee_usd": {
            "type": ["number", "null"],
            "description": "Reverse termination fee the acquirer pays the target, in dollars.",
        },
        "equity_value_usd": {
            "type": ["number", "null"],
            "description": "Equity value of the transaction, in dollars.",
        },
        "outside_date": {
            "type": ["string", "null"],
            "description": "The outside or end date by which the deal must close, as written.",
        },
    },
}

INSTRUCTION = """You are reading passages from a US merger filing.

Report only what the document states. Where it does not state a field, return
null for that field. Do not infer, compute or estimate any value: a null is
correct and a plausible guess is not, because these figures are checked against
the document's own arithmetic afterwards.

Two traps this document type sets:
- A proxy quotes many prices. The merger consideration is the one paid per target
  share under the agreement, not a historical trading price, an option exercise
  price, or a figure from a comparable companies table.
- In a stock deal both companies' share prices appear. The unaffected price is
  the target's.

Return fees and values in dollars, so ninety-five million is 95000000."""


class Extractor(Protocol):
    name: str

    def extract(self, text: str) -> Terms: ...


class DeterministicExtractor:
    """The patterns. No key, no spend, reproducible."""

    name = "deterministic"

    def extract(self, text: str) -> Terms:
        return extract_terms(text)


class ModelExtractor:
    """Claude, reading the located passages rather than the whole filing."""

    name = "model"

    def __init__(self, client=None, model: str = DEFAULT_MODEL, max_chars: int = MAX_EXCERPT_CHARS):
        self.model = model
        self.max_chars = max_chars
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def extract(self, text: str) -> Terms:
        passages = excerpt(text, self.max_chars)
        if not passages.strip():
            return Terms()

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=INSTRUCTION,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{"role": "user", "content": passages}],
        )
        return self.to_terms(response, text)

    @staticmethod
    def to_terms(response, text: str) -> Terms:
        """Map the structured response onto Terms.

        The booleans stay with the patterns. A single keyword is exactly the kind
        of thing a regular expression is better at than a model, and paying for
        tokens to re-derive them would be spending money to get worse answers.
        """
        payload: dict = {}
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                try:
                    payload = json.loads(block.text)
                except (ValueError, TypeError):
                    payload = {}
                break

        keep = {f.name for f in fields(Terms)}
        values = {
            name: payload.get(name)
            for name in MODEL_FIELDS
            if name in keep and payload.get(name) is not None
        }
        flags = extract_terms(text)
        return Terms(
            **values,
            financing_condition=flags.financing_condition,
            go_shop=flags.go_shop,
            hsr=flags.hsr,
            cfius=flags.cfius,
            tender_offer=flags.tender_offer,
        )


def get_extractor(name: str = "deterministic", **kwargs) -> Extractor:
    if name == "deterministic":
        return DeterministicExtractor()
    if name == "model":
        return ModelExtractor(**kwargs)
    raise ValueError(f"unknown extractor {name!r}, expected 'deterministic' or 'model'")


def has_credentials() -> bool:
    """Whether a model run is even possible here, checked before spending."""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
