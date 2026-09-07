"""
server/handlers.py
==================
HTTP-обработчики для всех API-маршрутов.

Каждый handler — чистая функция: принимает parsed query string,
возвращает (status_code, body). Транспортный слой живёт в server/app.py.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from cache.ticker_cache import get_status, start_fetch, stop_fetch, clear_cache
from config.markets import (
    STOCK_TICKERS, ETF_TICKERS, BOND_TICKERS, MARKET_TICKERS,
    ETF_MARKET_TICKERS, BOND_MARKET_TICKERS, market_tickers, asset_type_for_ticker, symbol_market,
)
from fetcher.chart import fetch_chart
from fetcher.fundamentals import fetch_fundamentals, _fund_cache
from portfolio.optimizer import analyze_portfolio
from portfolio.risk_contribution import analyze_snapshot_risk_contribution
from portfolio.position_size_frontier import analyze_position_size_frontier
from portfolio.forecast import run_snapshot_forecast
from portfolio.snapshot import save_portfolio_snapshot, get_portfolio_snapshot, clear_portfolio_snapshots
from fetcher.risk_free import get_usd_risk_free_rate
from portfolio.event_study import run_event_study, list_earnings_dates, list_event_candidates
from portfolio.historical_validation import (
    run_historical_model_validation,
    build_historical_validation_forecast,
    reveal_historical_actual,
    FIRST_VALIDATION_YEAR,
    LAST_COMPLETED_YEAR,
)
from research.fundamental_trends import build_fundamental_trends
from research.peers import find_similar_companies
from research.capm import analyze_capm


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


def handle_fundamental_trends(qs: dict) -> tuple[int, dict]:
    """GET /api/fundamental-trends?ticker=AAPL — calculated annual trends."""
    ticker = qs.get("ticker", [""])[0].strip().upper()
    if not ticker:
        return 400, {"error": "missing ticker"}
    fd = fetch_fundamentals(ticker)
    result = build_fundamental_trends(fd)
    if result.get("error"):
        return 404, result
    return 200, result


def handle_similar_companies(qs: dict) -> tuple[int, dict]:
    """GET /api/similar-companies?ticker=AAPL&limit=8 — separate peer research."""
    ticker = qs.get("ticker", [""])[0].strip().upper()
    if not ticker:
        return 400, {"error": "missing ticker"}
    try:
        limit = int(qs.get("limit", ["8"])[0])
    except Exception:
        limit = 8
    result = find_similar_companies(ticker, limit=max(1, min(limit, 12)))
    if result.get("error"):
        return 400, result
    return 200, result


def handle_capm(qs: dict) -> tuple[int, dict]:
    """GET /api/capm?ticker=AAPL&market=US — local CAPM issuer research."""
    ticker = qs.get("ticker", [""])[0].strip().upper()
    if not ticker:
        return 400, {"error": "missing ticker"}
    market = qs.get("market", [""])[0].strip() or None
    refresh = qs.get("refresh", ["0"])[0].strip().lower() in {"1", "true", "yes"}
    result = analyze_capm(ticker, market=market, force_refresh=refresh)
    if result.get("error"):
        return 400, result
    return 200, result


def handle_tickers() -> tuple[int, dict]:
    """GET /api/tickers — separated stock/ETF/bond universes."""
    return 200, {
        "stocks": STOCK_TICKERS,
        "stock_count": len(STOCK_TICKERS),
        "etfs": ETF_TICKERS,
        "etf_count": len(ETF_TICKERS),
        "bonds": BOND_TICKERS,
        "bond_count": len(BOND_TICKERS),
        "markets": {k: v for k, v in MARKET_TICKERS.items()},
        "etf_markets": {k: v for k, v in ETF_MARKET_TICKERS.items()},
        "bond_markets": {k: v for k, v in BOND_MARKET_TICKERS.items()},
    }

def handle_fetch_post(qs: dict) -> tuple[int, dict]:
    """POST /api/fetch[?tickers=…] — запустить фоновый обход."""
    status = get_status()
    if status["status"] == "loading":
        return 200, {"ok": False, "msg": "Already loading — press Stop first"}

    raw        = qs.get("tickers", [""])[0]
    market     = qs.get("market", ["All"])[0]
    asset_type = qs.get("asset", ["stock"])[0]
    tickers = (
        [t.strip().upper() for t in raw.split(",") if t.strip()]
        if raw else market_tickers(market, asset_type)
    )
    start_fetch(tickers, asset_type)
    return 200, {"ok": True, "total": len(tickers)}


def handle_stop_post() -> tuple[int, dict]:
    """POST /api/stop — прервать обход."""
    stop_fetch()
    return 200, {"ok": True}


def handle_clear_post() -> tuple[int, dict]:
    """POST /api/clear — сбросить все кеши, включая portfolio snapshots."""
    stop_fetch()
    clear_cache()
    clear_portfolio_snapshots()
    return 200, {"ok": True}


def _parse_portfolio_query(qs: dict):
    raw = qs.get("assets", [""])[0]
    assets = [t.strip().upper() for t in raw.split(",") if t.strip()]
    try:
        amount = float(qs.get("amount", ["0"])[0])
    except Exception:
        raise ValueError("Некорректная сумма инвестирования")
    return assets, amount


def _snapshot_id(qs: dict) -> str:
    sid = qs.get("snapshot_id", [""])[0].strip()
    if not sid:
        raise ValueError("Отсутствует snapshot_id. Сначала рассчитайте портфель Markowitz.")
    return sid


def handle_portfolio(qs: dict) -> tuple[int, dict]:
    """Create one Markowitz portfolio and freeze it as a downstream snapshot."""
    try:
        assets, amount = _parse_portfolio_query(qs)
        objective = qs.get("objective", ["max_sharpe"])[0].strip().lower()
        concentration_mode = qs.get("concentration_mode", ["constrained"])[0].strip().lower()
        covariance_method = qs.get("covariance_method", ["ledoit_wolf"])[0].strip().lower()
        include_etf_holdings = qs.get("include_etf_holdings", ["1"])[0].strip().lower() not in {"0", "false", "no"}
        rf_meta = get_usd_risk_free_rate()
        risk_free_rate_pct = float(rf_meta["rate_pct"])
        result = analyze_portfolio(
            assets, amount, objective=objective,
            risk_free_rate_pct=risk_free_rate_pct,
            concentration_mode=concentration_mode,
            covariance_method=covariance_method,
            include_historical_returns=True,
            include_etf_holdings=include_etf_holdings,
        )
        result["risk_free"] = {
            "rate_pct": round(risk_free_rate_pct, 4),
            "as_of": rf_meta.get("as_of"),
            "source": rf_meta.get("source"),
            "instrument": rf_meta.get("instrument"),
            "stale": bool(rf_meta.get("stale")),
            "base_currency": "USD",
            "automatic": True,
        }
        historical_returns = result.pop("_historical_returns", [])
        snapshot_id = save_portfolio_snapshot(result, historical_returns)
        public_result = dict(result)
        public_result.pop("_engine", None)
        public_result["snapshot_id"] = snapshot_id
        public_result["snapshot_policy"] = "immutable_markowitz_single_source_of_truth"
        return 200, public_result
    except Exception as exc:
        return 400, {"error": str(exc)}



def handle_portfolio_risk_contribution(qs: dict) -> tuple[int, dict]:
    """Risk decomposition of the exact frozen portfolio snapshot."""
    try:
        sid = _snapshot_id(qs)
        snap = get_portfolio_snapshot(sid)
        out = analyze_snapshot_risk_contribution(snap)
        out["snapshot_id"] = sid
        return 200, out
    except Exception as exc:
        return 400, {"error": str(exc)}


def handle_position_size_frontier(qs: dict) -> tuple[int, dict]:
    """Analyze a new candidate at 0..20% against an immutable existing portfolio."""
    try:
        sid = _snapshot_id(qs)
        ticker = qs.get("candidate", [""])[0].strip().upper()
        if not ticker:
            raise ValueError("Укажите candidate ticker")
        try:
            selected_weight_pct = float(qs.get("weight_pct", ["5"])[0])
        except Exception:
            raise ValueError("Некорректный candidate weight")
        snap = get_portfolio_snapshot(sid)
        out = analyze_position_size_frontier(snap, ticker, selected_weight_pct=selected_weight_pct)
        out["snapshot_id"] = sid
        return 200, out
    except Exception as exc:
        return 400, {"error": str(exc)}

def handle_portfolio_forecast(qs: dict) -> tuple[int, dict]:
    """Run GBM or Bootstrap on an existing immutable Markowitz snapshot."""
    try:
        sid = _snapshot_id(qs)
        snap = get_portfolio_snapshot(sid)
        try:
            horizon_days = int(qs.get("horizon", ["252"])[0])
        except Exception:
            raise ValueError("Некорректный горизонт прогноза")
        try:
            simulations = int(qs.get("simulations", ["10000"])[0])
        except Exception:
            raise ValueError("Некорректное количество симуляций")
        try:
            seed_raw = qs.get("seed", [""])[0].strip()
            seed = int(seed_raw) if seed_raw else None
        except Exception:
            raise ValueError("Некорректный seed")
        try:
            block_size = int(qs.get("block_size", ["21"])[0])
        except Exception:
            raise ValueError("Некорректная длина Bootstrap-блока")

        model = qs.get("model", ["gbm"])[0].strip().lower()
        forecast = run_snapshot_forecast(
            snap, model=model, horizon_days=horizon_days, simulations=simulations,
            block_size=block_size, seed=seed,
        )
        forecast["snapshot_id"] = sid
        return 200, {
            "snapshot_id": sid,
            "forecast": {
                "model": model,
                "primary": forecast,
                "method_note": "Обе модели используют один и тот же замороженный Markowitz snapshot, одинаковый горизонт в торговых днях и buy-and-hold политику.",
            },
        }
    except Exception as exc:
        return 400, {"error": str(exc)}



def handle_historical_validation(qs: dict) -> tuple[int, dict]:
    """GET /api/historical-validation — rolling 3y-train / 1y-test validation."""
    try:
        assets, amount = _parse_portfolio_query(qs)
        objective = qs.get("objective", ["max_sharpe"])[0].strip().lower()
        concentration_mode = qs.get("concentration_mode", ["constrained"])[0].strip().lower()
        covariance_method = qs.get("covariance_method", ["ledoit_wolf"])[0].strip().lower()
        result = run_historical_model_validation(
            assets, amount, objective=objective, concentration_mode=concentration_mode, covariance_method=covariance_method
        )
        return 200, result
    except Exception as exc:
        return 400, {"error": str(exc)}

def handle_historical_validation_forecast(qs: dict) -> tuple[int, dict]:
    """Build one train-only historical forecast; test-year data stay unopened."""
    try:
        assets, amount = _parse_portfolio_query(qs)
        objective = qs.get("objective", ["max_sharpe"])[0].strip().lower()
        concentration_mode = qs.get("concentration_mode", ["constrained"])[0].strip().lower()
        covariance_method = qs.get("covariance_method", ["ledoit_wolf"])[0].strip().lower()
        raw_year = qs.get("test_year", [""])[0].strip()
        if not raw_year:
            raise ValueError(f"Укажите test_year: {FIRST_VALIDATION_YEAR}–{LAST_COMPLETED_YEAR}")
        result = build_historical_validation_forecast(
            assets, amount, int(raw_year), objective=objective, concentration_mode=concentration_mode, covariance_method=covariance_method
        )
        return 200, result
    except Exception as exc:
        return 400, {"error": str(exc)}


def handle_historical_validation_actual(qs: dict) -> tuple[int, dict]:
    """Reveal the untouched real test year for an already-frozen forecast."""
    try:
        validation_id = qs.get("validation_id", [""])[0].strip()
        result = reveal_historical_actual(validation_id)
        return 200, result
    except Exception as exc:
        return 400, {"error": str(exc)}

def handle_event_study(qs: dict) -> tuple[int, dict]:
    """GET /api/event-study — one-asset earnings/report event study."""
    try:
        ticker = qs.get("ticker", [""])[0].strip().upper()
        if not ticker:
            raise ValueError("Укажите тикер")
        if asset_type_for_ticker(ticker) != "stock":
            raise ValueError("Event Study отчётности доступен только для акций")
        event_date = qs.get("event_date", [""])[0].strip()
        if not event_date:
            dates = list_earnings_dates(ticker, limit=12)
            if not dates:
                raise ValueError("Не удалось автоматически найти реальную дату отчётности из доступных источников.")
            # Prefer the most recent date not later than today.
            from datetime import date
            today = date.today().isoformat()
            past = sorted([d for d in dates if d <= today], reverse=True)
            future = sorted([d for d in dates if d > today])
            event_date = past[0] if past else (future[0] if future else dates[0])
        market = qs.get("market", [""])[0].strip() or symbol_market(ticker)
        region = qs.get("region", [""])[0].strip() or None
        return 200, run_event_study(ticker, event_date, market=market, region=region)
    except Exception as exc:
        return 400, {"error": str(exc)}

def handle_event_dates(qs: dict) -> tuple[int, dict]:
    """GET /api/event-study/dates?ticker=AAPL — compact report candidates."""
    try:
        ticker = qs.get("ticker", [""])[0].strip().upper()
        if not ticker:
            raise ValueError("Укажите тикер")
        if asset_type_for_ticker(ticker) != "stock":
            raise ValueError("Event Study отчётности доступен только для акций")
        return 200, {"ticker": ticker, "candidates": list_event_candidates(ticker, limit=8), "dates": list_earnings_dates(ticker, limit=8)}
    except Exception as exc:
        return 400, {"error": str(exc)}


def handle_portfolio_export(qs: dict) -> tuple[int, bytes, str]:
    """Export the exact portfolio snapshot currently shown in the UI."""
    try:
        from export.portfolio import build_portfolio_excel
        sid = _snapshot_id(qs)
        snap = get_portfolio_snapshot(sid)
        return 200, build_portfolio_excel(snap["result"]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception as exc:
        return 400, json_error(exc), "application/json"


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
