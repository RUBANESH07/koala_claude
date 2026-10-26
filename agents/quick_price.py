"""
Quick Price Agent — single Haiku call, no web_search.

Returns a knowledge-based benchmark estimate in ~3-5 seconds.
Used as the fast path in run_cached(); the full pipeline runs in background.
Confidence is always LOW — this is a knowledge estimate, not a verified price.
"""

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic
import structlog
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

log = structlog.get_logger()


def _fmt(d: date) -> str:
    return d.strftime("%m/%d/%Y")


_SYSTEM_PROMPT = (
    "You are a vacation rental pricing expert specialising in premium vacation ownership "
    "resorts — Marriott Vacation Club, Hilton Grand Vacations, Club Wyndham, Hyatt "
    "Residence Club, and similar brands. These properties command significantly higher "
    "nightly rates than standard vacation rentals due to brand, amenities, and location. "
    "Provide realistic market-rate estimates based on your knowledge. "
    "Output ONLY a JSON object — no prose, no markdown, no explanation."
)

_RESULT_SCHEMA = (
    '{"found": bool, "price_per_night": number|null, '
    '"price_low": number|null, "price_high": number|null, "notes": string}'
)


def _format_comparable_units(unit_name: str, comparable_units: Optional[list[dict]]) -> str:
    """
    Build a prompt section anchoring the estimate to known average prices for
    sibling unit types at the same resort, so tiers stay logically ordered
    (e.g. a plain "3 Bedroom" should not price above "3 Bedroom Deluxe").

    Each entry's `average_listing_price` may be null (no data yet) or a number —
    both are accepted; null entries are listed as "no data" rather than skipped,
    so the model still knows that tier exists.
    """
    if not comparable_units:
        return ""

    lines = []
    for u in comparable_units:
        name = (u.get("name") or "").strip()
        if not name or name.lower() == unit_name.lower():
            continue
        avg = u.get("average_listing_price")
        price_str = f"${avg:,.2f}/night avg" if isinstance(avg, (int, float)) else "no data"
        lines.append(f"  - {name}: {price_str}")

    if not lines:
        return ""

    return (
        "\n\nOther unit types at this same resort and their known average listing "
        "prices (use these as anchors — your estimate MUST stay logically consistent "
        "with them: higher-tier names like 'Deluxe', 'Presidential', or 'Suite' should "
        "price at or above comparable plain/standard units of the same bedroom count, "
        "and larger bedroom counts should generally price above smaller ones):\n"
        + "\n".join(lines)
    )


def quick_price(
    resolution: dict,
    checkin: date,
    checkout: date,
    nights: int,
    comparable_units: Optional[list[dict]] = None,
) -> Optional[dict]:
    """
    Single Haiku call (no web_search) for a fast knowledge-based price estimate.

    Args:
        comparable_units: Optional list of sibling unit types at the same resort,
            each like {"id": int, "name": str, "average_listing_price": float|None}.
            Used to anchor the estimate so tiers stay logically ordered.

    Returns a platform result dict compatible with validation.validate() and
    pricing.price(), or None if the estimate fails.
    """
    resort = resolution["display_resort_name"]
    unit = resolution["display_unit_name"]
    bedroom_tier = resolution.get("bedroom_tier") or unit
    view_class = resolution.get("view_class") or ""
    # Build a full unit label that includes view type for accurate pricing
    unit_label = f"{bedroom_tier} {view_class}".strip() if view_class else bedroom_tier
    month_name = checkin.strftime("%B")
    year = checkin.year

    # Classify season and detect high-demand holiday weeks
    peak_months = {1, 2, 3, 7, 8, 12}
    season = "peak" if checkin.month in peak_months else "shoulder"

    # Detect specific high-demand weeks that command a significant premium
    from datetime import timedelta as _td
    _holiday_weeks = []
    # Valentine's week (Feb 10–17)
    if checkin.month == 2 and 10 <= checkin.day <= 17:
        _holiday_weeks.append("Valentine's week")
    # Presidents' Day week (mid-Feb)
    if checkin.month == 2 and 14 <= checkin.day <= 21:
        _holiday_weeks.append("Presidents' Day week")
    # Spring Break (mid-March to mid-April)
    if (checkin.month == 3 and checkin.day >= 14) or (checkin.month == 4 and checkin.day <= 21):
        _holiday_weeks.append("Spring Break")
    # Thanksgiving week
    if checkin.month == 11 and 20 <= checkin.day <= 30:
        _holiday_weeks.append("Thanksgiving week")
    # Christmas/New Year
    if checkin.month == 12 and checkin.day >= 20:
        _holiday_weeks.append("Christmas/New Year week")
    if checkin.month == 1 and checkin.day <= 7:
        _holiday_weeks.append("New Year week")
    # 4th of July
    if checkin.month == 7 and 1 <= checkin.day <= 7:
        _holiday_weeks.append("4th of July week")

    holiday_note = (
        f" This query falls on a HIGH-DEMAND holiday period: {', '.join(_holiday_weeks)}. "
        f"Prices during these weeks are typically 40–80% above standard peak rates."
        if _holiday_weeks else ""
    )

    view_note = (
        f" Note: '{view_class}' units carry a significant premium over standard units "
        f"at this resort — factor this into your estimate."
        if view_class else ""
    )

    holiday_section = (
        f"\n*** HIGH-DEMAND HOLIDAY PERIOD: {', '.join(_holiday_weeks)} ***\n"
        f"Rental prices during this period are SIGNIFICANTLY elevated — typically "
        f"40–80% above standard peak-season rates. A unit that normally rents for "
        f"$600–$800/night may command $900–$1,400+/night during this week. "
        f"Do NOT use standard peak-season pricing — use holiday-week pricing.\n"
        if _holiday_weeks else ""
    )

    prompt = (
        f"Estimate the nightly rental rate on the secondary market (owner-to-renter) for:\n"
        f"  Resort: {resort}\n"
        f"  Unit:   {unit_label}\n"
        f"  Dates:  {checkin.strftime('%b %d')} – {checkout.strftime('%b %d, %Y')} ({month_name}, {season} season)\n"
        f"{holiday_section}\n"
        f"This is a premium vacation ownership property (Marriott Vacation Club, "
        f"Hilton Grand Vacations, Club Wyndham, or similar brand). "
        f"Secondary market rental rates for these properties are typically "
        f"$300–$1,500+/night depending on brand, unit size, view, and location.{view_note}\n\n"
        f"Use your knowledge of this specific resort if available. "
        f"If not, estimate based on comparable premium vacation club properties "
        f"in the same destination, unit size, view type, and season.\n\n"
        f"Provide a realistic price_low and price_high range reflecting actual "
        f"secondary market rental prices. Set price_per_night to the midpoint. "
        f"Always return found=true with an estimate."
        f"{_format_comparable_units(unit, comparable_units)}\n\n"
        f"Return this JSON only:\n{_RESULT_SCHEMA}"
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("quick_price_api_error", error=str(exc))
        return None

    if hasattr(response, "usage"):
        u = response.usage
        log.info(
            "quick_price_tokens",
            input_tokens=getattr(u, "input_tokens", None),
            output_tokens=getattr(u, "output_tokens", None),
        )

    for block in response.content:
        if hasattr(block, "text"):
            text = re.sub(r"```(?:json)?", "", block.text).strip()
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    raw = json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue

                nightly = raw.get("price_per_night")
                # Accept any result with a price — Haiku sometimes sets found=false
                # out of caution even when it provides a useful estimate
                if nightly:
                    log.info("quick_price_result", resort=resort, unit=unit,
                             nightly=nightly, month=month_name)
                    return {
                        "platform": "Estimate",
                        "status": "fallback",
                        "fallback_level": 3,
                        "price_type": "benchmark",
                        "resort_matched": resort,
                        "unit_matched": bedroom_tier,
                        "dates_matched": f"{_fmt(checkin)}–{_fmt(checkout)}",
                        "nightly_rate_usd": nightly,
                        "nightly_rate_low": raw.get("price_low"),
                        "nightly_rate_high": raw.get("price_high"),
                        "total_usd": round(nightly * nights, 2),
                        "source_url": None,
                        "notes": raw.get("notes", "Knowledge-based estimate"),
                    }

    log.warning("quick_price_no_result", resort=resort, unit=unit)
    return None
