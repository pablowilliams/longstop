from longstop.edgar.index import parse_index, parse_row
from longstop.universe import forms

# Real rows, copied from 2020 QTR1. The header in that file is misaligned with
# its own data, which is the reason nothing here parses by column position.
SAMPLE = """Description:           Master Index of EDGAR Dissemination Feed by Form Type

Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------
1-A              Acacia Diversified Holdings, Inc.                             1001463     2020-01-29  edgar/data/1001463/0001185185-20-000088.txt
DEFM14A          ADESTO TECHNOLOGIES Corp                                      1395848     2020-03-27  edgar/data/1395848/0001047469-20-001880.txt
SC 14D9          Forescout Technologies, Inc                                   1591890     2020-02-20  edgar/data/1591890/0001193125-20-042128.txt
SC 13E3/A        Bojangles Inc.                                                1649749     2020-01-06  edgar/data/1649749/0001193125-20-001745.txt
"""


def test_parses_form_types_containing_spaces():
    row = parse_row(
        "SC 14D9          Forescout Technologies, Inc                                   "
        "1591890     2020-02-20  edgar/data/1591890/0001193125-20-042128.txt"
    )
    assert row is not None
    assert row.form == "SC 14D9"
    assert row.company == "Forescout Technologies, Inc"
    assert row.cik == 1591890
    assert row.filed == "2020-02-20"
    assert row.accession == "0001193125-20-042128"


def test_filters_to_announcement_forms_and_counts_everything_seen():
    rows, seen, unparsed = parse_index(SAMPLE, forms.is_announcement)
    assert seen == 4
    assert unparsed == 0
    assert [r.form for r in rows] == ["DEFM14A", "SC 14D9", "SC 13E3/A"]


def test_unparsable_rows_are_counted_not_dropped_silently():
    broken = SAMPLE + "this is not an index row at all\n"
    _, seen, unparsed = parse_index(broken, forms.is_announcement)
    assert seen == 5
    assert unparsed == 1
