"""Grouping a target's deal filings into distinct deal episodes.

One company can be the target of more than one deal. A break in 2014 followed by
a successful sale in 2017 is two episodes on one CIK, and labelling the CIK
rather than the episode records the outcome of the second against the terms of
the first.

A time gap alone is not enough to separate them. Baker Hughes announced in
February 2015, had the Halliburton deal terminated in May 2016, and closed with
GE in July 2017. Filings ran continuously across all of it, so an eighteen month
gap rule saw one episode lasting 867 days and labelled it completed. The break
vanished.

So an episode also ends when it resolves. A termination or a deregistration
falling between two announcement filings is a boundary whatever the gap.

The bias in that rule is deliberate. Splitting too eagerly creates an episode
that may be labelled a break wrongly, and every break is afterwards read against
its own 8-K, so a false one is caught. Merging too eagerly hides a real break
inside a completion, and nothing downstream will ever find it. Given a choice,
be wrong in the direction that is checkable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DEFAULT_GAP_DAYS = 545  # eighteen months


def _as_date(iso: str) -> date:
    return date.fromisoformat(iso)


@dataclass
class Episode:
    cik: int
    company: str
    announced: str
    filings: list[tuple[str, str, str]] = field(default_factory=list)  # (form, filed, accession)

    @property
    def announce_date(self) -> date:
        return _as_date(self.announced)

    @property
    def forms(self) -> list[str]:
        return [form for form, _, _ in self.filings]

    @property
    def last_announcement(self) -> str:
        return max(filed for _, filed, _ in self.filings)


def group_episodes(
    cik: int,
    company: str,
    announcements: list[tuple[str, str, str]],
    gap_days: int = DEFAULT_GAP_DAYS,
    boundaries: list[str] | None = None,
) -> list[Episode]:
    """announcements is a list of (form, filed, accession), any order.

    boundaries are dates on which a deal resolved: a termination reported under
    8-K item 1.02, or a deregistration. An announcement on the far side of one
    belongs to a new deal.
    """
    if not announcements:
        return []
    ordered = sorted(announcements, key=lambda row: row[1])
    marks = sorted(boundaries or [])

    episodes: list[Episode] = []
    current = Episode(cik=cik, company=company, announced=ordered[0][1], filings=[ordered[0]])
    previous = ordered[0][1]

    for row in ordered[1:]:
        filed = row[1]
        gap_exceeded = (_as_date(filed) - _as_date(previous)).days > gap_days
        resolved_between = any(previous < mark < filed for mark in marks)
        if gap_exceeded or resolved_between:
            episodes.append(current)
            current = Episode(cik=cik, company=company, announced=filed, filings=[row])
        else:
            current.filings.append(row)
        previous = filed

    episodes.append(current)
    return episodes
