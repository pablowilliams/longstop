from datetime import date

from longstop.edgar.submissions import Filing
from longstop.universe.outcomes import (
    ACQUIRER_SIDE,
    COMPLETED,
    COMPLETED_SHELL,
    NOT_REGISTRANT,
    PENDING,
    TERMINATED,
    UNRESOLVED,
    label_episode,
)

# Every episode needs a periodic report before the announcement to count as a
# public registrant at all, so the fixtures carry one.
PRIOR = ("10-K", "2018-03-01")

CUT = date(2026, 9, 22)


def f(form, filed, items=""):
    return Filing(form=form, filed=filed, items=items, accession="x", report_date="")


def label(filings, announced="2019-01-10", last=None, registrant=True):
    prior = [f(*PRIOR)] if registrant else []
    return label_episode(announced, last or announced, prior + list(filings), CUT)


def test_deregistration_after_announcement_means_the_deal_closed():
    out = label([f("8-K", "2019-05-01", "5.01,3.01"), f("25-NSE", "2019-05-02")])
    assert out.label == COMPLETED
    assert out.resolved_on == "2019-05-02"
    assert out.days_to_resolution == 112


def test_a_slow_deal_is_not_a_broken_one():
    # Eighteen months from signing to closing, filing quarterly reports the
    # whole way through. Measuring survival from the announcement called this a
    # break; measuring it from the resolution does not.
    filings = [
        f("10-Q", "2019-05-01"), f("10-K", "2019-09-01"), f("10-Q", "2020-02-01"),
        f("8-K", "2020-06-01", "5.01"), f("25-NSE", "2020-06-05"),
    ]
    assert label(filings).label == COMPLETED


def test_change_in_control_is_the_targets_signal_not_completion_of_acquisition():
    # Item 2.01 is what the buyer files. A target-side universe watching 2.01
    # alone misses most closings.
    assert label([f("8-K", "2019-05-01", "5.01")]).label == COMPLETED


def test_a_spac_that_exits_shell_status_has_closed_not_broken():
    # The registrant survives the merger, renames, and carries on filing.
    filings = [
        f("8-K", "2019-06-01", "2.01,5.06"),
        f("10-K", "2020-03-01"), f("10-K", "2021-03-01"),
    ]
    assert label(filings).label == COMPLETED_SHELL


def test_termination_item_plus_continued_reporting_means_it_broke():
    out = label([f("8-K", "2019-06-01", "1.02"), f("10-K", "2020-06-01")])
    assert out.label == TERMINATED
    assert "item1.02:8-K@2019-06-01" in out.evidence


def test_survival_with_no_signal_at_all_is_unresolved_not_a_break():
    # A tender offer that lapses quietly and a buyer-side proxy look identical
    # from metadata. Phase one reads the document; phase zero says so.
    out = label([f("10-K", "2020-06-01"), f("10-Q", "2020-09-01")])
    assert out.label == UNRESOLVED


def test_a_registrant_that_completes_an_acquisition_and_lives_was_the_buyer():
    # A DEFM14A filed to approve a share issuance, not a sale of the company.
    out = label([f("8-K", "2019-04-01", "2.01"), f("10-K", "2020-06-01")])
    assert out.label == ACQUIRER_SIDE


def test_a_filer_with_no_prior_periodic_reports_is_not_a_public_target():
    # SC 13E3 is filed by sponsors and bidders as well as the subject company.
    out = label([f("8-K", "2019-04-01", "5.01")], registrant=False)
    assert out.label == NOT_REGISTRANT


def test_reporting_after_a_deregistration_does_not_undo_it():
    # A company with public debt keeps filing 10-Ks under Section 15(d) long
    # after its equity delists. Aircastle and Cincinnati Bell both do this.
    filings = [f("25-NSE", "2019-05-02"), f("10-K", "2020-06-01"), f("10-K", "2021-06-01")]
    assert label(filings).label == COMPLETED


def test_a_recent_announcement_with_no_signal_is_pending():
    assert label([], announced="2026-08-01").label == PENDING


def test_an_old_announcement_with_no_signal_is_unresolved_not_completed():
    out = label([])
    assert out.label == UNRESOLVED
    assert out.resolved_on is None


def test_filings_before_the_announcement_are_ignored():
    assert label([f("25-NSE", "2018-01-01")]).label == UNRESOLVED


def test_signals_beyond_the_resolution_horizon_do_not_count():
    assert label([f("25-NSE", "2024-01-01")]).label == UNRESOLVED


def test_an_episode_cannot_be_resolved_after_the_next_deal_was_announced():
    # Baker Hughes. Announced with Halliburton in February 2015, that deal
    # terminated in May 2016, delisted in July 2017 on closing with GE. Reaching
    # forward past the next announcement turned the first episode into an 867
    # day completion and buried a real break.
    filings = [
        f("10-K", "2014-02-01"),
        f("8-K", "2016-05-02", "1.01,1.02,7.01"),
        f("10-K", "2017-02-01"),
        f("8-K12B", "2017-07-03", "5.01"),
        f("25-NSE", "2017-07-05"),
    ]
    reaching_forward = label_episode("2015-02-19", "2015-02-19", filings, CUT)
    assert reaching_forward.label == COMPLETED
    assert reaching_forward.days_to_resolution == 867

    capped = label_episode(
        "2015-02-19", "2015-02-19", filings, CUT, next_announcement="2017-05-30"
    )
    assert capped.label == TERMINATED
    assert capped.resolved_on == "2016-05-02"


def test_the_second_episode_still_resolves_normally():
    filings = [
        f("10-K", "2014-02-01"),
        f("8-K", "2016-05-02", "1.02"),
        f("8-K12B", "2017-07-03", "5.01"),
        f("25-NSE", "2017-07-05"),
    ]
    out = label_episode("2017-05-30", "2017-05-30", filings, CUT)
    assert out.label == COMPLETED
    assert out.resolved_on == "2017-07-05"
