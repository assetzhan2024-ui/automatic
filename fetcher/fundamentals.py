"""
fetcher/fundamentals.py
=======================
Получение годовых финансовых отчётов (income statement, balance sheet,
cash flow) через yfinance для детального просмотра компании.

Публичный API:
    fetch_fundamentals(symbol: str) → dict
        {ticker, income, balance, cashflow}
        каждый раздел: { "YYYY": { metric: value } } — новейшие сначала
    clear_fund_cache()              — принудительно сбросить кеш

Кеш в памяти с TTL 2 часа — фундаментальные данные меняются редко.
"""

import threading
import time

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance pandas")

from config.kase import kase_candidates
from fetcher.session import SESSION as _SESSION

FUND_TTL = 7200  # секунд (2 часа)

_fund_cache: dict = {}
_fund_lock = threading.Lock()


def clear_fund_cache() -> None:
    """Принудительно очистить кеш фундаментальных данных."""
    with _fund_lock:
        _fund_cache.clear()


def _df_to_records(df) -> dict:
    """
    Конвертировать DataFrame yfinance (колонки=даты, индекс=метрики)
    в { "YYYY": { metric: value, … } }, отсортированный новейшим первым.
    """
    if df is None or df.empty:
        return {}

    out = {}
    for col in df.columns:
        year = str(col)[:4]   # "2023-12-31 00:00:00" → "2023"
        row = {}
        for metric, val in df[col].items():
            try:
                f = float(val)
                row[str(metric)] = None if (f != f) else round(f, 0)
            except Exception:
                row[str(metric)] = None
        out[year] = row

    return dict(sorted(out.items(), reverse=True))


def fetch_fundamentals(symbol: str) -> dict:
    """
    Вернуть годовые финансовые отчёты компании.

    Для KASE перебирает кандидатов.
    Результат кешируется на FUND_TTL секунд.
    """
    sym_up = symbol.upper()

    with _fund_lock:
        cached = _fund_cache.get(sym_up)
        if cached and (time.time() - cached["ts"]) < FUND_TTL:
            return cached["data"]

    is_kase    = sym_up.endswith(".KZ")
    candidates = kase_candidates(symbol) if is_kase else [symbol]
    ticker_obj = None

    for cand in candidates:
        try:
            t   = yf.Ticker(cand, session=_SESSION) if _SESSION else yf.Ticker(cand)
            _   = t.financials   # зондируем: бросает исключение для невалидных символов
            ticker_obj = t
            break
        except Exception:
            continue

    if ticker_obj is None:
        # Fallback: для KASE тикеров пробуем kase.kz напрямую
        if is_kase:
            try:
                from fetcher.kase_fetcher import fetch_kase_fundamentals
                data = fetch_kase_fundamentals(symbol)
                with _fund_lock:
                    _fund_cache[sym_up] = {"data": data, "ts": time.time()}
                return data
            except Exception:
                pass
        return {"error": "no_data", "ticker": symbol, "income": {}, "balance": {}, "cashflow": {}}

    def _safe_fetch(attr: str) -> dict:
        try:
            return _df_to_records(getattr(ticker_obj, attr))
        except Exception:
            return {}

    data = {
        "ticker":   symbol,
        "income":   _safe_fetch("financials"),
        "balance":  _safe_fetch("balance_sheet"),
        "cashflow": _safe_fetch("cashflow"),
    }

    with _fund_lock:
        _fund_cache[sym_up] = {"data": data, "ts": time.time()}

    return data
