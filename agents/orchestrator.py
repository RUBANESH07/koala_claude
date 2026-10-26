"""
Orchestrator — coordinates all agents for a single pricing query.

Two entry points:
  run_cached()  — customer-facing; checks cache first, then quick estimate.
                  Always returns fast.
  run()         — quick-price pipeline. Called internally by the background
                  thread that backs run_cached()'s "full" cache slot.

Pipeline flow:
  1. Validate inputs
  2. Resolution Agent  → resolve resort + unit
  3. Quick Price Agent → knowledge-based estimate (claude-sonnet-5)
  4. Validation Agent  → enforce hard rules, score confidence
  5. Pricing Agent     → calculate DRA / SMA / final rate
  6. Output Agent      → format response
"""

import threading
from datetime import datetime

import structlog

from agents.resolution import resolve
from agents.validation import validate
from agents.pricing import price
from agents.output import render, format_failure
from agents.quick_price import quick_price
from agents import cache

log = structlog.get_logger()

_DATE_FMT = "%m/%d/%Y"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _parse_date(s: str, field: str) -> datetime:
    try:
        return datetime.strptime(s.strip(), _DATE_FMT)
    except ValueError:
        raise ValueError(f"Invalid {field} '{s}' — expected MM/DD/YYYY")


def _validate_inputs(
    resort_name: str,
    unit_name: str,
    checkin: str,
    checkout: str,
) -> tuple[datetime, datetime, int]:
    """
    Validate and parse dates. Returns (checkin_dt, checkout_dt, nights).
    Raises ValueError with a user-friendly message on any problem.
    """
    missing = [
        label for label, val in [
            ("resort_name", resort_name),
            ("unit_name", unit_name),
            ("checkin_date", checkin),
            ("checkout_date", checkout),
        ]
        if not val or not val.strip()
    ]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    ci = _parse_date(checkin, "checkin_date")
    co = _parse_date(checkout, "checkout_date")

    if co <= ci:
        raise ValueError(
            f"checkout_date ({checkout}) must be after checkin_date ({checkin})"
        )

    nights = (co - ci).days
    return ci, co, nights


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(
    resort_name: str,
    unit_name: str,
    checkin_date: str,
    checkout_date: str,
    comparable_units: list[dict] | None = None,
) -> str:
    """
    Execute the pricing pipeline for one query (quick-price based).

    Args:
        resort_name:      Raw resort name from user
        unit_name:        Raw unit name from user
        checkin_date:     MM/DD/YYYY
        checkout_date:    MM/DD/YYYY
        comparable_units: Optional sibling unit types at the same resort, each
                           {"id": int, "name": str, "average_listing_price": float|None},
                           used to anchor the estimate so tiers stay logically ordered.

    Returns:
        Formatted pricing string (success or graceful failure).

    Raises:
        ValueError: if required inputs are missing or dates are invalid.
    """
    log.info(
        "orchestrator_start",
        resort=resort_name,
        unit=unit_name,
        checkin=checkin_date,
        checkout=checkout_date,
    )
    return _run_quick(resort_name, unit_name, checkin_date, checkout_date, comparable_units)


# ---------------------------------------------------------------------------
# Quick path — Sonnet knowledge estimate, no web search
# ---------------------------------------------------------------------------

def _run_quick(
    resort_name: str,
    unit_name: str,
    checkin_date: str,
    checkout_date: str,
    comparable_units: list[dict] | None = None,
) -> str:
    """
    Fast pricing path: single Sonnet call using model knowledge (~3–5s).
    Runs through the full validation → pricing → output pipeline so the
    output format is identical to run().
    """
    ci_dt, co_dt, nights = _validate_inputs(
        resort_name, unit_name, checkin_date, checkout_date
    )
    resolution = resolve(resort_name, unit_name)

    result = quick_price(resolution, ci_dt.date(), co_dt.date(), nights, comparable_units)

    if result is None:
        return format_failure(
            resolution=resolution,
            checkin=checkin_date,
            checkout=checkout_date,
            reason="Quick estimate unavailable — please try again.",
        )

    # Route as secondary (SMA) — Haiku already estimates the rental market rate,
    # so the 27% DRA discount should not be applied on top.
    validation = validate([], [result], resolution, nights)
    pricing_out = price(validation, nights)
    return render(resolution, pricing_out, validation, checkin_date, checkout_date)


# ---------------------------------------------------------------------------
# Cached entry point — customer-facing
# ---------------------------------------------------------------------------

def _format_combined(quick: str, full: str) -> str:
    """
    Combine quick estimate and full pipeline results side by side.
    Extracts the Per night line from each for a summary header,
    then shows the full researched result in full.
    """
    def _extract_nightly(output: str) -> str:
        for line in output.splitlines():
            if "Per night:" in line:
                return line.strip()
        return "Per night: —"

    quick_line = _extract_nightly(quick)
    full_line  = _extract_nightly(full)

    return (
        f"╔══ PRICE SUMMARY ════════════════════════════════╗\n"
        f"  Quick estimate : {quick_line.replace('Per night: ', '')}\n"
        f"  Researched     : {full_line.replace('Per night: ', '')}\n"
        f"╚═════════════════════════════════════════════════╝\n\n"
        f"── Researched Result (web search) ──────────────────\n"
        f"{full}\n\n"
        f"── Quick Estimate (knowledge-based) ────────────────\n"
        f"{quick}"
    )


def run_cached(
    resort_name: str,
    unit_name: str,
    checkin_date: str,
    checkout_date: str,
    comparable_units: list[dict] | None = None,
) -> str:
    """
    Customer-facing entry point. Always returns quickly.

    Args:
        comparable_units: Optional sibling unit types at the same resort, each
                           {"id": int, "name": str, "average_listing_price": float|None}.

    Flow:
      1. Cache hit with both results → return combined quick + full view
      2. Cache hit with quick only   → return quick, note full still pending
      3. Cache miss → run quick estimate (~3–5s), fire background full pipeline
    """
    # Step 1 — cache check
    cached = cache.get(resort_name, unit_name, checkin_date, checkout_date)
    if cached:
        quick = cached.get("quick_result", "")
        full  = cached.get("full_result", "")
        if quick and full:
            return _format_combined(quick, full)
        if quick:
            return quick + "\n\n[Full researched price still running in background — check back shortly]"
        if full:
            return full + "\n[cached]"

    # Step 2 — quick estimate
    log.info("run_cached_quick_start", resort=resort_name, unit=unit_name)
    result = _run_quick(resort_name, unit_name, checkin_date, checkout_date, comparable_units)
    cache.put(resort_name, unit_name, checkin_date, checkout_date, result, mode="quick")

    # Step 3 — background full pipeline
    def _background() -> None:
        log.info("background_pipeline_start", resort=resort_name, unit=unit_name)
        try:
            full_result = run(resort_name, unit_name, checkin_date, checkout_date, comparable_units)
            cache.put(resort_name, unit_name, checkin_date, checkout_date,
                      full_result, mode="full")
            log.info("background_pipeline_done", resort=resort_name)
        except Exception as exc:
            log.warning("background_pipeline_error", error=str(exc))

    threading.Thread(target=_background, daemon=True).start()

    return result + "\n\n[Full researched price running in background — re-query to see both]"
