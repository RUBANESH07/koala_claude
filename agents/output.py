"""
Output Agent — formats the final pricing response.

Two output modes:
  format_success()  — standard priced response
  format_failure()  — graceful failure when pricing is not possible

No commentary or rationale is added beyond what the spec defines.
"""

from datetime import datetime
from typing import Optional

def _holiday_name(checkin_str: str) -> str:
    """Return a short holiday name if checkin falls on a high-demand week, else ''."""
    try:
        ci = datetime.strptime(checkin_str, "%m/%d/%Y")
    except ValueError:
        return ""
    m, d = ci.month, ci.day
    if (m == 12 and d >= 19) or (m == 1 and d <= 7):
        return "Christmas & New Year week"
    if m == 2 and 10 <= d <= 21:
        return "Valentine's week"
    if (m == 3 and d >= 14) or (m == 4 and d <= 21):
        return "Spring Break"
    if m == 11 and 20 <= d <= 30:
        return "Thanksgiving week"
    if m == 7 and 1 <= d <= 7:
        return "4th of July week"
    return ""


def _sentiment_label(checkin_str: str) -> str:
    """Derive a price sentiment label from the check-in date."""
    try:
        ci = datetime.strptime(checkin_str, "%m/%d/%Y")
    except ValueError:
        return "FAIR MARKET"
    m, d = ci.month, ci.day
    if (m == 12 and d >= 19) or (m == 1 and d <= 7):
        return "PEAK / HOLIDAY — Holiday premium applies"
    if m == 2 and 10 <= d <= 21:
        return "PEAK / HOLIDAY — Holiday premium applies"
    if (m == 3 and d >= 14) or (m == 4 and d <= 21):
        return "PEAK / HOLIDAY — Holiday premium applies"
    if m == 11 and 20 <= d <= 30:
        return "PEAK / HOLIDAY — Holiday premium applies"
    if m == 7 and 1 <= d <= 7:
        return "PEAK / HOLIDAY — Holiday premium applies"
    if m in {1, 2, 3, 7, 8, 12}:
        return "STRONG DEMAND — Peak season"
    if m in {4, 5, 9, 10}:
        return "FAIR MARKET — Shoulder season"
    return "SOFT MARKET — Off-peak"


def _confidence_note(pricing: dict) -> str:
    """Return a human-readable confidence note including source type."""
    level = pricing.get("confidence", "LOW")
    basis = pricing.get("price_basis", "no_data")
    is_approx = pricing.get("is_approximate", False)
    if level == "HIGH":
        return "HIGH (verified listing — exact unit & dates)"
    if level == "MEDIUM":
        return "MEDIUM (price range from comparable listings)"
    # LOW
    if is_approx and "benchmark" in pricing.get("approximation_note", ""):
        return "LOW (knowledge-based estimate)"
    if is_approx:
        return "LOW (price range data — midpoint applied)"
    if basis in ("DRA_only", "SMA_only"):
        return "LOW (single platform benchmark)"
    return "LOW"


_BASIS_LABEL = {
    "DRA":      "Discounted Retail Average (lower of two)",
    "SMA":      "Secondary Market Average (lower of two)",
    "DRA_only": "Discounted Retail Average (only benchmark available)",
    "SMA_only": "Secondary Market Average (only benchmark available)",
    "no_data":  "N/A",
}

_LEVEL_LABEL = {
    1: "Level 1 match",
    2: "Level 2 match",
    3: "Level 3 match",
    4: "Level 4 match",
    5: "Level 5 match",
    6: "Level 6 match",
}


def _money(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


_PRICE_TYPE_TAG = {
    "verified":  "",
    "range":     " [range]",
    "benchmark": " [benchmark]",
}


def _result_line(result: dict, indent: str = "    ") -> str:
    """Format one platform result as a single display line."""
    platform = result.get("platform", "Unknown")
    status = result.get("status", "no_match")

    if status in ("no_match", "invalid") or not result.get("nightly_rate_usd"):
        return f"{indent}No match: {platform}"

    level = result.get("fallback_level", 1)
    label = _LEVEL_LABEL.get(level, f"Level {level} match")
    resort = result.get("resort_matched", "")
    unit = result.get("unit_matched", "")
    dates = result.get("dates_matched", "")
    url = result.get("source_url") or "—"
    price_type = result.get("price_type") or "verified"
    tag = _PRICE_TYPE_TAG.get(price_type, f" [{price_type}]")

    # Append range if available
    lo = result.get("nightly_rate_low")
    hi = result.get("nightly_rate_high")
    if price_type == "range" and lo and hi:
        tag = f" [range: ${lo:,.0f}–${hi:,.0f}]"

    # Shorten dates from MM/DD/YYYY–MM/DD/YYYY to MM/DD–MM/DD
    short_dates = dates
    if "–" in dates:
        parts = dates.split("–")
        if len(parts) == 2:
            short_dates = "–".join(p[:-5] if len(p) == 10 else p for p in parts)

    line1 = f"{indent}{label}: {resort} – {unit}{tag}"
    line2 = f"{indent}           {short_dates} ({platform} – {url})"
    return f"{line1}\n{line2}"


def _retail_header(pricing: dict) -> str:
    avg = pricing.get("retail_average_raw")
    dra = pricing.get("DRA")
    if avg is None:
        return "  Retail Benchmark\n  (no data):"
    return (
        f"  Retail Benchmark\n"
        f"  (avg {_money(avg)}/night raw → {_money(dra)}/night after 27% discount):"
    )


def _secondary_header(pricing: dict) -> str:
    sma = pricing.get("SMA")
    if sma is None:
        return "  Secondary Market Benchmark\n  (no data):"
    return (
        f"  Secondary Market Benchmark\n"
        f"  (avg {_money(sma)}/night, no discount applied):"
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def format_success(
    resolution: dict,
    pricing: dict,
    checkin: str,
    checkout: str,
) -> str:
    """
    Render the standard priced output.

    Args:
        resolution:  Output from resolution.resolve()
        pricing:     Output from pricing.price()
        checkin:     Check-in date string MM/DD/YYYY
        checkout:    Check-out date string MM/DD/YYYY

    Returns:
        Formatted multi-line string.
    """
    resort = resolution.get("display_resort_name", resolution.get("raw_resort", "Unknown"))
    unit = resolution.get("display_unit_name", resolution.get("raw_unit", "Unknown"))
    nights = pricing["nights"]
    nightly = pricing["final_nightly_rate"]
    total = pricing["final_total"]
    confidence = pricing["confidence"]
    basis = _BASIS_LABEL.get(pricing.get("price_basis", "no_data"), "N/A")

    retail_results = pricing.get("_retail_results", [])
    secondary_results = pricing.get("_secondary_results", [])

    is_approx  = pricing.get("is_approximate", False)
    range_low  = pricing.get("range_low")
    range_high = pricing.get("range_high")
    sentiment  = pricing.get("_sentiment", "")
    holiday    = pricing.get("_holiday", "")
    conf_note  = _confidence_note(pricing)

    # Date range line — "May 15–18 2026" or "Feb 14–21 2027 (Valentine's week)"
    try:
        ci_dt = datetime.strptime(checkin, "%m/%d/%Y")
        co_dt = datetime.strptime(checkout, "%m/%d/%Y")
        if ci_dt.month == co_dt.month and ci_dt.year == co_dt.year:
            date_range = f"{ci_dt.strftime('%b %d')}–{co_dt.strftime('%d %Y')}"
        else:
            date_range = f"{ci_dt.strftime('%b %d')} – {co_dt.strftime('%b %d %Y')}"
    except ValueError:
        date_range = f"{checkin}–{checkout}"
    if holiday:
        date_range = f"{date_range} ({holiday})"

    # Range and midpoint
    prefix = "~" if is_approx else ""
    if range_low and range_high:
        range_str = f"{prefix}${range_low:,.0f} – {prefix}${range_high:,.0f} / night"
    else:
        range_str = "—"
    midpoint_str = f"{prefix}{_money(nightly)} / night"
    total_str    = f"{prefix}{_money(total)} ({nights} nights)"

    # Header block matching Confluence doc format
    lines = [
        f"{resort} — {unit}",
        date_range,
        "",
        f"  Price sentiment:  {sentiment}",
        f"  Range:            {range_str}",
        f"  Midpoint:         {midpoint_str}",
        f"  Total:            {total_str}",
        f"  Confidence:       {conf_note}",
    ]
    lines += [
        "",
        "Source Validation:",
        "",
        _retail_header(pricing),
    ]
    for r in retail_results:
        lines.append(_result_line(r))

    lines += [
        "",
        _secondary_header(pricing),
    ]
    for r in secondary_results:
        lines.append(_result_line(r))

    lines += [
        "",
        f"  Final price derived from: {basis}",
    ]

    return "\n".join(lines)


def format_failure(
    resolution: dict,
    checkin: str,
    checkout: str,
    reason: str = "Fewer than 2 verified results found across all platforms after full fallback sequence.",
) -> str:
    """
    Render the graceful failure output.

    Args:
        resolution:  Output from resolution.resolve()
        checkin:     Check-in date string MM/DD/YYYY
        checkout:    Check-out date string MM/DD/YYYY
        reason:      Explanation string

    Returns:
        Formatted multi-line string.
    """
    resort = resolution.get("display_resort_name", resolution.get("raw_resort", "Unknown"))
    unit = resolution.get("display_unit_name", resolution.get("raw_unit", "Unknown"))

    # Wrap reason at ~60 chars preserving the indent
    words = reason.split()
    wrapped, line = [], []
    for word in words:
        line.append(word)
        if len(" ".join(line)) >= 58:
            wrapped.append("        " + " ".join(line))
            line = []
    if line:
        wrapped.append("        " + " ".join(line))
    reason_block = "\n".join(wrapped)

    return (
        f"Unable to price: {resort} — {unit}\n"
        f"                 {checkin}–{checkout}\n"
        f"\n"
        f"Reason: {reason_block.strip()}\n"
        f"\n"
        f"Suggested action: Try alternative dates or request manual review."
    )


def render(
    resolution: dict,
    pricing: dict,
    validation: dict,
    checkin: str,
    checkout: str,
) -> str:
    """
    Top-level render function. Chooses success or failure format automatically.

    Attaches retail/secondary results from validation onto the pricing dict
    so format_success() can render the source table.
    """
    if pricing.get("final_nightly_rate") is None:
        return format_failure(resolution, checkin, checkout)

    # Attach result lists, sentiment and holiday label for the source table
    enriched = {
        **pricing,
        "_retail_results": validation.get("retail_results", []),
        "_secondary_results": validation.get("secondary_results", []),
        "_sentiment": _sentiment_label(checkin),
        "_holiday": _holiday_name(checkin),
    }
    return format_success(resolution, enriched, checkin, checkout)
