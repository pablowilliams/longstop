import pytest

from longstop.filings.breaks import (
    CONFIRMED,
    NO_SECTION,
    UNCLEAR,
    UNRELATED,
    break_fee,
    classify,
)

MERGER = """Item 1.02. Termination of a Material Definitive Agreement.

On 26 July 2021, the Company and Parent entered into a Termination Agreement
pursuant to which the Agreement and Plan of Merger was terminated. The
termination followed the civil antitrust action filed by the Department of
Justice. Parent paid the Company a termination fee of $1,000 million.
"""

CREDIT_FACILITY = """Item 1.02. Termination of a Material Definitive Agreement.

On 22 December 2020, the Company terminated its revolving credit agreement
dated 2016 and repaid all amounts outstanding thereunder.
"""

TOPPING_BID = """Item 1.02 Termination of a Material Definitive Agreement

The Board determined that the unsolicited proposal constituted a Superior
Proposal and terminated the Merger Agreement, paying a termination fee of
$40.5 million.
"""

NO_TERMINATION = """Item 1.02 Termination of a Material Definitive Agreement

Reference is made to the Merger Agreement described under Item 1.01 above.
"""


def test_a_terminated_merger_agreement_is_confirmed():
    verdict = classify(MERGER)
    assert verdict.status == CONFIRMED
    assert "regulatory" in verdict.reasons
    assert verdict.break_fee_usd == 1_000_000_000


def test_a_terminated_credit_facility_is_not_a_deal_break():
    # This is the false positive that made one 2020 episode appear to die four
    # days after its own definitive proxy.
    verdict = classify(CREDIT_FACILITY)
    assert verdict.status == UNRELATED
    assert verdict.break_fee_usd is None


def test_the_reason_is_extracted_not_just_the_fact():
    verdict = classify(TOPPING_BID)
    assert verdict.status == CONFIRMED
    assert "superior_proposal" in verdict.reasons
    assert verdict.break_fee_usd == 40_500_000


def test_a_section_with_no_termination_language_abstains():
    assert classify(NO_TERMINATION).status == UNCLEAR


def test_a_missing_section_is_reported_not_guessed():
    assert classify(None).status == NO_SECTION


def test_break_fee_scales_are_read_correctly():
    assert break_fee("a termination fee of $1.5 billion") == 1_500_000_000
    assert break_fee("break-up fee of $725 million") == 725_000_000
    assert break_fee("termination fee of $12,500,000") == 12_500_000
    assert break_fee("no fee mentioned here") is None


def test_every_verdict_keeps_the_text_it_was_based_on():
    assert "Department of Justice" in classify(MERGER).excerpt  # whitespace is flattened


WRAPPED = """Item 1.02. Termination of a Material Definitive Agreement.

The Merger Agreement was terminated after the Department of
Justice filed a civil antitrust complaint, and the requisite
stockholder approval was not
obtained.
"""


def test_patterns_survive_a_filing_wrapped_at_column_eighty():
    # "Department of\nJustice" defeats any two-word pattern unless whitespace is
    # flattened first, and real filings wrap constantly.
    verdict = classify(WRAPPED)
    assert verdict.status == CONFIRMED
    assert "regulatory" in verdict.reasons
    assert "shareholder_vote" in verdict.reasons


def test_the_heading_does_not_supply_its_own_evidence():
    # The heading of item 1.02 is the words "Termination of a Material
    # Definitive Agreement", which is not evidence that anything terminated.
    from longstop.filings.breaks import body_of

    assert "Termination of a Material" not in body_of(
        "Item 1.02. Termination of a Material Definitive Agreement.\nSomething else."
    )


# The Aon and Willis Towers Watson termination, in the shape the real 8-K takes.
# It is the clearest break in the dataset and the first version of this
# classifier returned "unclear" on it, because the section never writes the
# agreement's name out.
ABBREVIATED = """On March 9, 2020, the Company entered into a Business Combination Agreement
(the "BCA") with Aon plc. Separately the Company amended its revolving credit
agreement (the "Credit Agreement").

Item 1.02. Termination of a Material Definitive Agreement.

On July 26, 2021, the Company entered into the Termination Agreement pursuant to
which the BCA was terminated by mutual consent, subject to receipt by the
Company of $1 billion payable by Aon, following the civil antitrust action
brought by the Department of Justice.
"""

ABBREVIATED_CREDIT = """The Company entered into a revolving credit agreement (the "Revolver").

Item 1.02. Termination of a Material Definitive Agreement.

On 22 December 2020 the Company terminated the Revolver and repaid all amounts
outstanding.
"""


def _section(document: str) -> str | None:
    from longstop.filings.sections import item_sections

    return item_sections(document).get("1.02")


def test_a_break_referred_to_only_by_its_abbreviation_is_still_confirmed():
    verdict = classify(_section(ABBREVIATED), ABBREVIATED)
    assert verdict.status == CONFIRMED
    assert "merger:BCA" in verdict.evidence
    assert "regulatory" in verdict.reasons


def test_the_same_document_without_its_definitions_cannot_be_read():
    # Proof the definitions are doing the work, not something else in the text.
    assert classify(_section(ABBREVIATED)).status == UNCLEAR


def test_a_credit_facility_referred_to_by_abbreviation_is_still_not_a_break():
    verdict = classify(_section(ABBREVIATED_CREDIT), ABBREVIATED_CREDIT)
    assert verdict.status == UNRELATED
    assert "other:Revolver" in verdict.evidence


def test_the_nearest_phrase_classifies_a_defined_term():
    # A lookback long enough to catch the agreement being named also reaches back
    # over unrelated ones. Giving merger unconditional priority classified the Aon
    # filing's credit agreement as a merger agreement.
    from longstop.filings.breaks import defined_terms

    merger, other = defined_terms(ABBREVIATED)
    assert merger == frozenset({"BCA"})
    assert other == frozenset({"Credit Agreement"})


def test_a_term_defined_by_nothing_relevant_is_left_unclassified():
    from longstop.filings.breaks import defined_terms

    merger, other = defined_terms('The parties issued a press release (the "Release").')
    assert "Release" not in merger and "Release" not in other


@pytest.mark.parametrize(
    "section",
    [
        # All four are real shapes from this universe's unclear bucket.
        "Item 1.02 Termination.\nThe board terminated the 2000 Employee Stock Option Plan.",
        "Item 1.02 Termination.\nThe Company paid $882 million due under its equity "
        "forward contract and the contract was terminated.",
        "Item 1.02 Termination.\nThe parties agreed to terminate the Investor Rights "
        "Agreement dated July 2003.",
        "Item 1.02 Termination.\nThe Company terminated the purchase and sale agreement "
        "for Palm Lake Apartments.",
    ],
)
def test_non_merger_terminations_are_decided_not_left_unclear(section):
    assert classify(section).status == UNRELATED


def test_broadening_the_other_list_cannot_bury_a_real_break():
    # The merger agreement is named, so it wins even though a plan is also named.
    section = (
        "Item 1.02 Termination.\nThe Merger Agreement was terminated, and in "
        "connection therewith the Company terminated its equity incentive plan."
    )
    assert classify(section).status == CONFIRMED
