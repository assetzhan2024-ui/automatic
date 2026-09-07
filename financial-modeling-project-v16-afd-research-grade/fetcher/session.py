"""
fetcher/session.py
==================
Единственный источник curl_cffi сессии для всех fetcher-модулей.
Вынесен отдельно чтобы избежать циклических импортов между ticker и fx.
"""

_DEFAULT_TIMEOUT = 30

try:
    from curl_cffi.requests import Session as _CurlSession
    SESSION = _CurlSession(impersonate="chrome", timeout=_DEFAULT_TIMEOUT)
except ImportError:
    SESSION = None  # fallback: yfinance создаст сессию сам
