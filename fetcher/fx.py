"""
fetcher/fx.py
=============
Получение курсов валют к USD через yfinance.

Публичный API:
    get_rate(currency: str) -> float | None   — курс currency/USD (сколько USD = 1 unit currency)
    to_usd(value, currency: str) -> float | None
    clear_fx_cache() -> None

Кеш с TTL 1 час — курсы не нужны точнее.
GBp (пенс) — особый случай: 1 GBp = 0.01 GBP.
USD → 1.0 всегда.
"""

import threading
import time

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance pandas")

from fetcher.session import SESSION as _SESSION

_FX_TTL = 3600  # 1 час

# Пары валюта → Yahoo тикер
_YF_PAIRS: dict[str, str] = {
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "KZT": "KZTUSD=X",
    "JPY": "JPYUSD=X",
    "HKD": "HKDUSD=X",
    "CNY": "CNYUSD=X",
    "KRW": "KRWUSD=X",
    "AUD": "AUDUSD=X",
    "CAD": "CADUSD=X",
    "CHF": "CHFUSD=X",
    "SEK": "SEKUSD=X",
    "NOK": "NOKRUSD=X",
    "DKK": "DKKUSD=X",
    "BRL": "BRLUSD=X",
    "MXN": "MXNUSD=X",
    "INR": "INRUSD=X",
    "TRY": "TRYUSD=X",
    "ZAR": "ZARUSD=X",
    "SGD": "SGDUSD=X",
    "TWD": "TWDUSD=X",
    "IDR": "IDRUSD=X",
    "THB": "THBUSD=X",
    "PHP": "PHPUSD=X",
    "VND": "VNDUSD=X",
    "ARS": "ARSUSD=X",
    "EGP": "EGPUSD=X",
    "NGN": "NGNUSD=X",
}

_fx_cache: dict[str, dict] = {}  # { "EUR": {"rate": 1.09, "ts": 1234567890} }
_fx_lock = threading.Lock()


def clear_fx_cache() -> None:
    with _fx_lock:
        _fx_cache.clear()


def get_rate(currency: str) -> float | None:
    """
    Вернуть курс: сколько USD за 1 единицу currency.
    USD → 1.0, GBp → 0.01 * GBP/USD, неизвестная → None.
    """
    if not currency:
        return None
    if currency == "USD":
        return 1.0
    # GBp (пенсы LSE) = 0.01 GBP
    if currency == "GBp":
        gbp = get_rate("GBP")
        return round(gbp * 0.01, 8) if gbp else None
    # ZAc (South African cents, JSE) = 0.01 ZAR
    if currency == "ZAc":
        zar = get_rate("ZAR")
        return round(zar * 0.01, 8) if zar else None

    cur = currency.upper()

    with _fx_lock:
        cached = _fx_cache.get(cur)
        if cached and (time.time() - cached["ts"]) < _FX_TTL:
            return cached["rate"]

    pair = _YF_PAIRS.get(cur)
    if not pair:
        return None

    try:
        ticker_obj = yf.Ticker(pair, session=_SESSION) if _SESSION else yf.Ticker(pair)
        hist = ticker_obj.history(period="2d", interval="1d", auto_adjust=False)
        if hist.empty:
            return None
        rate = float(hist["Close"].dropna().iloc[-1])
        if rate <= 0:
            return None
        with _fx_lock:
            _fx_cache[cur] = {"rate": rate, "ts": time.time()}
        return rate
    except Exception:
        return None


def to_usd(value, currency: str) -> float | None:
    """Конвертировать значение из currency в USD. None если нет курса или value."""
    if value is None:
        return None
    rate = get_rate(currency)
    if rate is None:
        return None
    return value * rate
