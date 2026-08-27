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
except ImportError:  # optional at import time; live FX features fail clearly at call time
    yf = None

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
    if yf is None:
        return None
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

# Historical FX series for research/backtesting.
def fetch_fx_history(currency: str, period: str = "5y"):
    """Return a daily series of KZT value of one unit of ``currency``.

    Uses Yahoo Finance currency pairs. For example, JPY/KZT is derived as
    (JPY/USD) / (KZT/USD). USD/KZT is 1 / (KZT/USD). Returns None when the
    provider cannot supply the required pair.
    """
    import pandas as pd
    cur = (currency or "USD").strip().upper()
    if cur == "KZT":
        return pd.Series(1.0, index=pd.DatetimeIndex([]), dtype="float64")
    cache_key = f"hist:{cur}:{period}"
    with _fx_lock:
        cached = _fx_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < _FX_TTL:
            return cached["data"].copy()
    if yf is None:
        return None
    try:
        if cur != "USD" and cur not in _YF_PAIRS:
            return None
        local_pair = _YF_PAIRS.get(cur)
        def _hist(pair):
            if not pair:
                return None
            obj = yf.Ticker(pair, session=_SESSION) if _SESSION else yf.Ticker(pair)
            h = obj.history(period=period, interval="1d", auto_adjust=False)
            if h is None or h.empty:
                return None
            s = pd.to_numeric(h["Close"], errors="coerce").dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            return s.sort_index()
        # Prefer the direct USD/KZT pair; fall back to the inverse KZT/USD pair.
        usd_kzt = _hist("USDKZT=X")
        kzt_usd = _hist(_YF_PAIRS["KZT"])
        if usd_kzt is not None:
            if cur == "USD":
                fx = usd_kzt
            else:
                local_usd = _hist(local_pair)
                if local_usd is None:
                    return None
                common = pd.concat({"local": local_usd, "usd_kzt": usd_kzt}, axis=1).sort_index().ffill().dropna()
                fx = (common["local"] * common["usd_kzt"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
        else:
            if kzt_usd is None:
                return None
            if cur == "USD":
                fx = (1.0 / kzt_usd).replace([float("inf"), float("-inf")], pd.NA).dropna()
            else:
                local_usd = _hist(local_pair)
                if local_usd is None:
                    return None
                common = pd.concat({"local": local_usd, "kzt": kzt_usd}, axis=1).sort_index().ffill().dropna()
                fx = (common["local"] / common["kzt"]).replace([float("inf"), float("-inf")], pd.NA).dropna()
        fx.name = f"{cur}/KZT"
        with _fx_lock:
            _fx_cache[cache_key] = {"data": fx.copy(), "ts": time.time()}
        return fx
    except Exception:
        return None


def fetch_fx_history_usd(currency: str, period: str = "5y"):
    """Return daily USD value of one unit of ``currency``.

    Example: JPY -> JPYUSD=X. USD returns a constant 1 series aligned by the
    caller. GBp/ZAc are converted from their major currency units.
    """
    import pandas as pd
    cur_raw = (currency or "USD").strip()
    if cur_raw == "GBp":
        base, scale = "GBP", 0.01
    elif cur_raw == "ZAc":
        base, scale = "ZAR", 0.01
    else:
        base, scale = cur_raw.upper(), 1.0
    if base == "USD":
        return pd.Series(dtype="float64", name="USD/USD")
    cache_key = f"hist_usd:{base}:{period}"
    with _fx_lock:
        cached = _fx_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < _FX_TTL:
            s = cached["data"].copy()
            return s * scale if scale != 1.0 else s
    if yf is None:
        return None
    pair = _YF_PAIRS.get(base)
    try:
        if base == "KZT":
            # Prefer direct KZT/USD; fall back to inverse USD/KZT.
            obj = yf.Ticker(pair, session=_SESSION) if (_SESSION and pair) else (yf.Ticker(pair) if pair else None)
            h = obj.history(period=period, interval="1d", auto_adjust=False) if obj else None
            s = None if h is None or h.empty else pd.to_numeric(h["Close"], errors="coerce").dropna()
            if s is None or s.empty:
                p2 = "USDKZT=X"
                obj2 = yf.Ticker(p2, session=_SESSION) if _SESSION else yf.Ticker(p2)
                h2 = obj2.history(period=period, interval="1d", auto_adjust=False)
                if h2 is None or h2.empty:
                    return None
                inv = pd.to_numeric(h2["Close"], errors="coerce").dropna()
                s = (1.0 / inv).replace([float("inf"), float("-inf")], pd.NA).dropna()
        else:
            if not pair:
                return None
            obj = yf.Ticker(pair, session=_SESSION) if _SESSION else yf.Ticker(pair)
            h = obj.history(period=period, interval="1d", auto_adjust=False)
            if h is None or h.empty:
                return None
            s = pd.to_numeric(h["Close"], errors="coerce").dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s.sort_index()
        s.name = f"{base}/USD"
        with _fx_lock:
            _fx_cache[cache_key] = {"data": s.copy(), "ts": time.time()}
        return s * scale if scale != 1.0 else s
    except Exception:
        return None
