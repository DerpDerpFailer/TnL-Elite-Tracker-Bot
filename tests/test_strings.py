from __future__ import annotations

from bot import strings


def test_zone_list_entry_formats_nested_bullets():
    result = strings.zone_list_entry("Laslan", ["Urstella Fields", "Aida's Camp"])
    assert result == "* Laslan\n  * Urstella Fields\n  * Aida's Camp"


def test_zone_list_entry_with_no_subzones_is_just_the_zone():
    assert strings.zone_list_entry("Syleus", []) == "* Syleus"
