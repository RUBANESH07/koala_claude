"""
Resolution Agent — normalises raw resort/unit strings for downstream pricing.

No taxonomy lookup: the raw resort and unit names supplied by the caller are
used directly as the display names. Bedroom tier and view class are parsed
out of the unit name with simple pattern matching.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Unit name parsers
# ---------------------------------------------------------------------------

_BEDROOM_PATTERN = re.compile(
    r"(\d+\s*Bedroom|Studio|Suite)", re.IGNORECASE
)
_VIEW_ORDER = [
    "Ocean Front", "Ocean View", "Partial Ocean View",
    "Garden View", "Pool View", "Mountain View", "City View",
    "Lake View", "Golf View",
]


def _extract_bedroom_tier(unit_name: str) -> str:
    m = _BEDROOM_PATTERN.search(unit_name)
    return m.group(0).title() if m else ""


def _extract_view_class(unit_name: str) -> str:
    lower = unit_name.lower()
    for view in _VIEW_ORDER:
        if view.lower() in lower:
            return view
    return ""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(raw_resort: str, raw_unit: str, taxonomy: Optional[list[dict]] = None) -> dict:
    """
    Normalise raw resort and unit strings into a resolution dict.

    Returns a dict:
      {
        "raw_resort": str,
        "raw_unit": str,
        "resort_db_id": None,
        "display_resort_name": str,
        "resort_search_terms": [str],
        "unit_db_id": None,
        "display_unit_name": str,
        "unit_search_terms": [str],
        "bedroom_tier": str,
        "view_class": str,
        "resort_confidence": "direct",
        "unit_confidence": "direct",
        "resort_match_score": 1.0,
        "unit_match_score": 1.0,
      }
    """
    display_resort = raw_resort.strip()
    display_unit = raw_unit.strip()

    return {
        "raw_resort": raw_resort,
        "raw_unit": raw_unit,
        "resort_db_id": None,
        "display_resort_name": display_resort,
        "resort_search_terms": [display_resort],
        "unit_db_id": None,
        "display_unit_name": display_unit,
        "unit_search_terms": [display_unit],
        "bedroom_tier": _extract_bedroom_tier(display_unit),
        "view_class": _extract_view_class(display_unit),
        "resort_confidence": "direct",
        "unit_confidence": "direct",
        "resort_match_score": 1.0,
        "unit_match_score": 1.0,
    }
