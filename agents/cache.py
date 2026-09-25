"""
Price cache — stores rendered pricing results with 24h TTL.

Cache file: data/price_cache.json
Cache key:  resort + unit + checkin + checkout (exact match)
TTL:        24 hours

Each entry stores quick_result and full_result independently so both
are available for display. put() never erases the other mode's result.
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "price_cache.json"
TTL_HOURS = 24

_lock = threading.Lock()


def _make_key(resort: str, unit: str, checkin: str, checkout: str) -> str:
    """Normalize query components into a stable cache key."""
    def norm(s: str) -> str:
        return s.lower().strip().replace(" ", "_")
    return f"{norm(resort)}__{norm(unit)}__{checkin}__{checkout}"


def _load() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def get(resort: str, unit: str, checkin: str, checkout: str) -> Optional[dict]:
    """
    Return cached entry if present and not expired.

    Returns dict with keys:
        quick_result  — fast knowledge estimate (always set first)
        full_result   — web-search pipeline result (set when background completes)
        cached_at     — ISO timestamp of first write
        expires_at    — ISO timestamp of expiry
    Returns None on miss or expiry.
    """
    key = _make_key(resort, unit, checkin, checkout)
    with _lock:
        data = _load()
    entry = data.get(key)
    if not entry:
        return None
    if datetime.now() > datetime.fromisoformat(entry["expires_at"]):
        log.info("cache_expired", key=key)
        return None
    log.info("cache_hit", key=key,
             has_full=bool(entry.get("full_result")))
    return entry


def put(
    resort: str,
    unit: str,
    checkin: str,
    checkout: str,
    result: str,
    mode: str,          # "quick" or "full"
) -> None:
    """
    Write a rendered result string to the cache under quick_result or full_result.
    Never erases the other mode's result.
    """
    key = _make_key(resort, unit, checkin, checkout)
    now = datetime.now()
    with _lock:
        data = _load()
        entry = data.get(key, {
            "cached_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=TTL_HOURS)).isoformat(),
            "quick_result": None,
            "full_result": None,
        })
        if mode == "quick":
            entry["quick_result"] = result
        else:
            entry["full_result"] = result
        data[key] = entry
        _save(data)
    log.info("cache_write", key=key, mode=mode)
