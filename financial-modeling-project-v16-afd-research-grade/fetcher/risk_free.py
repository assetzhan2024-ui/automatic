"""Automatic USD risk-free-rate provider.

The portfolio engine is USD-based. For Sharpe / maximum-Sharpe optimization we
use the current 13-week U.S. Treasury bill yield as the USD risk-free proxy.
The live value is refreshed from Yahoo Finance ticker ``^IRX`` and cached on
disk for only 30 minutes, so changes are picked up automatically without a manual yearly update. If the live provider is temporarily unavailable, the last successful
cached value is used. A dated seed fallback is shipped only so the application
can remain usable during a first-run outage; it is explicitly marked stale.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

try:
    import yfinance as yf
except ImportError:
    yf = None

from fetcher.session import SESSION as _SESSION

_TTL_SECONDS = 30 * 60
_LOCK = threading.RLock()
_CACHE_FILE = Path(__file__).resolve().parents[1] / "cache" / "usd_risk_free.json"
# Official U.S. Treasury daily bill table, 2026-08-25: 13-week coupon-equivalent
# rate = 3.72%. Used only if there has never been a successful live fetch.
_SEED = {
    "rate_pct": 3.72,
    "as_of": "2026-08-25",
    "source": "U.S. Treasury daily bill rates (seed fallback)",
    "instrument": "13-week U.S. Treasury bill",
    "stale": True,
}


def _read_cache() -> dict | None:
    try:
        if not _CACHE_FILE.exists():
            return None
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        rate = float(data.get("rate_pct"))
        if rate < -5 or rate > 30:
            return None
        return data
    except Exception:
        return None


def _write_cache(payload: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_usd_risk_free_rate(*, force_refresh: bool = False) -> dict:
    """Return current USD risk-free proxy metadata.

    Output keys: ``rate_pct``, ``as_of``, ``source``, ``instrument``, ``stale``.
    ``rate_pct`` is an annual percentage, e.g. ``3.72``.
    """
    with _LOCK:
        cached = _read_cache()
        if cached and not force_refresh:
            fetched_ts = float(cached.get("fetched_ts", 0) or 0)
            if fetched_ts and time.time() - fetched_ts < _TTL_SECONDS:
                out = dict(cached)
                out["stale"] = False
                return out

        if yf is not None:
            try:
                obj = yf.Ticker("^IRX", session=_SESSION) if _SESSION else yf.Ticker("^IRX")
                hist = obj.history(period="7d", interval="1d", auto_adjust=False)
                close = hist["Close"].dropna()
                if not close.empty:
                    rate = float(close.iloc[-1])
                    if -5.0 < rate < 30.0:
                        idx = close.index[-1]
                        try:
                            as_of = idx.date().isoformat()
                        except Exception:
                            as_of = datetime.now(timezone.utc).date().isoformat()
                        payload = {
                            "rate_pct": rate,
                            "as_of": as_of,
                            "source": "Yahoo Finance ^IRX",
                            "instrument": "13-week U.S. Treasury bill",
                            "stale": False,
                            "fetched_ts": time.time(),
                        }
                        _write_cache(payload)
                        return payload
            except Exception:
                pass

        if cached:
            out = dict(cached)
            out["stale"] = True
            out["source"] = str(out.get("source") or "cached USD risk-free rate") + " (cached)"
            return out
        return dict(_SEED)
