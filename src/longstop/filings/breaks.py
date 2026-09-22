"""Confirming a break against the document that reports it.

The universe labels a break when the target files an 8-K under item 1.02 and
carries on reporting. That item covers termination of any material definitive
agreement, so a terminated revolving credit facility looks identical to a
terminated merger. One 2020 episode resolved four days after its own definitive
proxy, which is not a deal dying, and the label needed to stop pretending
otherwise.

So every break candidate is read. The classifier is deterministic, it abstains
rather than guessing, and the section it based its answer on is kept alongside
the verdict so any call can be checked by eye.

The reason a deal died is extracted at the same time, because it is free once
the document is open and it is the most interesting variable in the dataset.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CONFIRMED = "confirmed"
UNRELATED = "unrelated"
UNCLEAR = "unclear"
NO_DOCUMENT = "no_document"
NO_SECTION = "no_section"

# Amalgamation is what a merger is called in Canada and Bermuda, and a share
# exchange is one of the structures a merger takes. Both appeared repeatedly in
# the undecided bucket, which means they were breaks being thrown away.
MERGER_AGREEMENT = re.compile(
    r"\b(agreement and plan of (?:merger|reorganization|amalgamation|share exchange)|"
    r"merger agreement|amalgamation agreement|share exchange agreement|"
    r"business combination agreement|arrangement agreement|"
    r"scheme implementation (?:agreement|deed)|plan of arrangement|"
    r"(?:the\s+)?transaction agreement)\b",
    re.IGNORECASE,
)

# The false positives. Every one of these is a material definitive agreement
# whose termination is reported under the same item.
# The false positives. Every one of these is a material definitive agreement
# whose termination is reported under the same item, and every phrase after the
# first line was put here because a real filing in this universe used it. An
# employee stock option plan, an equity forward contract and the sale of an
# apartment complex all file exactly like a dead merger.
#
# Broadening this list is safe in the direction that matters. A named merger
# agreement is matched first and wins, so nothing here can turn a real break
# into a non-break on its own.
OTHER_AGREEMENT = re.compile(
    r"\b(credit agreement|credit facility|loan agreement|revolving credit|"
    r"term loan|indenture|note purchase agreement|securities purchase agreement|"
    r"lease agreement|employment agreement|license agreement|"
    r"distribution agreement|supply agreement|collaboration agreement|"
    r"underwriting agreement|at.the.market|"
    r"(?:stock |equity )?(?:option|incentive|compensation|benefit) plan|"
    r"forward (?:contract|purchase agreement)|swap agreement|"
    r"investor rights agreement|registration rights agreement|"
    r"consulting agreement|advisory agreement|management agreement|"
    r"services agreement|joint venture agreement|"
    r"purchase and sale agreement|asset purchase agreement|"
    r"lease(?: agreement| termination agreement)?|security agreement|"
    r"guarant(?:y|ee) agreement|warrant plan|development agreement|"
    r"promissory note|senior notes?|convertible notes?)\b",
    re.IGNORECASE,
)

TERMINATION = re.compile(
    r"\b(terminat(?:e|ed|es|ing|ion)|mutually agreed to (?:end|terminate)|"
    r"withdraw(?:n|al)?|abandon(?:ed|ment)?|expired without)\b",
    re.IGNORECASE,
)

REASONS: dict[str, re.Pattern[str]] = {
    "regulatory": re.compile(
        r"\b(antitrust|hart.scott.rodino|second request|"
        r"(?:department of justice|federal trade commission|european commission)|"
        r"cfius|competition authority|regulatory approval(?:s)? (?:was|were) not|"
        r"failed to (?:obtain|receive) .{0,40}(?:regulatory|antitrust))\b",
        re.IGNORECASE,
    ),
    "superior_proposal": re.compile(
        r"\b(superior proposal|alternative acquisition (?:proposal|agreement)|"
        r"competing (?:proposal|offer|bid)|unsolicited proposal)\b",
        re.IGNORECASE,
    ),
    "shareholder_vote": re.compile(
        r"\b((?:stock|share)holders? (?:did not|failed to) approve|"
        r"(?:failed|did not) (?:to )?(?:obtain|receive) the requisite|"
        r"requisite (?:stock|share)holder (?:approval|vote) was not)\b",
        re.IGNORECASE,
    ),
    "financing": re.compile(
        r"\b(failure to (?:obtain|fund) .{0,30}financing|"
        r"financing (?:was|were) not (?:obtained|available)|debt financing failed)\b",
        re.IGNORECASE,
    ),
    "outside_date": re.compile(
        r"\b((?:outside|end|termination) date (?:had |has )?(?:passed|occurred|expired)|"
        r"(?:on or (?:prior to|before)|by) the (?:outside|end) date)\b",
        re.IGNORECASE,
    ),
    "material_adverse": re.compile(
        r"\b(material adverse (?:effect|change)|company material adverse)\b",
        re.IGNORECASE,
    ),
    "mutual": re.compile(
        r"\b(mutual (?:agreement|consent|written consent)|mutually agreed)\b",
        re.IGNORECASE,
    ),
}

# Filings define a term once and use the abbreviation forever after. The Aon and
# Willis Towers Watson 8-K, one of the clearest breaks in the dataset, says only
# that "the BCA was terminated by mutual consent", and no list of full agreement
# names will ever match that. So the document's own definitions are harvested:
# every (the "X") is read together with the text in front of it, and X inherits
# whatever class that text belongs to.
DEFINITION = re.compile(r"[\(\[]\s*(?:the|this)?\s*[\"\u201c\u2018\']([A-Z][A-Za-z0-9 &.\-]{1,60}?)[\"\u201d\u2019\']\s*[\)\]]")
DEFINITION_LOOKBACK = 160

# The tail of instrument names is genuinely open ended. This universe alone
# produced a Separation Agreement, a Collateral Protection Agreement and a
# Macadamia Nut Purchase Agreement, and enumerating those is overfitting rather
# than engineering.
#
# So the last tier is a rule instead of a list: a capitalised, specifically named
# instrument, in a filing whose text never mentions a merger agreement at all, is
# not a deal break. The qualifier matters. "Agreement" and "Material Definitive
# Agreement" are excluded because they are what a filing calls a merger agreement
# on second reference, and treating those as evidence would bury real breaks.
NAMED_INSTRUMENT = re.compile(
    r"\b((?:[A-Z][A-Za-z&-]+ ){1,4}(?:Agreement|Plan|Notes?|Lease|Contract))\b"
)
NOT_DISTINGUISHING = re.compile(
    r"^(?:the |this |such )?(?:material definitive|definitive|termination|"
    r"merger|amalgamation|arrangement|business combination|share exchange|"
    r"transaction)\b",
    re.IGNORECASE,
)

BREAK_FEE = re.compile(
    r"(?:termination|break.?up|break)\s+fee[^.]{0,120}?\$\s?([\d,]+(?:\.\d+)?)\s*"
    r"(million|billion|thousand)?",
    re.IGNORECASE,
)
MULTIPLIER = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000, None: 1}


@dataclass(frozen=True)
class Verdict:
    status: str
    reasons: tuple[str, ...] = ()
    break_fee_usd: float | None = None
    excerpt: str = ""
    evidence: tuple[str, ...] = field(default=())


HEADING_LINE = re.compile(
    r"^[ \t>*]*item\s*\d{1,2}\.\d{2}[.\s]*"
    r"(?:termination|entry)[^\n]*\n?",
    re.IGNORECASE,
)


def body_of(section: str) -> str:
    """The section without its heading, on one line.

    Two reasons, both of which produced wrong answers before they were handled.
    The heading of item 1.02 is literally "Termination of a Material Definitive
    Agreement", so a section that merely cross-references a merger agreement
    looked like a confirmed break. And filings wrap text at column eighty, so
    "Department of\nJustice" defeats any pattern spanning two words unless the
    whitespace is flattened first.
    """
    without_heading = HEADING_LINE.sub("", section, count=1)
    return re.sub(r"\s+", " ", without_heading).strip()


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    found = pattern.search(text)
    return found.group(0) if found else None


def _named_instrument(text: str) -> str | None:
    """A specifically named agreement, ignoring the generic ways of saying one."""
    for match in NAMED_INSTRUMENT.finditer(text):
        name = match.group(1).strip()
        if NOT_DISTINGUISHING.match(name):
            continue
        return name
    return None


def defined_terms(document: str) -> tuple[frozenset[str], frozenset[str]]:
    """Abbreviations the document defines, split into merger and everything else.

    Returns (merger_terms, other_terms). A term defined by text mentioning a
    merger or business combination joins the first set; one defined by text
    mentioning a credit facility or an indenture joins the second.
    """
    flat = re.sub(r"\s+", " ", document)
    merger: set[str] = set()
    other: set[str] = set()
    for match in DEFINITION.finditer(flat):
        term = match.group(1).strip()
        if len(term) < 2:
            continue
        context = flat[max(0, match.start() - DEFINITION_LOOKBACK): match.start()]
        # The nearest phrase wins. A lookback long enough to catch the agreement
        # being named is also long enough to reach back over an unrelated one, and
        # giving either class unconditional priority classified the credit
        # agreement in the Aon filing as a merger agreement.
        nearest_merger = max((m.start() for m in MERGER_AGREEMENT.finditer(context)), default=-1)
        nearest_other = max((m.start() for m in OTHER_AGREEMENT.finditer(context)), default=-1)
        if nearest_merger > nearest_other:
            merger.add(term)
        elif nearest_other > nearest_merger:
            other.add(term)
    # A term cannot be both. Where the document is contradictory, the narrower
    # reading wins and it is treated as unclassified.
    overlap = merger & other
    return frozenset(merger - overlap), frozenset(other - overlap)


def _term_pattern(terms: frozenset[str]) -> re.Pattern[str] | None:
    if not terms:
        return None
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in ordered) + r")\b")


def break_fee(text: str) -> float | None:
    found = BREAK_FEE.search(text)
    if not found:
        return None
    try:
        amount = float(found.group(1).replace(",", ""))
    except ValueError:
        return None
    scale = (found.group(2) or "").lower() or None
    return amount * MULTIPLIER.get(scale, 1)


def classify(section: str | None, document: str | None = None) -> Verdict:
    """Was it the merger that was terminated, or something else entirely?

    `document` is the whole filing. It is used only to resolve the abbreviations
    the filing defines for itself, which is how a section saying nothing but "the
    BCA was terminated" becomes readable.
    """
    if section is None:
        return Verdict(NO_SECTION)
    text = body_of(section)
    if not text:
        return Verdict(UNCLEAR)
    if not TERMINATION.search(text):
        return Verdict(UNCLEAR, excerpt=text[:400])

    merger = _first_match(MERGER_AGREEMENT, text)
    other = _first_match(OTHER_AGREEMENT, text)

    if document:
        merger_terms, other_terms = defined_terms(document)
        if merger is None:
            pattern = _term_pattern(merger_terms)
            merger = _first_match(pattern, text) if pattern else None
        if other is None:
            pattern = _term_pattern(other_terms)
            other = _first_match(pattern, text) if pattern else None

    if merger and not other:
        status = CONFIRMED
    elif merger and other:
        # Both named. A merger termination that also unwinds the acquisition
        # financing is common and is still a merger termination, so the merger
        # phrase wins when it appears first.
        lowered = text.lower()
        status = (
            CONFIRMED
            if lowered.index(merger.lower()) < lowered.index(other.lower())
            else UNCLEAR
        )
    elif other:
        status = UNRELATED
    else:
        named = _named_instrument(text)
        if named and not MERGER_AGREEMENT.search(document or text):
            other = named
            status = UNRELATED
        else:
            status = UNCLEAR

    reasons = tuple(name for name, pattern in REASONS.items() if pattern.search(text))
    evidence = tuple(x for x in (merger and f"merger:{merger}", other and f"other:{other}") if x)
    return Verdict(
        status=status,
        reasons=reasons,
        break_fee_usd=break_fee(text) if status == CONFIRMED else None,
        excerpt=text[:600],
        evidence=evidence,
    )
