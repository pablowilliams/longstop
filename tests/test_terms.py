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
