"""What happened to the deal, derived from the target's own later filings.

Nobody labels these. A company that is acquired stops being a registrant, and
the paperwork ending its registration is itself the label.

Four things in this file were wrong in earlier versions. Each one moved the
headline number by several points, and each is the kind of error that a
plausible looking table would have hidden:

  Survival is measured from the resolution, not from the announcement. A deal
  taking eighteen months to close files quarterly reports the whole way
  through, and reading those as evidence it never closed turned slow deals into
  broken ones.

  The target reports a change in control, item 5.01. The acquirer reports
  completing an acquisition, item 2.01. A target-side universe watching 2.01
  alone misses most closings.

  A blank-cheque company does not deregister when its merger closes. It renames
  and carries on filing, reporting the change under item 5.06.

  Continued reporting after a deregistration is normal, not contradictory. A
  company with public debt keeps filing 10-Ks under Section 15(d) long after
  its equity delists, so treating that as a conflict marked real completions
  such as Aircastle and Cincinnati Bell as ambiguous.

What this file deliberately does not do is guess which side of the deal the
registrant is on. A DEFM14A can be filed by a buyer seeking approval to issue
shares, and from metadata alone that is indistinguishable from a target whose
deal broke. Those are labelled and set aside rather than counted, and phase one
resolves them by reading the document.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from longstop.edgar.submissions import Filing
from longstop.universe import forms

RESOLUTION_DAYS = 900   # deals slower than this are reported unresolved, not assumed closed
SURVIVAL_DAYS = 365     # periodic reporting this long after the last deal filing, with no
                        # resolution event, means the registrant was not taken private
PENDING_DAYS = 400      # announced this recently, no outcome expected yet

COMPLETED = "completed"
COMPLETED_SHELL = "completed_shell"
TERMINATED = "terminated"
ACQUIRER_SIDE = "acquirer_side"
PENDING = "pending"
UNRESOLVED = "unresolved"
NOT_REGISTRANT = "not_registrant"

LABELS = (
    COMPLETED,
    COMPLETED_SHELL,
    TERMINATED,
    ACQUIRER_SIDE,
    PENDING,
    UNRESOLVED,
    NOT_REGISTRANT,
)
COMPLETED_LABELS = (COMPLETED, COMPLETED_SHELL)
BREAK_LABELS = (TERMINATED,)
EXCLUDED_LABELS = (ACQUIRER_SIDE, NOT_REGISTRANT)


@dataclass(frozen=True)
class Outcome:
    label: str
    resolved_on: str | None
    days_to_resolution: int | None
    evidence: tuple[str, ...]
    resolved_accession: str | None = None
    resolved_form: str | None = None
    resolved_document: str | None = None


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def label_episode(
    announced: str,
    last_announcement: str,
    filings: tuple[Filing, ...] | list[Filing],
    data_cut: date,
    resolution_days: int = RESOLUTION_DAYS,
    survival_days: int = SURVIVAL_DAYS,
    pending_days: int = PENDING_DAYS,
    next_announcement: str | None = None,
) -> Outcome:
    start = _d(announced)
    last = _d(last_announcement)
    horizon = last + timedelta(days=resolution_days)

    # An episode cannot be resolved by something that happened after the next
    # deal was announced. Baker Hughes announced with Halliburton in February
    # 2015, that deal was terminated in May 2016, and the company delisted in
    # July 2017 on closing with GE. Without this cap the 2015 episode reached
    # forward, took the 2017 deregistration and was recorded as an 867 day
    # completion, with its own termination sitting unused in the evidence.
    if next_announcement:
        horizon = min(horizon, _d(next_announcement) - timedelta(days=1))

    dereg: Filing | None = None
    change_control: Filing | None = None
    shell_exit: Filing | None = None
    completion: Filing | None = None
    termination: Filing | None = None
    periodic_before = False
    periodic_after_survival = False
    survival_cutoff = last + timedelta(days=survival_days)

    for filing in filings:
        filed = _d(filing.filed)
        if forms.is_periodic(filing.form):
            if filed <= start:
                periodic_before = True
            elif filed > survival_cutoff:
                periodic_after_survival = True
        if filed <= start or filed > horizon:
            continue
        if dereg is None and forms.is_deregistration(filing.form):
            dereg = filing
        if filing.form.startswith("8-K"):
            if change_control is None and forms.has_item(filing.items, forms.ITEM_CHANGE_CONTROL):
                change_control = filing
            if shell_exit is None and forms.has_item(filing.items, forms.ITEM_SHELL_STATUS):
                shell_exit = filing
            if completion is None and forms.has_item(filing.items, forms.ITEM_COMPLETION):
                completion = filing
            if termination is None and forms.has_item(filing.items, forms.ITEM_TERMINATION):
                termination = filing

    evidence = tuple(
        f"{tag}:{f.form}@{f.filed}"
        for tag, f in (
            ("dereg", dereg),
            ("item5.01", change_control),
            ("item5.06", shell_exit),
            ("item2.01", completion),
            ("item1.02", termination),
        )
        if f is not None
    )

    def outcome(label: str, filing: Filing) -> Outcome:
        return Outcome(
            label,
            filing.filed,
            (_d(filing.filed) - start).days,
            evidence,
            resolved_accession=filing.accession,
            resolved_form=filing.form,
            resolved_document=filing.primary_document or None,
        )

    # SC 13E3 and SC 14D9 are filed by every party to the transaction, so the
    # index rows include sponsors, bidders and advisers alongside the subject
    # company. A registrant that never filed a periodic report before the deal
    # is not a public target, whatever form it appears on.
    if not periodic_before:
        return Outcome(NOT_REGISTRANT, None, None, evidence)

    if dereg is not None:
        return outcome(COMPLETED, dereg)

    if shell_exit is not None:
        return outcome(COMPLETED_SHELL, shell_exit)

    if change_control is not None and not periodic_after_survival:
        return outcome(COMPLETED, change_control)

    if periodic_after_survival:
        if termination is not None:
            return outcome(TERMINATED, termination)
        if completion is not None:
            # The registrant completed an acquisition and carried on filing, so
            # it was the buyer. A target-side break looks nothing like this.
            return outcome(ACQUIRER_SIDE, completion)
        return Outcome(UNRESOLVED, None, None, evidence)

    if completion is not None:
        return outcome(COMPLETED, completion)

    if (data_cut - last).days < pending_days:
        return Outcome(PENDING, None, None, evidence)
    return Outcome(UNRESOLVED, None, None, evidence)
