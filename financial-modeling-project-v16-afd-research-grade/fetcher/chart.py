"""
fetcher/chart.py
================
Получение годовых дневных цен закрытия для sparkline-графика.

Публичный API:
    fetch_chart(symbol: str) → dict
    fetch_history(symbol: str, period: str = "3y") → dict
    fetch_history_range(symbol: str, start: str, end: str) → dict
        {ticker, dates, closes, min_close, max_close}
        или {error: "no_data", ticker, dates: [], closes: []}
    clear_chart_cache()     — принудительно сбросить кеш

Кеш в памяти с TTL 1 час — не нужны свежие данные чаще.
"""

import threading
import time
import math

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance pandas")

from config.kase import kase_candidates
from fetcher.session import SESSION as _SESSION

CHART_TTL = 3600  # секунд

_chart_cache: dict = {}
_chart_lock = threading.Lock()


def clear_chart_cache() -> None:
    """Принудительно очистить кеш исторических котировок."""
    with _chart_lock:
        _chart_cache.clear()


def _clean_history_close(hist):
    """Return a strictly-positive finite Close series with valid dates only."""
    import pandas as pd
    if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
        return pd.Series(dtype="float64")
    close = pd.to_numeric(hist["Close"], errors="coerce")
    close = close.replace([float("inf"), float("-inf")], float("nan")).dropna()
    close = close[close > 0]
    close = close[~close.index.duplicated(keep="last")].sort_index()
    return close


def _clean_pairs(dates, closes):
    """Sanitize provider/fallback date-close pairs; never turn missing into zero."""
    import pandas as pd
    out=[]
    for d,v in zip(dates or [], closes or []):
        dt=pd.to_datetime(d, errors="coerce")
        try: fv=float(v)
        except Exception: continue
        if pd.isna(dt) or not math.isfinite(fv) or fv <= 0:
            continue
        out.append((dt, fv))
    dedup={str(d.date()):(d,v) for d,v in out}
    return [dedup[k] for k in sorted(dedup)]


def _coverage_meta(dates) -> dict:
    import pandas as pd
    idx = pd.to_datetime(list(dates or []), errors="coerce")
    idx = idx[~pd.isna(idx)]
    if len(idx) < 2:
        return {"observations": int(len(idx)), "coverage_days": 0, "first_date": None, "last_date": None, "full_52w": False}
    first, last = idx.min(), idx.max()
    days = int((last-first).days)
    # Exchange holidays and IPOs mean observation count varies. Calendar
    # coverage is the primary guard against presenting a short fallback series
    # as a 52-week range.
    return {"observations": int(len(idx)), "coverage_days": days, "first_date": str(first.date()), "last_date": str(last.date()), "full_52w": bool(days >= 300 and len(idx) >= 150)}

def fetch_history(symbol: str, period: str = "3y") -> dict:
    """Return adjusted daily closes for a configurable Yahoo period.

    Portfolio analytics use 3y by default.  The existing one-year sparkline
    API remains unchanged via :func:`fetch_chart`.
    """
    sym_up = symbol.upper()
    cache_key = f"{sym_up}|{period}"
    with _chart_lock:
        cached = _chart_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < CHART_TTL:
            return cached["data"]

    is_kase = sym_up.endswith(".KZ")
    candidates = kase_candidates(symbol) if is_kase else [symbol]
    hist = None
    for cand in candidates:
        try:
            ticker_obj = yf.Ticker(cand, session=_SESSION) if _SESSION else yf.Ticker(cand)
            h = ticker_obj.history(period=period, interval="1d", auto_adjust=True, timeout=10)
            if not h.empty:
                hist = h
                break
        except Exception:
            continue

    if hist is None or hist.empty:
        # KASE fallback currently exposes approximately one year.  It is still
        # returned; the portfolio layer decides whether there are enough
        # observations for a statistically meaningful optimisation.
        if is_kase:
            try:
                from fetcher.kase_fetcher import fetch_kase_chart
                raw = fetch_kase_chart(symbol)
                pairs = _clean_pairs(raw.get("dates"), raw.get("closes"))
                if len(pairs) < 2:
                    raise ValueError("KASE fallback returned no valid positive closes")
                closes = [round(v, 6) for _,v in pairs]
                dates_clean=[str(d.date()) for d,_ in pairs]
                data = {**raw, "dates":dates_clean, "closes":closes, "min_close":min(closes), "max_close":max(closes), **_coverage_meta(dates_clean)}
                with _chart_lock:
                    _chart_cache[cache_key] = {"data": data, "ts": time.time()}
                return data
            except Exception:
                pass
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": []}

    close = _clean_history_close(hist)
    if len(close) < 2:
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": []}
    closes = [round(float(v), 6) for v in close]
    dates = [str(d.date()) for d in close.index]
    data = {
        "ticker": symbol, "dates": dates, "closes": closes,
        "min_close": min(closes), "max_close": max(closes), "period": period,
        **_coverage_meta(dates),
    }
    with _chart_lock:
        _chart_cache[cache_key] = {"data": data, "ts": time.time()}
    return data



def fetch_history_range(symbol: str, start: str, end: str, timeout: int = 7) -> dict:
    """Return adjusted daily closes for an explicit date range.

    The range form is used by Event Study and Historical Model Validation so
    old tests never depend on a moving ``period=5y`` window. ``end`` follows
    yfinance semantics (exclusive), therefore callers normally pass the day
    after the desired final calendar date. Results are cached in memory.
    """
    sym_up = symbol.upper()
    start = str(start)[:10]
    end = str(end)[:10]
    cache_key = f"range:{sym_up}:{start}:{end}"
    with _chart_lock:
        cached = _chart_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < CHART_TTL:
            return cached["data"]

    is_kase = sym_up.endswith(".KZ")
    candidates = kase_candidates(symbol) if is_kase else [symbol]
    hist = None
    resolved = symbol
    for cand in candidates:
        try:
            ticker_obj = yf.Ticker(cand, session=_SESSION) if _SESSION else yf.Ticker(cand)
            h = ticker_obj.history(
                start=start, end=end, interval="1d", auto_adjust=True, timeout=max(2, int(timeout))
            )
            if h is not None and not h.empty:
                hist = h
                resolved = cand
                break
        except Exception:
            continue

    if hist is None or hist.empty:
        # The KASE fallback exposes only its available history. Slice it rather
        # than fabricating observations outside the provider's coverage.
        if is_kase:
            try:
                from fetcher.kase_fetcher import fetch_kase_chart
                data = fetch_kase_chart(symbol)
                keep = [(d, v) for d, v in _clean_pairs(data.get("dates"), data.get("closes")) if start <= str(d.date()) < end]
                if keep:
                    closes = [round(float(v), 6) for _, v in keep]
                    dates = [str(d.date()) for d, _ in keep]
                    out = {
                        "ticker": symbol, "resolved_as": symbol, "dates": dates, "closes": closes,
                        "min_close": min(closes), "max_close": max(closes),
                        "start": start, "end": end, "source": "KASE fallback",
                    }
                    with _chart_lock:
                        _chart_cache[cache_key] = {"data": out, "ts": time.time()}
                    return out
            except Exception:
                pass
        return {
            "error": "no_data", "ticker": symbol, "dates": [], "closes": [],
            "start": start, "end": end,
        }

    close = _clean_history_close(hist)
    if close.empty:
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": [], "start": start, "end": end}
    closes = [round(float(v), 8) for v in close]
    dates = [str(d.date()) for d in close.index]
    data = {
        "ticker": symbol, "resolved_as": resolved if resolved != symbol else None,
        "dates": dates, "closes": closes,
        "min_close": min(closes), "max_close": max(closes),
        "start": start, "end": end, "source": "Yahoo Finance adjusted close",
    }
    with _chart_lock:
        _chart_cache[cache_key] = {"data": data, "ts": time.time()}
    return data

def fetch_chart(symbol: str) -> dict:
    """
    Вернуть годовые дневные котировки для построения sparkline.

    Для KASE перебирает кандидатов. Результат кешируется на CHART_TTL секунд.
    """
    sym_up = symbol.upper()

    with _chart_lock:
        cached = _chart_cache.get(sym_up)
        if cached and (time.time() - cached["ts"]) < CHART_TTL:
            return cached["data"]

    is_kase    = sym_up.endswith(".KZ")
    candidates = kase_candidates(symbol) if is_kase else [symbol]
    hist       = None

    for cand in candidates:
        try:
            ticker_obj = yf.Ticker(cand, session=_SESSION) if _SESSION else yf.Ticker(cand)
            h = ticker_obj.history(
                period="1y", interval="1d", auto_adjust=True, timeout=10
            )
            if not h.empty:
                hist = h
                break
        except Exception:
            continue

    if hist is None or hist.empty:
        # Fallback: для KASE тикеров пробуем kase.kz напрямую
        if is_kase:
            try:
                from fetcher.kase_fetcher import fetch_kase_chart
                raw = fetch_kase_chart(symbol)
                pairs = _clean_pairs(raw.get("dates"), raw.get("closes"))
                if len(pairs) < 2:
                    raise ValueError("KASE fallback returned no valid positive closes")
                closes = [round(v, 4) for _,v in pairs]
                dates_clean=[str(d.date()) for d,_ in pairs]
                data = {**raw, "dates":dates_clean, "closes":closes, "min_close":min(closes), "max_close":max(closes), **_coverage_meta(dates_clean)}
                with _chart_lock:
                    _chart_cache[sym_up] = {"data": data, "ts": time.time()}
                return data
            except Exception:
                pass
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": []}

    close = _clean_history_close(hist)
    if len(close) < 2:
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": []}
    closes = [round(float(v), 4) for v in close]
    dates  = [str(d.date()) for d in close.index]

    data = {
        "ticker":    symbol,
        "dates":     dates,
        "closes":    closes,
        "min_close": min(closes),
        "max_close": max(closes),
        **_coverage_meta(dates),
    }

    with _chart_lock:
        _chart_cache[sym_up] = {"data": data, "ts": time.time()}

    return data
