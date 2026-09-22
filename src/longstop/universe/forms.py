"""Which EDGAR form types mean what, for the purposes of building a deal universe.

Two independent directions are used deliberately. The announcement forms are
filed by the target when a deal is signed. The outcome forms are filed when the
target stops being a public company, or when the agreement it signed is torn
up. Neither direction is complete on its own, and the gap between them is the
coverage number phase 0 exists to measure.
"""
from __future__ import annotations

# Target-side announcement forms. The registrant on each of these is the
# company being acquired, which is the CIK whose later filings tell us what
# happened to the deal.
#
# S-4 and 425 are deliberately excluded: their registrant is the acquirer, so
# they identify the wrong CIK for outcome tracking. Their absence is a known
# coverage gap and is measured rather than assumed away.
ANNOUNCEMENT_FORMS = frozenset(
    {
        "DEFM14A",   # definitive merger proxy
        "PREM14A",   # preliminary merger proxy
        "DEFM14C",   # definitive merger information statement (no vote solicited)
        "PREM14C",   # preliminary merger information statement
        "SC 14D9",   # target board's recommendation in a tender offer
        "SC 13E3",   # going-private transaction
    }
)

# Amendments carry the same signal. Matched by prefix so that "SC 14D9/A" and
# "SC 13E3/A" are picked up without enumerating every variant EDGAR has used
# across twenty-four years.
ANNOUNCEMENT_PREFIXES = tuple(sorted(ANNOUNCEMENT_FORMS))

# The target has ceased to be a listed, registered company. In the window after
# a signed merger this is close to conclusive evidence the deal closed, but it
# is not exclusive to mergers: bankruptcy and going dark produce the same forms,
# which is why proximity to an announcement is required, and why a company that
# carries on filing quarterly reports afterwards is reported as ambiguous
# rather than counted.
#
# 15-15D is excluded deliberately. It suspends a Section 15(d) reporting duty
# and is filed for reasons that have nothing to do with a merger, so including
# it bought coverage at the cost of precision.
DEREGISTRATION_FORMS = frozenset({"25", "25-NSE", "15-12B", "15-12G"})

# Periodic reports. A company still filing these long after its outside date is
# a company whose deal did not close.
PERIODIC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F"})

# 8-K item codes, from the SEC's current item taxonomy.
ITEM_MATERIAL_AGREEMENT = "1.01"   # entry into a material definitive agreement
ITEM_TERMINATION = "1.02"          # termination of a material definitive agreement
ITEM_COMPLETION = "2.01"           # completion of acquisition or disposition of assets
ITEM_CHANGE_CONTROL = "5.01"       # changes in control of registrant
ITEM_SHELL_STATUS = "5.06"         # change in shell company status

# Item 2.01 is the acquirer's signal. When a public company is bought, the buyer
# reports completing an acquisition and the target reports a change in control,
# so a target-side universe that watches 2.01 alone misses most closings.
#
# Item 5.06 is how a blank-cheque company reports that it has stopped being one.
# A SPAC does not deregister on closing: it renames and carries on filing, so
# without this signal every completed SPAC merger is labelled a break.
SHELL_SIC = "6770"                 # blank checks


def is_announcement(form: str) -> bool:
    form = form.strip().upper()
    return any(form == f or form.startswith(f + "/") for f in ANNOUNCEMENT_PREFIXES)


def is_deregistration(form: str) -> bool:
    form = form.strip().upper()
    return any(form == f or form.startswith(f + "/") for f in DEREGISTRATION_FORMS)


def is_periodic(form: str) -> bool:
    return form.strip().upper() in PERIODIC_FORMS


def is_shell_sic(sic: str) -> bool:
    return (sic or "").strip() == SHELL_SIC


def has_item(items: str, code: str) -> bool:
    """The submissions API returns 8-K items as a comma-separated string."""
    if not items:
        return False
    return code in {part.strip() for part in items.split(",")}
