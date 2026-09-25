"""
Pricing Agent — applies DRA / SMA pricing logic to validated search results.

Calculations:
  retail_average  = mean of all valid retail nightly rates
  DRA             = retail_average × 0.73  (27% discount)
  SMA             = mean of all valid secondary nightly rates
  final_nightly   = min(DRA, SMA)
  price_basis     = "DRA" if DRA ≤ SMA else "SMA"

If only one benchmark is available, that benchmark is used directly.
If neither is available, pricing fails gracefully.
"""

from typing import Optional

import structlog

log = structlog.get_logger()

RETAIL_DISCOUNT = 0.73  # retail average × 0.73 = DRA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_rates(results: list[dict]) -> list[float]:
    """
    Return valid nightly rates, deduplicating by source URL.
    If multiple platforms cite the same URL they found the same data point — count once.
    """
    seen_urls: set = set()
    rates = []
    for r in results:
        if r.get("nightly_rate_usd") is None or r.get("status") == "invalid":
            continue
        url = r.get("source_url") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        rates.append(r["nightly_rate_usd"])
    return rates


def _approximation_note(results: list[dict]) -> tuple[bool, str]:
    """Return (is_approximate, note) based on price_types of results with rates."""
    used = [r for r in results if r.get("nightly_rate_usd") and r.get("status") != "invalid"]
    types = {r.get("price_type", "verified") for r in used}
    if "benchmark" in types:
        return True, "Approximate — benchmark data from comparable properties used"
    if "range" in types:
        return True, "Approximate — price range data used (midpoint applied)"
    return False, ""


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def price(validation_output: dict, nights: int) -> dict:
    """
    Calculate the final suggested nightly rate from validated search results.

    Args:
        validation_output: Output dict from validation.validate()
        nights:            Number of nights in the booking

    Returns:
        {
            "retail_rates_raw":  [float, ...],
            "retail_average_raw": float | None,
            "DRA":               float | None,
            "secondary_rates":   [float, ...],
            "SMA":               float | None,
            "final_nightly_rate": float | None,
            "final_total":       float | None,
            "nights":            int,
            "price_basis":       "DRA" | "SMA" | "DRA_only" | "SMA_only" | "no_data",
            "confidence":        "HIGH" | "MEDIUM" | "LOW",
        }
    """
    all_results = (
        validation_output.get("retail_results", []) +
        validation_output.get("secondary_results", [])
    )
    retail_rates = _extract_rates(validation_output.get("retail_results", []))
    secondary_rates = _extract_rates(validation_output.get("secondary_results", []))
    confidence = validation_output.get("confidence", "LOW")
    is_approximate, approximation_note = _approximation_note(all_results)

    retail_avg = _mean(retail_rates)
    dra = round(retail_avg * RETAIL_DISCOUNT, 2) if retail_avg is not None else None
    sma = _mean(secondary_rates)

    # Determine final rate and basis
    if dra is not None and sma is not None:
        if dra <= sma:
            final_nightly = dra
            basis = "DRA"
        else:
            final_nightly = sma
            basis = "SMA"
    elif dra is not None:
        final_nightly = dra
        basis = "DRA_only"
    elif sma is not None:
        final_nightly = sma
        basis = "SMA_only"
    else:
        final_nightly = None
        basis = "no_data"

    final_total = round(final_nightly * nights, 2) if final_nightly is not None else None

    # Aggregate low/high range across all valid results
    lows  = [r["nightly_rate_low"]  for r in all_results
             if r.get("nightly_rate_low")  and r.get("status") != "invalid"]
    highs = [r["nightly_rate_high"] for r in all_results
             if r.get("nightly_rate_high") and r.get("status") != "invalid"]
    range_low  = min(lows)  if lows  else (round(final_nightly * 0.80, 0) if final_nightly else None)
    range_high = max(highs) if highs else (round(final_nightly * 1.20, 0) if final_nightly else None)

    result = {
        "retail_rates_raw": retail_rates,
        "retail_average_raw": retail_avg,
        "DRA": dra,
        "secondary_rates": secondary_rates,
        "SMA": sma,
        "final_nightly_rate": final_nightly,
        "final_total": final_total,
        "range_low": range_low,
        "range_high": range_high,
        "nights": nights,
        "price_basis": basis,
        "confidence": confidence,
        "is_approximate": is_approximate,
        "approximation_note": approximation_note,
    }

    log.info(
        "pricing_complete",
        retail_count=len(retail_rates),
        secondary_count=len(secondary_rates),
        DRA=dra,
        SMA=sma,
        final_nightly=final_nightly,
        basis=basis,
        confidence=confidence,
    )

    return result
