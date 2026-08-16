"""
fetcher/chart.py
================
Получение годовых дневных цен закрытия для sparkline-графика.

Публичный API:
    fetch_chart(symbol: str) → dict
        {ticker, dates, closes, min_close, max_close}
        или {error: "no_data", ticker, dates: [], closes: []}
    clear_chart_cache()     — принудительно сбросить кеш

Кеш в памяти с TTL 1 час — не нужны свежие данные чаще.
"""

import threading
import time

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
                period="1y", interval="1d", auto_adjust=True
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
                data = fetch_kase_chart(symbol)
                with _chart_lock:
                    _chart_cache[sym_up] = {"data": data, "ts": time.time()}
                return data
            except Exception:
                pass
        return {"error": "no_data", "ticker": symbol, "dates": [], "closes": []}

    closes = [round(float(v), 4) for v in hist["Close"]]
    dates  = [str(d.date()) for d in hist.index]

    data = {
        "ticker":    symbol,
        "dates":     dates,
        "closes":    closes,
        "min_close": min(closes),
        "max_close": max(closes),
    }

    with _chart_lock:
        _chart_cache[sym_up] = {"data": data, "ts": time.time()}

    return data
