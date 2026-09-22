from longstop.universe import forms


def test_amendments_count_as_announcements():
    assert forms.is_announcement("DEFM14A")
    assert forms.is_announcement("SC 14D9/A")
    assert forms.is_announcement("SC 13E3/A")


def test_acquirer_side_forms_are_excluded():
    # S-4 and 425 name the acquirer as registrant, so they point at the wrong
    # CIK for outcome tracking. Excluding them is a known coverage gap.
    assert not forms.is_announcement("S-4")
    assert not forms.is_announcement("425")
    assert not forms.is_announcement("DEF 14A")


def test_item_parsing_handles_the_comma_separated_string():
    assert forms.has_item("1.01,2.03,9.01", "1.01")
    assert forms.has_item("2.01", "2.01")
    assert not forms.has_item("1.01,9.01", "1.02")
    assert not forms.has_item("", "2.01")


def test_item_matching_is_not_a_substring_match():
    assert not forms.has_item("11.01", "1.01")
