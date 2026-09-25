"""
Validation Agent — reviews search results, enforces hard rules, assigns confidence.

Hard rules (any violation strips the result):
  - No bedroom tier downgrade vs. the resolved unit
  - Nights count must be preserved

Confidence scoring:
  HIGH   — 3+ results matched at fallback level 1 or 2
  MEDIUM — 2+ results matched at any fallback level
  LOW    — fewer than 2 matched, OR all matched results at level 5–6
"""

import re
from typing import Optional

import structlog

log = structlog.get_logger()

# Bedroom tiers in ascending order — used to detect downgrades.
_TIER_ORDER = ["Studio", "1 Bedroom", "2 Bedroom", "3 Bedroom", "4 Bedroom"]

_BEDROOM_RE = re.compile(r"(\d+)\s*Bedroom|Studio", re.IGNORECASE)


def _tier_rank(unit_name: str) -> int:
    """Return sort rank for a unit name; lower = smaller unit. -1 if unknown."""
    if not unit_name:
        return -1
    lower = unit_name.lower()
    if "studio" in lower:
        return 0
    m = _BEDROOM_RE.search(unit_name)
    if m and m.group(1):
        return int(m.group(1))
    return -1


def _nights_from_result(result: dict) -> Optional[int]:
    """Derive nights from 'dates_matched' field (MM/DD/YYYY–MM/DD/YYYY)."""
    dm = result.get("dates_matched") or ""
    parts = dm.split("–")
    if len(parts) != 2:
        return None
    try:
        from datetime import datetime
        ci = datetime.strptime(parts[0].strip(), "%m/%d/%Y")
        co = datetime.strptime(parts[1].strip(), "%m/%d/%Y")
        return (co - ci).days
    except ValueError:
        return None


def _validate_result(result: dict, resolved_unit: str, expected_nights: int) -> tuple[dict, list[str]]:
    """
    Validate a single platform result against hard rules.

    Returns (result_with_valid_flag, list_of_flags).
    """
    flags: list[str] = []
    platform = result.get("platform", "Unknown")

    if result.get("status") == "no_match" or not result.get("nightly_rate_usd"):
        return result, flags

    unit_matched = result.get("unit_matched") or ""
    resolved_rank = _tier_rank(resolved_unit)
    matched_rank = _tier_rank(unit_matched)

    # Hard rule 1: no bedroom tier mismatch beyond 1 tier
    if resolved_rank != -1 and matched_rank != -1:
        tier_diff = matched_rank - resolved_rank
        if tier_diff < 0:
            flags.append(
                f"{platform}: tier downgrade detected "
                f"(resolved={resolved_unit!r}, matched={unit_matched!r}) — result stripped"
            )
            log.warning("validation_tier_downgrade", platform=platform,
                        resolved_unit=resolved_unit, matched_unit=unit_matched)
            result = {**result, "status": "invalid", "nightly_rate_usd": None, "total_usd": None}
            return result, flags
        if tier_diff > 1:
            flags.append(
                f"{platform}: tier too large "
                f"(resolved={resolved_unit!r}, matched={unit_matched!r}) — result stripped"
            )
            log.warning("validation_tier_too_large", platform=platform,
                        resolved_unit=resolved_unit, matched_unit=unit_matched)
            result = {**result, "status": "invalid", "nightly_rate_usd": None, "total_usd": None}
            return result, flags

    # Hard rule 2: nights count preserved
    result_nights = _nights_from_result(result)
    if result_nights is not None and result_nights != expected_nights:
        flags.append(
            f"{platform}: nights mismatch "
            f"(expected={expected_nights}, got={result_nights}) — result stripped"
        )
        log.warning(
            "validation_nights_mismatch",
            platform=platform,
            expected_nights=expected_nights,
            result_nights=result_nights,
        )
        result = {**result, "status": "invalid", "nightly_rate_usd": None, "total_usd": None}
        return result, flags

    # Advisory flags (do not strip)
    level = result.get("fallback_level")
    if level and level >= 5:
        flags.append(f"{platform}: used fallback level {level} — low confidence match")
    elif level and level >= 3:
        flags.append(f"{platform}: used fallback level {level}")

    price_type = result.get("price_type")
    if price_type == "range":
        lo = result.get("nightly_rate_low")
        hi = result.get("nightly_rate_high")
        range_str = f" (${lo}–${hi})" if lo and hi else ""
        flags.append(f"{platform}: price range used{range_str} — midpoint applied")
    elif price_type == "benchmark":
        flags.append(f"{platform}: benchmark price — comparable unit or dates")

    return result, flags


# Weight applied per price_type when scoring confidence.
# verified=1.0 (exact listing), range=0.5 (midpoint used), benchmark=0.25 (approximation)
_PRICE_TYPE_WEIGHT: dict[str, float] = {
    "verified":  1.0,
    "range":     0.5,
    "benchmark": 0.25,
}


def _type_weight(result: dict) -> float:
    return _PRICE_TYPE_WEIGHT.get(result.get("price_type") or "verified", 1.0)


def _score_confidence(valid_results: list[dict]) -> tuple[str, str]:
    """
    Assign HIGH / MEDIUM / LOW weighted by both fallback level and price_type.

    Returns (confidence, reason).
    """
    matched = [r for r in valid_results if r.get("nightly_rate_usd") is not None]
    if not matched:
        return "LOW", "No pricing data found across all platforms"

    levels = [r.get("fallback_level") or 99 for r in matched]
    total_weight = sum(_type_weight(r) for r in matched)
    tight_weight = sum(_type_weight(r) for r, lv in zip(matched, levels) if lv <= 2)
    all_high_fallback = all(lv >= 5 for lv in levels)
    all_benchmark = all(r.get("price_type") == "benchmark" for r in matched)

    if tight_weight >= 3.0:
        return "HIGH", (
            f"Weighted score {tight_weight:.1f} at fallback level ≤2 "
            f"({len(matched)} results)"
        )
    if total_weight >= 2.0 and not all_high_fallback:
        return "MEDIUM", (
            f"Weighted score {total_weight:.1f} across {len(matched)} results "
            f"(fallback levels: {sorted(levels)})"
        )
    if all_benchmark:
        return "LOW", "All results are benchmarks — no verified or range pricing found"
    if all_high_fallback:
        return "LOW", f"All {len(matched)} result(s) at fallback level ≥5"
    return "LOW", f"Weighted score {total_weight:.1f} — insufficient data"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def validate(
    retail_results: list[dict],
    secondary_results: list[dict],
    resolution: dict,
    nights: int,
) -> dict:
    """
    Validate all search results and assign an overall confidence score.

    Args:
        retail_results:    List of per-platform retail result dicts
        secondary_results: List of per-platform secondary/estimate result dicts
        resolution:        Output dict from resolution.resolve()
        nights:            Expected number of nights

    Returns:
        {
            "retail_results":    [validated result dicts],
            "secondary_results": [validated result dicts],
            "confidence":        "HIGH" | "MEDIUM" | "LOW",
            "confidence_reason": str,
            "flags":             [str, ...]
        }
    """
    resolved_unit = resolution.get("display_unit_name") or ""
    all_flags: list[str] = []

    validated_retail = []
    for r in retail_results:
        vr, flags = _validate_result(r, resolved_unit, nights)
        validated_retail.append(vr)
        all_flags.extend(flags)

    validated_secondary = []
    for r in secondary_results:
        vr, flags = _validate_result(r, resolved_unit, nights)
        validated_secondary.append(vr)
        all_flags.extend(flags)

    all_valid = validated_retail + validated_secondary
    confidence, reason = _score_confidence(all_valid)

    log.info(
        "validation_complete",
        confidence=confidence,
        reason=reason,
        flags=all_flags,
        retail_matched=sum(1 for r in validated_retail if r.get("nightly_rate_usd")),
        secondary_matched=sum(1 for r in validated_secondary if r.get("nightly_rate_usd")),
    )

    return {
        "retail_results": validated_retail,
        "secondary_results": validated_secondary,
        "confidence": confidence,
        "confidence_reason": reason,
        "flags": all_flags,
    }
