from longstop.filings.sections import item_sections

EIGHT_K = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Form 8-K

Item 1.01 Entry into a Material Definitive Agreement
Item 1.02 Termination of a Material Definitive Agreement
Item 9.01 Financial Statements and Exhibits

Item 1.01. Entry into a Material Definitive Agreement.

On 1 March the Company entered into an Agreement and Plan of Merger.

ITEM 1.02. TERMINATION OF A MATERIAL DEFINITIVE AGREEMENT.

On 26 June, the Company and Parent mutually agreed to terminate the Merger
Agreement following the failure to obtain antitrust approval.

Item 9.01 Financial Statements and Exhibits.

(d) Exhibits.
"""


def test_the_table_of_contents_does_not_win_over_the_body():
    sections = item_sections(EIGHT_K)
    assert "mutually agreed to terminate" in sections["1.02"]
    assert "Financial Statements" not in sections["1.02"]


def test_every_item_code_present_is_returned():
    assert set(item_sections(EIGHT_K)) == {"1.01", "1.02", "9.01"}


def test_capitalisation_and_punctuation_vary_and_do_not_matter():
    assert item_sections("item 5.02 Departure of Directors\nsomething happened")["5.02"]
    assert item_sections("ITEM 5.02. Departure\nsomething")["5.02"]


def test_a_document_with_no_items_returns_nothing():
    assert item_sections("just some prose about a merger") == {}


# The other layout: every heading listed together, then one narrative for all of
# them. Splitting this naively gives item 1.02 nothing but its own title and
# hands the narrative to item 2.03.
LISTED_HEADINGS = """Item 1.01.

Entry into a Material Definitive Agreement.

Item 1.02

Termination of a Material Definitive Agreement.

Item 2.03.

Creation of a Direct Financial Obligation.

On October 31, 2007 the Company entered into a secured business loan agreement
with JP Morgan Chase Bank, replacing a credit facility with the Company's
wholly-owned subsidiary, and that credit facility was terminated.
"""


def test_a_run_of_headings_shares_the_narrative_that_follows_it():
    sections = item_sections(LISTED_HEADINGS)
    assert "secured business loan agreement" in sections["1.02"]
    assert "secured business loan agreement" in sections["1.01"]
    assert "secured business loan agreement" in sections["2.03"]


def test_the_shared_narrative_still_classifies():
    # And it classifies as unrelated, which is the right answer: this is a credit
    # facility, not a merger. Before the fix it was unclear, which is not an
    # answer at all.
    from longstop.filings.breaks import UNRELATED, classify

    assert classify(item_sections(LISTED_HEADINGS).get("1.02"), LISTED_HEADINGS).status == UNRELATED


def test_the_ordinary_layout_is_unchanged():
    sections = item_sections(EIGHT_K)
    assert "mutually agreed to terminate" in sections["1.02"]
    assert "Agreement and Plan of Merger" in sections["1.01"]
    assert "mutually agreed to terminate" not in sections["1.01"]


def test_a_short_real_section_is_not_mistaken_for_a_listing():
    # "On 1 March the Company entered into an Agreement and Plan of Merger." is
    # sixty characters and is a section, not a heading. Length alone called it a
    # listing and handed item 1.01's narrative to every other item in the file.
    from longstop.filings.sections import _is_title_only

    assert _is_title_only("Item 1.02\n\nTermination of a Material Definitive Agreement.")
    assert not _is_title_only(
        "Item 1.01.\n\nOn 1 March 2019 the Company entered into an Agreement and Plan of Merger."
    )
