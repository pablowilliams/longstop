"""Tests for point-in-time financials.

The property under test is that nothing leaks backwards. A 10-K for a year
ending in December is filed the following February or March, so a deal announced
in January cannot have used it, and a model that does is reporting a skill it
would not have had.
"""
from __future__ import annotations

from longstop.edgar.xbrl import latest_annual, snapshot


def facts(tag: str, rows: list[dict], namespace: str = "us-gaap") -> dict:
    return {
        "facts": {
            namespace: {
                tag: {"units": {"USD": rows}},
            }
        }
    }


def row(value: float, end: str, filed: str, form: str = "10-K") -> dict:
    return {"val": value, "end": end, "filed": filed, "form": form}


FILER = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        row(900e6, "2017-12-31", "2018-02-20"),
                        row(1_000e6, "2018-12-31", "2019-02-20"),
                        row(1_200e6, "2019-12-31", "2020-02-25"),
                        row(300e6, "2019-09-30", "2019-10-30", form="10-Q"),
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [row(120e6, "2018-12-31", "2019-02-20")]}
            },
        }
    }
}


def test_a_figure_filed_after_the_date_is_not_available_on_it():
    # The 2019 annual report was filed on 25 February 2020. A deal announced on
    # 10 January 2020 could not have seen it.
    fact = latest_annual(FILER, "revenue", known_by="2020-01-10")
    assert fact is not None
    assert fact.value == 1_000e6
    assert fact.period_end == "2018-12-31"


def test_the_same_lookup_a_month_later_does_see_it():
    fact = latest_annual(FILER, "revenue", known_by="2020-03-01")
    assert fact is not None
    assert fact.value == 1_200e6


def test_filtering_on_the_period_end_instead_would_have_leaked():
    # The trap this is guarding. The 2019 period ended before the announcement,
    # so a period-end filter would have admitted a figure nobody had yet.
    leaked = max(
        (r for r in FILER["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
         if r["end"] < "2020-01-10" and r["form"] == "10-K"),
        key=lambda r: r["end"],
    )
    assert leaked["val"] == 1_200e6
    assert latest_annual(FILER, "revenue", known_by="2020-01-10").value == 1_000e6


def test_quarterly_figures_are_excluded_from_an_annual_lookup():
    fact = latest_annual(FILER, "revenue", known_by="2020-01-10")
    assert fact.form == "10-K"


def test_the_tag_fallback_chain_finds_whichever_tag_the_filer_used():
    # There is no single tag for revenue. Which one a filer uses depends on the
    # filer, the year and the standard in force.
    modern = facts("RevenueFromContractWithCustomerExcludingAssessedTax",
                   [row(500e6, "2022-12-31", "2023-02-20")])
    legacy = facts("SalesRevenueNet", [row(400e6, "2014-12-31", "2015-02-20")])
    assert latest_annual(modern, "revenue", "2024-01-01").value == 500e6
    assert latest_annual(legacy, "revenue", "2016-01-01").value == 400e6


def test_an_absent_concept_returns_nothing_rather_than_a_zero():
    # A missing figure and a figure of zero are different things, and a model
    # that cannot tell them apart will happily value a company at nothing.
    assert latest_annual(FILER, "cash", known_by="2020-01-10") is None


def test_the_snapshot_records_which_tag_each_figure_came_from():
    taken = snapshot(FILER, known_by="2020-03-01", concepts=("revenue", "net_income", "cash"))
    assert taken["revenue"]["tag"] == "Revenues"
    assert taken["revenue"]["filed"] == "2020-02-25"
    assert taken["net_income"]["value"] == 120e6
    assert taken["cash"] is None


def test_a_restatement_filed_later_wins_for_the_same_period():
    restated = facts("Revenues", [
        row(1_000e6, "2018-12-31", "2019-02-20"),
        row(950e6, "2018-12-31", "2020-02-20"),
    ])
    assert latest_annual(restated, "revenue", "2021-01-01").value == 950e6
    assert latest_annual(restated, "revenue", "2019-06-01").value == 1_000e6
