"""
Tests for agents/resolution.py

No taxonomy lookup: resolve() passes raw resort/unit names through directly
and parses bedroom tier / view class out of the unit name.
"""

from agents.resolution import resolve


class TestDirectResolution:
    def test_names_passed_through(self):
        result = resolve("Marriott's Grand Chateau", "1 Bedroom Villa")
        assert result["display_resort_name"] == "Marriott's Grand Chateau"
        assert result["display_unit_name"] == "1 Bedroom Villa"
        assert result["resort_confidence"] == "direct"
        assert result["unit_confidence"] == "direct"
        assert result["resort_match_score"] == 1.0
        assert result["unit_match_score"] == 1.0

    def test_no_db_ids(self):
        result = resolve("Any Resort", "Any Unit")
        assert result["resort_db_id"] is None
        assert result["unit_db_id"] is None

    def test_whitespace_stripped(self):
        result = resolve("  Ocean Breeze Resort  ", "  Deluxe Studio  ")
        assert result["display_resort_name"] == "Ocean Breeze Resort"
        assert result["display_unit_name"] == "Deluxe Studio"

    def test_raw_strings_preserved(self):
        result = resolve("Ocean Breeze Resort", "Deluxe Studio")
        assert result["raw_resort"] == "Ocean Breeze Resort"
        assert result["raw_unit"] == "Deluxe Studio"

    def test_search_terms(self):
        result = resolve("Ocean Breeze Resort", "Deluxe Studio")
        assert result["resort_search_terms"] == ["Ocean Breeze Resort"]
        assert result["unit_search_terms"] == ["Deluxe Studio"]


class TestBedroomTierExtraction:
    def test_studio(self):
        result = resolve("Some Resort", "Studio Suite")
        assert result["bedroom_tier"] == "Studio"

    def test_one_bedroom(self):
        result = resolve("Some Resort", "1 Bedroom Villa")
        assert result["bedroom_tier"] == "1 Bedroom"

    def test_two_bedroom(self):
        result = resolve("Some Resort", "2 Bedroom Ocean View")
        assert result["bedroom_tier"] == "2 Bedroom"

    def test_no_bedroom_info(self):
        result = resolve("Some Resort", "Penthouse")
        assert result["bedroom_tier"] == ""


class TestViewClassExtraction:
    def test_ocean_view(self):
        result = resolve("Some Resort", "1 Bedroom Ocean View")
        assert result["view_class"] == "Ocean View"

    def test_mountain_view(self):
        result = resolve("Some Resort", "Studio Mountain View")
        assert result["view_class"] == "Mountain View"

    def test_no_view_info(self):
        result = resolve("Some Resort", "1 Bedroom Villa")
        assert result["view_class"] == ""
