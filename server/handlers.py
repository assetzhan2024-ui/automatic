"""
server/handlers.py
==================
HTTP-обработчики для всех API-маршрутов.

Каждый handler — чистая функция: принимает parsed query string,
возвращает (status_code, body). Транспортный слой живёт в server/app.py.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from cache.ticker_cache import get_status, start_fetch, stop_fetch, clear_cache
from config.tickers import DEFAULT_TICKERS
from fetcher.chart import fetch_chart
from fetcher.fundamentals import fetch_fundamentals, _fund_cache


# ── Shared helper ─────────────────────────────────────────────────────────────

def _build_fund_map(records: list[dict]) -> dict:
    """
    Для списка записей построить {ticker: fund_data}.
    Сначала проверяет in-memory кеш, затем параллельно загружает недостающие.
    Никаких блокирующих вызовов из главного потока сервера.
    """
    fund_map: dict = {}
    missing:  list = []

    for rec in records:
        ticker = rec.get("ticker", "")
        cached = _fund_cache.get(ticker.upper())
        if cached and isinstance(cached, dict):
            fd = cached.get("data", {})
            if fd and not fd.get("error"):
                fund_map[ticker] = fd
                continue
        missing.append(ticker)

    if missing:
        def _fetch(t: str):
            try:
                return t, fetch_fundamentals(t)
            except Exception:
                return t, None

        with ThreadPoolExecutor(max_workers=min(len(missing), 8)) as pool:
            futures = {pool.submit(_fetch, t): t for t in missing}
            for fut in as_completed(futures, timeout=20):
                try:
                    t, fd = fut.result()
                    if fd and not fd.get("error"):
                        fund_map[t] = fd
                except Exception:
                    pass

    return fund_map


def _filter_records(qs: dict) -> list[dict]:
    """Вернуть отфильтрованный список из кеша по параметру tickers=."""
    all_data = get_status().get("data", [])
    raw = qs.get("tickers", [""])[0]
    if raw:
        wanted = {t.strip().upper() for t in raw.split(",") if t.strip()}
        all_data = [b for b in all_data if b.get("ticker", "").upper() in wanted]
    return all_data


# ── Export handlers ───────────────────────────────────────────────────────────

def handle_export(qs: dict) -> tuple[int, bytes, str]:
    """GET /api/export?tickers=AAPL,MSFT — экспорт данных тикеров в Excel."""
    try:
        from export.excel import build_excel

        records = _filter_records(qs)
        if not records:
            return 400, b'{"error":"no data"}', "application/json"

        fund_map   = _build_fund_map(records)
        xlsx_bytes = build_excel(records, fund_map)
        return 200, xlsx_bytes, \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    except Exception as exc:
        import traceback; traceback.print_exc()
        return 500, json_error(exc), "application/json"


def handle_export_dcf(qs: dict) -> tuple[int, bytes, str]:
    """GET /api/export/dcf?tickers=HSBK — DCF-модель в Excel."""
    try:
        from export.dcf import build_dcf_multi

        records = _filter_records(qs)
        if not records:
            return 400, b'{"error":"no data"}', "application/json"

        fund_map   = _build_fund_map(records)
        xlsx_bytes = build_dcf_multi(records, fund_map)
        return 200, xlsx_bytes, \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    except Exception as exc:
        import traceback; traceback.print_exc()
        return 500, json_error(exc), "application/json"


# ── Utility ───────────────────────────────────────────────────────────────────

def json_error(exc: Exception) -> bytes:
    """Безопасно сформировать JSON с описанием ошибки."""
    import json
    msg = str(exc)[:200]
    return json.dumps({"error": msg}).encode()


# ── Standard handlers ─────────────────────────────────────────────────────────

def handle_status(_qs: dict) -> tuple[int, dict]:
    """GET /api/status — текущее состояние + данные."""
    return 200, get_status()


def handle_chart(qs: dict) -> tuple[int, dict]:
    """GET /api/chart?ticker=AAPL — годовые котировки для sparkline."""
    ticker = qs.get("ticker", [""])[0].strip().upper()
    if not ticker:
        return 400, {"error": "missing ticker"}
    return 200, fetch_chart(ticker)


def handle_fundamentals(qs: dict) -> tuple[int, dict]:
    """GET /api/fundamentals?ticker=AAPL — годовые финансовые отчёты."""
    ticker = qs.get("ticker", [""])[0].strip().upper()
    if not ticker:
        return 400, {"error": "missing ticker"}
    return 200, fetch_fundamentals(ticker)


def handle_tickers() -> tuple[int, dict]:
    """GET /api/tickers — список тикеров по умолчанию."""
    return 200, {"tickers": DEFAULT_TICKERS, "count": len(DEFAULT_TICKERS)}


def handle_fetch_post(qs: dict) -> tuple[int, dict]:
    """POST /api/fetch[?tickers=…] — запустить фоновый обход."""
    status = get_status()
    if status["status"] == "loading":
        return 200, {"ok": False, "msg": "Already loading — press Stop first"}

    raw     = qs.get("tickers", [""])[0]
    tickers = (
        [t.strip().upper() for t in raw.split(",") if t.strip()]
        if raw else DEFAULT_TICKERS
    )
    start_fetch(tickers)
    return 200, {"ok": True, "total": len(tickers)}


def handle_stop_post() -> tuple[int, dict]:
    """POST /api/stop — прервать обход."""
    stop_fetch()
    return 200, {"ok": True}


def handle_clear_post() -> tuple[int, dict]:
    """POST /api/clear — сбросить все кеши."""
    stop_fetch()
    clear_cache()
    return 200, {"ok": True}


def handle_kase_test(qs: dict) -> tuple[int, dict]:
    """GET /api/kase_test?ticker=HSBK — диагностика парсинга kase.kz."""
    import re
    ticker = qs.get("ticker", ["HSBK"])[0].strip().upper().replace(".KZ", "")
    from fetcher.kase_fetcher import fetch_kase_quote, _fetch_url

    url  = f"https://kase.kz/ru/shares/show/{ticker}/"
    raw  = _fetch_url(url)
    html = raw.decode("utf-8", errors="ignore") if raw else ""

    snippets = []
    for pattern in [
        r'.{0,60}(?:последн|last_price|lastPrice|цена|price|сделк).{0,60}',
        r'<[^>]*class="[^"]*price[^"]*"[^>]*>[^<]{1,30}<',
        r'data-[\w-]*="[\d.,]+"',
    ]:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            s = m.group(0).strip()
            if any(c.isdigit() for c in s):
                snippets.append(s[:120])

    return 200, {
        "ticker":       ticker,
        "parsed_price": fetch_kase_quote(ticker),
        "url":          url,
        "html_length":  len(html),
        "snippets":     snippets[:20],
    }
