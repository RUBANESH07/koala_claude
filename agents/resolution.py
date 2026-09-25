"""
Resolution Agent — matches raw resort/unit strings to taxonomy entries.

Match order:
  1. Exact display name match
  2. Exact alias match
  3. rapidfuzz fuzzy match (threshold 0.75)
  4. no_match

Fuzzy matches are logged to data/fuzzy_match_log.jsonl via structlog.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import structlog
from rapidfuzz import fuzz

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

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = ROOT / "data" / "taxonomy.json"
FUZZY_LOG_PATH = ROOT / "data" / "fuzzy_match_log.jsonl"

FUZZY_THRESHOLD = 0.75  # rapidfuzz scores are 0–100; we normalise to 0–1

# ---------------------------------------------------------------------------
# Structlog setup — writes fuzzy matches as JSONL
# ---------------------------------------------------------------------------

def _build_fuzzy_logger() -> structlog.BoundLogger:
    handler = logging.FileHandler(FUZZY_LOG_PATH, encoding="utf-8")
    handler.setLevel(logging.DEBUG)

    raw_logger = logging.getLogger("fuzzy_match")
    raw_logger.setLevel(logging.DEBUG)
    raw_logger.propagate = False
    if not raw_logger.handlers:
        raw_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger("fuzzy_match")


_fuzzy_log = _build_fuzzy_logger()

# ---------------------------------------------------------------------------
# Taxonomy loading
# ---------------------------------------------------------------------------

_taxonomy: Optional[list[dict]] = None


def load_taxonomy(path: Path = TAXONOMY_PATH) -> list[dict]:
    """Load and cache the taxonomy JSON."""
    global _taxonomy
    if _taxonomy is None:
        with path.open(encoding="utf-8") as fh:
            _taxonomy = json.load(fh)
    return _taxonomy


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    return s.strip().lower()


def _fuzzy_score(a: str, b: str) -> float:
    """Return token_set_ratio score normalised to 0–1."""
    return fuzz.token_set_ratio(_normalise(a), _normalise(b)) / 100.0


def _best_fuzzy(raw: str, candidates: list[str]) -> tuple[Optional[str], float]:
    """Return (best_candidate, score) above threshold, or (None, 0)."""
    best_text, best_score = None, 0.0
    for candidate in candidates:
        score = _fuzzy_score(raw, candidate)
        if score > best_score:
            best_text, best_score = candidate, score
    if best_score >= FUZZY_THRESHOLD:
        return best_text, best_score
    return None, best_score


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve(raw_resort: str, raw_unit: str, taxonomy: Optional[list[dict]] = None) -> dict:
    """
    Resolve raw resort and unit strings to a taxonomy entry.

    Returns a dict:
      {
        "raw_resort": str,
        "raw_unit": str,
        "resort_db_id": str | None,
        "display_resort_name": str | None,
        "unit_db_id": str | None,
        "display_unit_name": str | None,
        "resort_confidence": "exact" | "alias" | "fuzzy" | "no_match",
        "unit_confidence": "exact" | "alias" | "fuzzy" | "no_match",
        "resort_match_score": float,   # 1.0 for exact/alias, 0–1 for fuzzy
        "unit_match_score": float,
      }
    """
    if taxonomy is None:
        taxonomy = load_taxonomy()

    norm_resort = _normalise(raw_resort)
    norm_unit = _normalise(raw_unit)

    matched_entry: Optional[dict] = None
    resort_confidence = "no_match"
    resort_score = 0.0

    # --- Resort matching ---
    # Pass 1: exact display name
    for entry in taxonomy:
        if _normalise(entry["display_resort_name"]) == norm_resort:
            matched_entry = entry
            resort_confidence = "exact"
            resort_score = 1.0
            break

    # Pass 2: exact alias
    if matched_entry is None:
        for entry in taxonomy:
            if any(_normalise(a) == norm_resort for a in entry["resort_aliases"]):
                matched_entry = entry
                resort_confidence = "alias"
                resort_score = 1.0
                break

    # Pass 3: fuzzy
    if matched_entry is None:
        best_entry, best_score = None, 0.0
        for entry in taxonomy:
            candidates = [entry["display_resort_name"]] + entry["resort_aliases"]
            _, score = _best_fuzzy(raw_resort, candidates)
            if score > best_score:
                best_entry, best_score = entry, score
        if best_entry is not None and best_score >= FUZZY_THRESHOLD:
            matched_entry = best_entry
            resort_confidence = "fuzzy"
            resort_score = best_score
            _fuzzy_log.info(
                "fuzzy_resort_match",
                raw_resort=raw_resort,
                matched_resort=best_entry["display_resort_name"],
                score=round(best_score, 4),
            )

    # --- Unit matching (scoped to matched resort entry if found) ---
    unit_confidence = "no_match"
    unit_score = 0.0
    unit_entry: Optional[dict] = None

    # Scope unit search to ALL entries for the matched resort, not just the first one.
    if matched_entry:
        resort_id = matched_entry["resort_db_id"]
        search_pool = [e for e in taxonomy if e["resort_db_id"] == resort_id]
    else:
        search_pool = taxonomy

    # Pass 1: exact display name
    for entry in search_pool:
        if _normalise(entry["display_unit_name"]) == norm_unit:
            unit_entry = entry
            unit_confidence = "exact"
            unit_score = 1.0
            break

    # Pass 2: exact alias
    if unit_entry is None:
        for entry in search_pool:
            if any(_normalise(a) == norm_unit for a in entry["unit_aliases"]):
                unit_entry = entry
                unit_confidence = "alias"
                unit_score = 1.0
                break

    # Pass 3: fuzzy
    if unit_entry is None:
        best_entry, best_score = None, 0.0
        for entry in search_pool:
            candidates = [entry["display_unit_name"]] + entry["unit_aliases"]
            _, score = _best_fuzzy(raw_unit, candidates)
            if score > best_score:
                best_entry, best_score = entry, score
        if best_entry is not None and best_score >= FUZZY_THRESHOLD:
            unit_entry = best_entry
            unit_confidence = "fuzzy"
            unit_score = best_score
            _fuzzy_log.info(
                "fuzzy_unit_match",
                raw_unit=raw_unit,
                matched_unit=best_entry["display_unit_name"],
                score=round(best_score, 4),
            )

    resolved_resort = matched_entry or {}
    resolved_unit = unit_entry if unit_confidence != "no_match" else {}

    display_resort = resolved_resort.get("display_resort_name")
    display_unit = resolved_unit.get("display_unit_name")

    resort_search_terms: list[str] = []
    if display_resort:
        resort_search_terms = list(dict.fromkeys(
            [display_resort] + resolved_resort.get("resort_aliases", [])
        ))

    unit_search_terms: list[str] = []
    if display_unit:
        unit_search_terms = list(dict.fromkeys(
            [display_unit] + resolved_unit.get("unit_aliases", [])
        ))

    return {
        "raw_resort": raw_resort,
        "raw_unit": raw_unit,
        "resort_db_id": resolved_resort.get("resort_db_id"),
        "display_resort_name": display_resort,
        "resort_search_terms": resort_search_terms,
        "unit_db_id": resolved_unit.get("unit_db_id"),
        "display_unit_name": display_unit,
        "unit_search_terms": unit_search_terms,
        "bedroom_tier": _extract_bedroom_tier(display_unit) if display_unit else "",
        "view_class": _extract_view_class(display_unit) if display_unit else "",
        "resort_confidence": resort_confidence,
        "unit_confidence": unit_confidence,
        "resort_match_score": round(resort_score, 4),
        "unit_match_score": round(unit_score, 4),
    }
