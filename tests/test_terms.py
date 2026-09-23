from longstop.filings.terms import (
    INSUFFICIENT,
    MISMATCH,
    RECONCILED,
    extract_terms,
    reconcile,
)

# Written in the register real proxies use, including the line wrapping.
CASH_DEAL = """
Merger Consideration

At the effective time, each share of Company common stock will be converted into
the right to receive $58.50 per share in cash, without interest.

Background of the Merger

The consideration represents a premium of approximately 30.0% to the closing
price of the Company's common stock of $45.00 on 14 February 2020, the last
trading day before the announcement.

Termination Fees

The Company will be required to pay Parent a termination fee of $95 million if
the merger agreement is terminated in specified circumstances. Parent will pay
the Company a reverse termination fee of $190 million. The transaction values
the Company at an equity value of $3,100 million.

The obligations of Parent are not subject to any financing condition. The
merger is conditioned on expiration of the waiting period under the
Hart-Scott-Rodino Antitrust Improvements Act. The End Date under the merger
agreement is December 31, 2020.
"""

STOCK_DEAL = """
Each share of Company common stock will be converted into 0.4506 shares of
Parent common stock. The exchange ratio implies a premium of approximately
12.5% based on closing prices.
"""


def test_a_cash_deal_reads_end_to_end():
    terms = extract_terms(CASH_DEAL)
    assert terms.cash_per_share == 58.50
    assert terms.unaffected_price == 45.00
    assert terms.stated_premium_pct == 30.0
    assert terms.consideration == "cash"
    assert terms.termination_fee_usd == 95_000_000
    assert terms.parent_termination_fee_usd == 190_000_000
    assert terms.equity_value_usd == 3_100_000_000
    assert terms.outside_date == "December 31, 2020"
    assert terms.financing_condition is False
    assert terms.hsr is True
    assert terms.cfius is False


def test_the_break_fee_is_quoted_the_way_a_deal_team_quotes_it():
    # 95 over 3,100 is 3.06%, which is the range these fees actually sit in.
    assert extract_terms(CASH_DEAL).break_fee_pct == 3.065


def test_the_document_verifies_its_own_extraction():
    # 58.50 over 45.00 is a 30% premium, which is what the document says. Three
    # figures read from three different sections agreeing is the check, and no
    # annotator was involved in it.
    result = reconcile(extract_terms(CASH_DEAL))
    assert result.status == RECONCILED
    assert result.implied_premium_pct == 30.0
    assert result.absolute_error_pp == 0.0


def test_a_misread_price_fails_the_arithmetic_rather_than_being_reported():
    from dataclasses import replace

    broken = replace(extract_terms(CASH_DEAL), cash_per_share=85.50)
    result = reconcile(broken)
    assert result.status == MISMATCH
    assert result.absolute_error_pp > 1.5


def test_a_stock_deal_has_no_cash_arithmetic_to_check_and_says_so():
    terms = extract_terms(STOCK_DEAL)
    assert terms.consideration == "stock"
    assert terms.exchange_ratio == 0.4506
    assert reconcile(terms).status == INSUFFICIENT


def test_the_parent_fee_is_not_mistaken_for_the_company_fee():
    terms = extract_terms(CASH_DEAL)
    assert terms.termination_fee_usd < terms.parent_termination_fee_usd


# The wording real press releases use. Measured over two hundred deals, the
# number comes before the word far more often than after it.
NUMBER_FIRST = """Under the terms of the Merger, Carlyle will acquire all of the outstanding
shares of Synagro for $5.76 per share in cash, representing a 28.6% premium
based upon Synagro's closing share price on January 26, 2007.
"""

NEARLY = """Shareholders will receive stock and cash valued at $47.24 per share at the time
of announcement, a nearly 30% premium to the closing share price on October 6,
2006.
"""

AVERAGE_BASELINE_TEXT = """USI stockholders will receive $17.00 in cash for each share, representing a
premium of 20.5% to the average closing share price for the 30 calendar days
prior to October 24, 2006.
"""


def test_the_premium_is_read_when_the_number_comes_first():
    assert extract_terms(NUMBER_FIRST).stated_premium_pct == 28.6
    assert extract_terms(NEARLY).stated_premium_pct == 30.0


def test_the_baseline_is_recorded_because_it_is_not_always_the_close():
    assert extract_terms(NUMBER_FIRST).premium_baseline == "close"
    assert extract_terms(AVERAGE_BASELINE_TEXT).premium_baseline == "average"


def test_a_premium_to_an_average_is_not_checked_against_the_closing_price():
    # The identity holds against the unaffected close. Checking a consideration
    # against a thirty day average with it would compare two things that were
    # never equal, and a mismatch reported that way would mean nothing.
    from dataclasses import replace

    terms = replace(extract_terms(AVERAGE_BASELINE_TEXT), unaffected_price=14.11)
    result = reconcile(terms)
    assert result.status == INSUFFICIENT
    assert "average" in result.note


def test_the_original_wording_still_works():
    assert extract_terms(CASH_DEAL).stated_premium_pct == 30.0
    assert reconcile(extract_terms(CASH_DEAL)).status == RECONCILED


# A proxy runs to hundreds of pages and mentions many prices. The merger
# consideration is restated on nearly every page; a historical price, an option
# exercise price or a figure from a comparables table is written once. Taking the
# first match produced a median error of 110 percentage points against the
# document's own stated premium.
LONG_PROXY = """
The closing price of our common stock on 2 January 2014 was $12.40 per share.
Options outstanding have an exercise price of $9.75 per share.

Under the merger agreement each share will be converted into $58.50 per share in
cash. The board recommends the $58.50 per share in cash consideration. Holders
will receive $58.50 per share in cash, without interest.

The consideration represents a premium of approximately 30.0% to the closing
price of the Company's common stock of $45.00 on 14 February 2020.
The comparable companies traded at a premium of 12.0% on average.
"""


def test_the_repeated_price_wins_over_the_first_one_mentioned():
    terms = extract_terms(LONG_PROXY)
    assert terms.cash_per_share == 58.50
    assert terms.stated_premium_pct == 30.0


def test_the_extraction_then_verifies_against_the_document():
    assert extract_terms(LONG_PROXY).unaffected_price == 45.00
    assert reconcile(extract_terms(LONG_PROXY)).status == RECONCILED


def test_a_short_filing_is_unaffected_by_counting():
    # One mention each, so position and frequency agree.
    assert extract_terms(CASH_DEAL).cash_per_share == 58.50


def test_the_unaffected_price_is_read_beside_the_premium_it_belongs_to():
    # LONG_PROXY mentions a 2014 closing price of $12.40 before it states the
    # deal's $45.00. Choosing globally took the earlier one.
    assert extract_terms(LONG_PROXY).unaffected_price == 45.00


def test_the_baseline_detector_stops_at_the_sentence_end():
    # LONG_PROXY follows the premium sentence with "comparable companies traded
    # at a premium of 12.0% on average", and a window that ran past the full
    # stop labelled an ordinary premium to the close as an average.
    assert extract_terms(LONG_PROXY).premium_baseline == "close"


def test_an_impossible_premium_is_not_a_premium():
    # "300.0%" and "150.0%" came out of real proxies and are the pattern catching
    # a percentage that merely sits near the word.
    assert extract_terms("a 300.0% premium to the closing price").stated_premium_pct is None
    assert extract_terms("a 96.0% premium to the closing price").stated_premium_pct == 96.0


def test_an_unaffected_price_is_only_taken_beside_the_premium():
    # In a stock deal the proxy discusses both companies' share prices, and a
    # global search picked the acquirer's.
    stray = """The acquirer's shares closed at a closing price of $73.01 in March.
    Holders will receive $16.45 per share in cash."""
    assert extract_terms(stray).unaffected_price is None


def test_a_price_equal_to_the_consideration_is_a_collision_not_a_zero_premium():
    from dataclasses import replace

    terms = replace(
        extract_terms(CASH_DEAL), cash_per_share=24.80, unaffected_price=24.80
    )
    result = reconcile(terms)
    assert result.status == INSUFFICIENT
    assert "misread" in result.note
