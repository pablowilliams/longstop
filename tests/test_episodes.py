from longstop.universe.episodes import group_episodes


def test_one_deal_is_one_episode():
    episodes = group_episodes(
        1, "Target Inc",
        [("PREM14A", "2019-03-01", "a"), ("DEFM14A", "2019-04-15", "b")],
    )
    assert len(episodes) == 1
    assert episodes[0].announced == "2019-03-01"
    assert episodes[0].last_announcement == "2019-04-15"


def test_a_broken_deal_then_a_later_sale_is_two_episodes():
    # Labelling the CIK rather than the episode would record the 2017 outcome
    # against the 2014 terms.
    episodes = group_episodes(
        1, "Target Inc",
        [("DEFM14A", "2014-02-01", "a"), ("DEFM14A", "2017-09-01", "b")],
    )
    assert [e.announced for e in episodes] == ["2014-02-01", "2017-09-01"]


def test_the_gap_is_a_parameter_not_a_truth():
    filings = [("DEFM14A", "2014-02-01", "a"), ("DEFM14A", "2015-06-01", "b")]
    assert len(group_episodes(1, "T", filings, gap_days=545)) == 1
    assert len(group_episodes(1, "T", filings, gap_days=200)) == 2


def test_unordered_input_is_sorted():
    episodes = group_episodes(
        1, "T", [("DEFM14A", "2019-04-15", "b"), ("PREM14A", "2019-03-01", "a")]
    )
    assert episodes[0].announced == "2019-03-01"


def test_a_resolution_between_two_announcements_ends_the_episode():
    # Baker Hughes: announced February 2015, the Halliburton deal terminated in
    # May 2016, closed with GE in July 2017. Filings ran continuously, so the
    # gap rule alone saw one episode of 867 days and labelled it completed. The
    # break disappeared.
    # The intermediate filing is the point. No single consecutive gap exceeds
    # eighteen months, so the gap rule chains all three into one episode.
    filings = [
        ("DEFM14A", "2015-02-19", "a"),
        ("PREM14A", "2016-01-15", "b"),
        ("DEFM14A", "2016-10-31", "c"),
    ]
    assert len(group_episodes(1, "Baker Hughes", filings, gap_days=545)) == 1
    split = group_episodes(1, "Baker Hughes", filings, gap_days=545, boundaries=["2016-05-02"])
    assert [e.announced for e in split] == ["2015-02-19", "2016-10-31"]


def test_a_resolution_outside_the_interval_does_not_split_anything():
    filings = [("DEFM14A", "2019-03-01", "a"), ("DEFM14A", "2019-06-01", "b")]
    assert len(group_episodes(1, "T", filings, boundaries=["2018-01-01", "2020-01-01"])) == 1


def test_boundaries_are_optional():
    filings = [("DEFM14A", "2019-03-01", "a"), ("DEFM14A", "2019-06-01", "b")]
    assert len(group_episodes(1, "T", filings)) == 1
