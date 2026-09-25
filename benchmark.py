"""
benchmark.py — Run the full pricing pipeline for all 9 benchmark cases sequentially.

Prints progress after each case and saves results to data/benchmark_results.json.
Run time per case is tracked and included in output.

Usage:
    python3 benchmark.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

from agents.orchestrator import run

RESULTS_FILE = Path("data/benchmark_results.json")

CASES = [
    {
        "num": 1,
        "resort": "Sunrise Lodge, a Hilton Grand Vacations Club",
        "unit": "1 Bedroom Premier (1BX)",
        "checkin": "12/19/2026",
        "checkout": "12/26/2026",
        "myles": 200,
        "user_price": 425,
        "price_iq": 390,
        "quick": 525,
        "hist_avg": None,
    },
    {
        "num": 2,
        "resort": "Club Wyndham Bonnet Creek",
        "unit": "1 Bedroom Presidential",
        "checkin": "04/23/2026",
        "checkout": "04/25/2026",
        "myles": 250,
        "user_price": 250,
        "price_iq": 160,
        "quick": 210,
        "hist_avg": 149,
    },
    {
        "num": 3,
        "resort": "Club Wyndham Bonnet Creek",
        "unit": "2 Bedroom Deluxe",
        "checkin": "06/20/2026",
        "checkout": "06/27/2026",
        "myles": 250,
        "user_price": 400,
        "price_iq": 275,
        "quick": 280,
        "hist_avg": 257,
    },
    {
        "num": 4,
        "resort": "Sunrise Lodge, a Hilton Grand Vacations Club",
        "unit": "2 Bedroom Plus (2LK)",
        "checkin": "01/11/2027",
        "checkout": "01/18/2027",
        "myles": 243,
        "user_price": None,
        "price_iq": 316,
        "quick": 475,
        "hist_avg": None,
    },
    {
        "num": 5,
        "resort": "Marriott's Aruba Surf Club",
        "unit": "2 Bedroom Ocean View",
        "checkin": "02/28/2027",
        "checkout": "03/04/2027",
        "myles": 450,
        "user_price": 571,
        "price_iq": 666,
        "quick": 625,
        "hist_avg": 877,
    },
    {
        "num": 6,
        "resort": "Marriott's Aruba Surf Club",
        "unit": "3 Bedroom Ocean View",
        "checkin": "02/13/2027",
        "checkout": "02/20/2027",
        "myles": 450,
        "user_price": 2271,
        "price_iq": 994,
        "quick": 850,
        "hist_avg": None,
    },
    {
        "num": 7,
        "resort": "Marriott's Aruba Surf Club",
        "unit": "2 Bedroom Ocean View",
        "checkin": "02/14/2027",
        "checkout": "02/21/2027",
        "myles": 450,
        "user_price": 1114,
        "price_iq": 692,
        "quick": 1114,
        "hist_avg": 877,
    },
    {
        "num": 8,
        "resort": "Marriott's Grand Chateau",
        "unit": "1 Bedroom Villa",
        "checkin": "05/15/2026",
        "checkout": "05/18/2026",
        "myles": 200,
        "user_price": 333,
        "price_iq": 238,
        "quick": 275,
        "hist_avg": None,
        "researched": 315,   # already captured
        "run_time_s": None,
    },
    {
        "num": 9,
        "resort": "Marriott's Grand Chateau",
        "unit": "2 Bedroom Villa",
        "checkin": "05/23/2026",
        "checkout": "05/25/2026",
        "myles": 210,
        "user_price": 260,
        "price_iq": 380,
        "quick": 375,
        "hist_avg": 396,
    },
]


def _extract_nightly(output: str):
    for line in output.splitlines():
        if "Per night:" in line:
            # e.g. "  Per night: ~$314.75"
            import re
            m = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", line)
            if m:
                return float(m.group(1).replace(",", ""))
    return None


def _fmt_dollars(v) -> str:
    if v is None:
        return "—"
    return f"${v:,.0f}"


def _fmt_run_time(s) -> str:
    if s is None:
        return "—"
    return f"{s:.0f}s"


def run_all() -> list[dict]:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for case in CASES:
        n = case["num"]

        # Case 8 already has a researched price
        if case.get("researched") is not None:
            print(f"  Case {n}: {case['resort']} | {case['unit']}")
            print(f"  ✓ Already captured: ${case['researched']:.0f}/night\n")
            result = {**case, "run_time_s": case.get("run_time_s")}
            results.append(result)
            RESULTS_FILE.write_text(json.dumps(results, indent=2))
            continue

        print(f"  Case {n}: {case['resort']} | {case['unit']} | {case['checkin']}–{case['checkout']}")
        print(f"  Running full pipeline...", end=" ", flush=True)

        t0 = time.time()
        try:
            output = run(case["resort"], case["unit"], case["checkin"], case["checkout"])
            elapsed = time.time() - t0
            nightly = _extract_nightly(output)
            if nightly:
                print(f"✓ ${nightly:,.0f}/night ({elapsed:.0f}s)")
            else:
                print(f"⚠ No price found ({elapsed:.0f}s)")
                nightly = None
        except Exception as exc:
            elapsed = time.time() - t0
            print(f"✗ Error: {exc} ({elapsed:.0f}s)")
            nightly = None

        result = {**case, "researched": nightly, "run_time_s": round(elapsed)}
        results.append(result)
        RESULTS_FILE.write_text(json.dumps(results, indent=2))
        print()

    return results


def print_table(results: list[dict]) -> None:
    print("\n" + "=" * 100)
    print("BENCHMARK RESULTS")
    print("=" * 100)
    header = f"{'#':>2}  {'Resort':<35} {'Unit':<25} {'Dates':<20} {'Myles':>6} {'User':>6} {'PriceIQ':>8} {'Quick':>7} {'Researched':>11} {'Time':>6} {'Hist.Avg':>9}"
    print(header)
    print("-" * 100)
    for r in results:
        dates = f"{r['checkin']}–{r['checkout']}"
        print(
            f"{r['num']:>2}  {r['resort']:<35} {r['unit']:<25} {dates:<20} "
            f"{_fmt_dollars(r['myles']):>6} {_fmt_dollars(r.get('user_price')):>6} "
            f"{_fmt_dollars(r['price_iq']):>8} {_fmt_dollars(r['quick']):>7} "
            f"{_fmt_dollars(r.get('researched')):>11} {_fmt_run_time(r.get('run_time_s')):>6} "
            f"{_fmt_dollars(r.get('hist_avg')):>9}"
        )
    print("=" * 100)


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"Pricing Wizard — Full Pipeline Benchmark")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cases: {len(CASES)} | Running sequentially")
    print(f"{'='*60}\n")

    results = run_all()
    print_table(results)

    print(f"\nResults saved to {RESULTS_FILE}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
