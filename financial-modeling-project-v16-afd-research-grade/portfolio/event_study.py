"""Event-study analytics for earnings/report announcements.

Research-oriented market-model event study:
- estimation window: -110 to -11 trading days (100 observations)
- event window: -5 to +5 trading days, or as far as data is actually available
- market model: R_i,t = alpha + beta * R_m,t + error
- abnormal return (AR), cumulative abnormal return (CAR), t-statistic
- latest report/news context: revenue, net income, dividend and a short driver note

Important research convention:
Day 0 is the reporting/news trading session. The app never fabricates future data.
If the event is recent, the event window is explicitly marked as incomplete and
CAR/tables stop at the latest available post-event trading day.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from fetcher.chart import fetch_history, fetch_history_range
from config.kase import kase_candidates
from fetcher.session import SESSION as _SESSION
from fetcher.official_events import official_event_candidates, sec_event_candidates, kase_event_candidates, kase_official_issuer_page

EST_START = -110
EST_END = -11
EVENT_START = -5
EVENT_END = 5
EVENT_CACHE_TTL = 900

BENCHMARKS = {
    "US": "^GSPC",
    "Japan": "^N225",
    "London": "^FTSE",
    "France": "^FCHI",
    "Australia": "^AORD",
    "Europe": "^STOXX50E",
    "Asia": "^HSI",
    "Kazakhstan": "^KZKAK",
    "KZ": "^KZKAK",
}

_event_cache: dict[tuple, tuple[float, dict]] = {}
_event_cache_lock = threading.Lock()
_earnings_cache: dict[tuple, tuple[float, list[dict]]] = {}
_earnings_cache_lock = threading.Lock()


def _to_df(history: dict) -> pd.Series:
    dates = history.get("dates") or []
    closes = history.get("closes") or []
    if len(dates) < 3 or len(closes) < 3:
        return pd.Series(dtype=float)
    s = pd.Series(pd.to_numeric(closes, errors="coerce"), index=pd.to_datetime(dates, errors="coerce"))
    s = s[~s.index.duplicated(keep="last")].sort_index().dropna()
    return s


def _returns(s: pd.Series) -> pd.Series:
    return s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def benchmark_for_market(market: str | None, region: str | None = None) -> str:
    for key in (market, region):
        if key in BENCHMARKS:
            return BENCHMARKS[key]
    return "^GSPC"


def _nearest_trading_date(index: pd.DatetimeIndex, event_date: pd.Timestamp) -> pd.Timestamp:
    if event_date in index:
        return event_date
    distances = np.abs(index.view("i8") - event_date.value)
    m = int(np.argmin(distances))
    return index[m]


def _parse_event_date(raw: str | None) -> pd.Timestamp:
    if not raw:
        raise ValueError("Укажите дату публикации отчёта (YYYY-MM-DD)")
    try:
        return pd.Timestamp(datetime.strptime(raw[:10], "%Y-%m-%d").date())
    except Exception as exc:
        raise ValueError("Дата события должна быть в формате YYYY-MM-DD") from exc


def _ticker_obj(symbol: str):
    import yfinance as yf
    candidates = kase_candidates(symbol) if symbol.upper().endswith(".KZ") else [symbol]
    for cand in candidates:
        try:
            return yf.Ticker(cand, session=_SESSION) if _SESSION else yf.Ticker(cand)
        except Exception:
            continue
    return None


def _ts_date(v: Any) -> pd.Timestamp | None:
    try:
        ts = pd.Timestamp(v)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts.normalize()
    except Exception:
        return None


def _quarter_label(rank: int) -> str:
    return f"Квартальный отчёт {rank}" if 1 <= rank <= 4 else "Квартальный отчёт"


def _annual_earnings_candidate(obj, earnings_dates: list[str]) -> dict | None:
    """Map the latest annual financial period to the nearest plausible earnings release date."""
    try:
        af = getattr(obj, "financials", None)
        rows = _df_to_metric_rows(af)
        if not rows or not earnings_dates:
            return None
        fiscal_end = rows[0][0]
        parsed = [pd.Timestamp(d) for d in earnings_dates]
        plausible = [d for d in parsed if 0 <= (d - fiscal_end).days <= 150]
        if not plausible:
            return None
        chosen = min(plausible, key=lambda d: abs((d - fiscal_end).days))
        return {"label": "Годовой отчёт", "date": chosen.strftime("%Y-%m-%d"), "is_past": chosen.date() <= date.today()}
    except Exception:
        return None


def list_event_candidates(ticker: str, limit: int = 8) -> list[dict]:
    """Return report candidates, preferring official issuer/regulator sources.

    Official sources are preferred (SEC EDGAR for SEC-reporting issuers and KASE
    issuer pages for Kazakhstan). Yahoo earnings dates remain a fallback for
    markets where an official machine-readable feed is unavailable.
    """
    key = (ticker.upper(), int(limit))
    now = time.time()
    with _earnings_cache_lock:
        cached = _earnings_cache.get(key)
        if cached and now - cached[0] < EVENT_CACHE_TTL:
            return cached[1]

    try:
        official = official_event_candidates(ticker, limit=limit)
        if official:
            # KASE issuer pages are an official source even when a specific report
            # link could not be extracted; keep the visible source provenance.
            return official[:limit]

        obj = _ticker_obj(ticker)
        if obj is None:
            return []
        frame = obj.get_earnings_dates(limit=limit)
        if frame is None or frame.empty:
            return []
        dates = []
        for x in pd.to_datetime(frame.index, errors="coerce"):
            ts = _ts_date(x)
            if ts is not None:
                dates.append(ts.strftime("%Y-%m-%d"))
        # Deduplicate while keeping newest first.
        dates = list(dict.fromkeys(dates))
        today = date.today().isoformat()
        past = sorted([d for d in dates if d <= today], reverse=True)
        future = sorted([d for d in dates if d > today])
        ordered = past + future
        out = []
        for i, d in enumerate(ordered[:limit], start=1):
            label = _quarter_label(i) if i <= 4 else "Предыдущий отчёт"
            out.append({"label": f"{label} · {d}", "date": d, "is_past": d <= today, "source_name": "Market-data provider", "source_url": None})
        annual = _annual_earnings_candidate(obj, ordered)
        if annual and annual["date"] not in {x["date"] for x in out}:
            out.append(annual)
        elif annual:
            # If annual and quarterly release coincide, keep one date but expose the annual meaning explicitly.
            for item in out:
                if item["date"] == annual["date"]:
                    item["label"] = f"{item['label']} / годовой отчёт"
                    break
        with _earnings_cache_lock:
            _earnings_cache[key] = (now, out)
        return out
    except Exception:
        return []


def list_earnings_dates(ticker: str, limit: int = 12) -> list[str]:
    return [x["date"] for x in list_event_candidates(ticker, limit=limit)]


def _df_to_metric_rows(df: Any) -> list[tuple[pd.Timestamp, dict]]:
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[tuple[pd.Timestamp, dict]] = []
    try:
        for col in df.columns:
            ts = _ts_date(col)
            if ts is None:
                continue
            metrics = {}
            for metric, value in df[col].items():
                try:
                    f = float(value)
                    if math.isfinite(f):
                        metrics[str(metric)] = f
                except Exception:
                    continue
            rows.append((ts, metrics))
    except Exception:
        return []
    return sorted(rows, key=lambda x: x[0], reverse=True)


def _metric(metrics: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in metrics:
            return metrics[key]
    return None


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _report_context(ticker: str, event_day: pd.Timestamp) -> dict:
    """Build a compact fundamental/news context around the selected report date."""
    obj = _ticker_obj(ticker)
    official_source = None
    try:
        official_rows = official_event_candidates(ticker, limit=12)
        if official_rows:
            nearest = min(official_rows, key=lambda x: abs((pd.Timestamp(x["date"]) - event_day).days))
            official_source = {k: nearest.get(k) for k in ("source_name", "source_url", "label", "form", "event_type")}
        elif ticker.upper().endswith(".KZ"):
            official_source = kase_official_issuer_page(ticker)
    except Exception:
        official_source = None
    if obj is None:
        return {"available": False, "summary": "Финансовый контекст недоступен."}

    revenue_growth = net_income_growth = None
    revenue = net_income = None
    period_end = None
    period_label = None
    dividend_value = None
    dividend_date = None
    news_title = None
    news_date = None
    publisher = None

    # Quarterly report data is preferred; fall back to annual if unavailable.
    try:
        qf = getattr(obj, "quarterly_financials", None)
        qrows = _df_to_metric_rows(qf)
        if qrows:
            # Pick the latest reported financial period ending before day 0;
            # this avoids using today's fundamentals for a historical event.
            eligible = [(ts, metrics) for ts, metrics in qrows if ts <= event_day and (event_day - ts).days <= 150]
            current_ts, current_metrics = (eligible[0] if eligible else qrows[0])
            prior_same = None
            for ts, metrics in qrows:
                if (current_ts - ts).days >= 250:
                    prior_same = metrics
                    break
            revenue = _metric(current_metrics, ("Total Revenue", "Operating Revenue"))
            net_income = _metric(current_metrics, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"))
            revenue_growth = _pct_change(revenue, _metric(prior_same or {}, ("Total Revenue", "Operating Revenue")))
            net_income_growth = _pct_change(net_income, _metric(prior_same or {}, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests")))
            period_end = current_ts.strftime("%Y-%m-%d")
            period_label = "квартал"
        else:
            af = getattr(obj, "financials", None)
            arows = _df_to_metric_rows(af)
            if arows:
                eligible = [(ts, metrics) for ts, metrics in arows if ts <= event_day and (event_day - ts).days <= 450]
                current_ts, current_metrics = (eligible[0] if eligible else arows[0])
                prior = {}
                for ts, metrics in arows:
                    if (current_ts - ts).days >= 300:
                        prior = metrics
                        break
                revenue = _metric(current_metrics, ("Total Revenue", "Operating Revenue"))
                net_income = _metric(current_metrics, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"))
                revenue_growth = _pct_change(revenue, _metric(prior, ("Total Revenue", "Operating Revenue")))
                net_income_growth = _pct_change(net_income, _metric(prior, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests")))
                period_end = current_ts.strftime("%Y-%m-%d")
                period_label = "год"
    except Exception:
        pass

    # Dividend context: latest declared/paid distribution around the event date.
    try:
        divs = obj.dividends
        if divs is not None and not divs.empty:
            divs = divs.copy()
            idx = pd.to_datetime(divs.index, errors="coerce")
            mask = idx <= event_day
            if mask.any():
                ix = idx[mask][-1]
                dividend_value = float(divs.iloc[mask.nonzero()[0][-1]]) if hasattr(mask, "nonzero") else None
                if dividend_value is None:
                    vals = divs.loc[mask]
                    dividend_value = float(vals.iloc[-1]) if len(vals) else None
                dividend_date = pd.Timestamp(ix).strftime("%Y-%m-%d")
    except Exception:
        pass

    # News is context only: event-study causality comes from AR/CAR, not headline text.
    try:
        news = getattr(obj, "news", None) or []
        candidates = []
        for item in news:
            content = item.get("content") if isinstance(item, dict) else None
            title = (content or {}).get("title") or item.get("title") if isinstance(item, dict) else None
            pub = (content or {}).get("pubDate") or item.get("providerPublishTime") if isinstance(item, dict) else None
            dt = _ts_date(pub) if pub else None
            if title and dt is not None:
                distance = abs((dt - event_day).days)
                candidates.append((distance, dt, str(title), (content or {}).get("provider", {}).get("displayName") if isinstance(content, dict) else item.get("publisher")))
        if candidates:
            candidates.sort(key=lambda x: (x[0], -x[1].value))
            _, news_dt, news_title, publisher = candidates[0]
            news_date = news_dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    drivers = []
    if revenue_growth is not None:
        drivers.append(f"выручка {revenue_growth:+.1f}%")
    if net_income_growth is not None:
        drivers.append(f"чистая прибыль {net_income_growth:+.1f}%")
    if dividend_value is not None:
        drivers.append(f"дивиденд {dividend_value:.2f} на акцию")

    if drivers:
        summary = "; ".join(drivers) + "."
        if news_title:
            summary += f" Ближайший информационный повод: «{news_title[:180]}»."
    elif news_title:
        summary = f"Ближайший информационный повод: «{news_title[:180]}»."
    else:
        summary = "В доступном источнике нет достаточного фундаментального/новостного контекста; событием считается сама публикация отчётности."

    return {
        "available": bool(drivers or news_title),
        "period_end": period_end,
        "period_label": period_label,
        "revenue": revenue,
        "revenue_growth_pct": revenue_growth,
        "net_income": net_income,
        "net_income_growth_pct": net_income_growth,
        "dividend_per_share": dividend_value,
        "dividend_date": dividend_date,
        "news_title": news_title,
        "news_date": news_date,
        "publisher": publisher,
        "official_source": official_source,
        "summary": summary,
    }


def _market_model_diagnostics(stock_r: pd.Series, market_r: pd.Series) -> dict:
    """OLS market model plus regression diagnostics used by research-grade AR tests."""
    df = pd.concat([stock_r.rename("stock"), market_r.rename("market")], axis=1).dropna()
    n = len(df)
    if n < 30:
        raise ValueError("Недостаточно совместимых наблюдений для окна оценки")
    x = df["market"].to_numpy(float)
    y = df["stock"].to_numpy(float)
    xm, ym = float(np.mean(x)), float(np.mean(y))
    sxx = float(np.sum((x - xm) ** 2))
    if sxx <= 1e-14:
        raise ValueError("Рыночная доходность почти не менялась: beta невозможно оценить")
    beta = float(np.sum((y - ym) * (x - xm)) / sxx)
    alpha = float(ym - beta * xm)
    fitted = alpha + beta * x
    resid = y - fitted
    sse = float(np.sum(resid ** 2))
    df_resid = n - 2
    residual_variance = float(sse / df_resid)
    residual_std = float(math.sqrt(residual_variance))
    sst = float(np.sum((y - ym) ** 2))
    r2 = float(1.0 - sse / sst) if sst > 1e-14 else 0.0

    se_beta = float(math.sqrt(residual_variance / sxx))
    se_alpha = float(residual_std * math.sqrt(1.0 / n + (xm * xm) / sxx))
    t_beta = beta / se_beta if se_beta > 1e-14 else float("nan")
    t_alpha = alpha / se_alpha if se_alpha > 1e-14 else float("nan")
    p_beta = float(2.0 * student_t.sf(abs(t_beta), df_resid)) if math.isfinite(t_beta) else None
    p_alpha = float(2.0 * student_t.sf(abs(t_alpha), df_resid)) if math.isfinite(t_alpha) else None

    return {
        "alpha": alpha,
        "beta": beta,
        "residual_std": residual_std,
        "residual_variance": residual_variance,
        "sse": sse,
        "sst": sst,
        "r_squared": r2,
        "observations": n,
        "df_resid": df_resid,
        "market_mean": xm,
        "stock_mean": ym,
        "market_sxx": sxx,
        "se_alpha": se_alpha,
        "se_beta": se_beta,
        "t_alpha": t_alpha,
        "t_beta": t_beta,
        "p_alpha": p_alpha,
        "p_beta": p_beta,
    }


def _market_model(stock_r: pd.Series, market_r: pd.Series) -> tuple[float, float, float, int]:
    """Backward-compatible compact market-model result."""
    d = _market_model_diagnostics(stock_r, market_r)
    return d["alpha"], d["beta"], d["residual_std"], d["observations"]


def _two_sided_p_value(t_stat: float, df_resid: int) -> float | None:
    if not math.isfinite(t_stat):
        return None
    return float(2.0 * student_t.sf(abs(float(t_stat)), int(df_resid)))


def run_event_study(
    ticker: str,
    event_date: str,
    market: str | None = None,
    region: str | None = None,
    estimation_start: int = EST_START,
    estimation_end: int = EST_END,
    event_start: int = EVENT_START,
    event_end: int = EVENT_END,
) -> dict:
    """Run a one-asset research-grade market-model event study on real data.

    Each ticker is estimated independently. The 100-session estimation sample
    is separated from the event window, and no synthetic post-event prices are
    generated when the selected event is too recent.
    """
    if event_start >= event_end:
        raise ValueError("Некорректное окно события")

    event_target = _parse_event_date(event_date)
    if event_target.date() > date.today():
        raise ValueError("Event Study работает только по уже произошедшим событиям: выберите сегодняшнюю или прошлую дату")
    cache_key = (ticker.upper(), event_date, market or "", region or "", estimation_start, estimation_end, event_start, event_end)
    now = time.time()
    with _event_cache_lock:
        cached = _event_cache.get(cache_key)
        if cached and now - cached[0] < EVENT_CACHE_TTL:
            return cached[1]

    # ~320 calendar days before the event comfortably covers -110..-11.
    # +5 event sessions need only a small forward range; 35 calendar days is
    # deliberately bounded and avoids unrelated future history.
    range_start = (event_target - pd.Timedelta(days=320)).strftime("%Y-%m-%d")
    today = pd.Timestamp(date.today())
    requested_end = event_target + pd.Timedelta(days=35)
    range_end_ts = min(today + pd.Timedelta(days=1), requested_end + pd.Timedelta(days=1))
    range_end = range_end_ts.strftime("%Y-%m-%d")

    bench = benchmark_for_market(market, region)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="event-market-data") as pool:
        stock_future = pool.submit(fetch_history_range, ticker, range_start, range_end, 7)
        market_future = pool.submit(fetch_history_range, bench, range_start, range_end, 7)
        stock_hist = stock_future.result()
        market_hist = market_future.result()

    stock_px = _to_df(stock_hist)
    if stock_px.empty:
        raise ValueError(f"Нет реальных historical prices для {ticker} в окне события")

    market_px = _to_df(market_hist)
    if market_px.empty and bench != "^GSPC":
        market_hist = fetch_history_range("^GSPC", range_start, range_end, timeout=7)
        market_px = _to_df(market_hist)
        bench = "^GSPC"
    if market_px.empty:
        raise ValueError(f"Нет реальных historical data для рыночного индекса {bench}")

    stock_r, market_r = _returns(stock_px), _returns(market_px)
    common = stock_r.index.intersection(market_r.index)
    if len(common) < 120:
        raise ValueError("Нужно больше совместимых торговых дней для event study")

    event_day = _nearest_trading_date(common, event_target)
    pos = common.get_loc(event_day)
    if isinstance(pos, slice):
        pos = pos.start
    est_left = pos + estimation_start
    est_right = pos + estimation_end
    evt_left = pos + event_start
    evt_right_requested = pos + event_end
    if est_left < 0 or evt_left < 0:
        raise ValueError("Недостаточно исторических данных до выбранной даты события")

    evt_right = min(evt_right_requested, len(common) - 1)
    if evt_right < evt_left:
        raise ValueError("Недостаточно данных после выбранной даты события")

    est_dates = common[est_left:est_right + 1]
    if len(est_dates) != 100:
        raise ValueError(f"Окно оценки должно содержать 100 торговых дней, сейчас: {len(est_dates)}")
    est_stock = stock_r.reindex(est_dates)
    est_market = market_r.reindex(est_dates)
    regression = _market_model_diagnostics(est_stock, est_market)
    alpha = float(regression["alpha"])
    beta = float(regression["beta"])
    se = float(regression["residual_std"])
    n = int(regression["observations"])
    df_resid = int(regression["df_resid"])
    xbar = float(regression["market_mean"])
    sxx = float(regression["market_sxx"])
    residual_variance = float(regression["residual_variance"])

    # Independent second OLS calculation before releasing the result.
    verify_df = pd.concat([est_stock.rename("stock"), est_market.rename("market")], axis=1).dropna()
    X = np.column_stack([np.ones(len(verify_df)), verify_df["market"].to_numpy(float)])
    y = verify_df["stock"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    alpha_check, beta_check = float(coef[0]), float(coef[1])
    if abs(alpha - alpha_check) > 1e-10 or abs(beta - beta_check) > 1e-10:
        raise RuntimeError("Event Study integrity check failed: market-model regression mismatch")

    evt_dates = common[evt_left:evt_right + 1]
    rows = []
    raw_ars: list[float] = []
    event_market_returns: list[float] = []
    car = 0.0
    for idx, dt in enumerate(evt_dates):
        relative_day = event_start + idx
        actual = float(stock_r.loc[dt])
        market_ret = float(market_r.loc[dt])
        expected = alpha + beta * market_ret
        ar = actual - expected
        raw_ars.append(ar)
        event_market_returns.append(market_ret)
        car += ar

        # Research-grade forecast-error variance: residual noise + parameter
        # estimation uncertainty in alpha/beta.
        var_ar = residual_variance * (
            1.0 + 1.0 / n + ((market_ret - xbar) ** 2) / sxx
        )
        se_ar = math.sqrt(max(var_ar, 0.0))
        tstat = ar / se_ar if se_ar > 1e-14 else float("nan")
        p_value = _two_sided_p_value(tstat, df_resid)

        # Cumulative abnormal-return variance over the observed prefix.
        L = len(raw_ars)
        market_dev_sum = float(np.sum(np.asarray(event_market_returns, dtype=float) - xbar))
        var_car = residual_variance * (
            L + (L * L) / n + (market_dev_sum * market_dev_sum) / sxx
        )
        se_car = math.sqrt(max(var_car, 0.0))
        t_car = car / se_car if se_car > 1e-14 else float("nan")
        p_car = _two_sided_p_value(t_car, df_resid)

        rows.append({
            "relative_day": relative_day,
            "date": dt.strftime("%Y-%m-%d"),
            "stock_return_pct": round(actual * 100, 5),
            "market_return_pct": round(market_ret * 100, 5),
            "expected_return_pct": round(expected * 100, 5),
            "abnormal_return_pct": round(ar * 100, 5),
            "se_ar_pct": round(se_ar * 100, 5),
            "t_stat": round(float(tstat), 4) if math.isfinite(tstat) else None,
            "p_value": round(float(p_value), 6) if p_value is not None else None,
            "significant": bool(p_value is not None and p_value < 0.05),
            "car_pct": round(car * 100, 5),
            "car_se_pct": round(se_car * 100, 5),
            "car_t_stat": round(float(t_car), 4) if math.isfinite(t_car) else None,
            "car_p_value": round(float(p_car), 6) if p_car is not None else None,
            "car_significant": bool(p_car is not None and p_car < 0.05),
        })

    car_check = 0.0
    for dt in evt_dates:
        car_check += float(stock_r.loc[dt]) - (alpha_check + beta_check * float(market_r.loc[dt]))
    if abs(car - car_check) > 1e-10:
        raise RuntimeError("Event Study integrity check failed: CAR mismatch")

    final_car = float(car)
    event_row = next((r for r in rows if r["relative_day"] == 0), None)
    event_ar = event_row["abnormal_return_pct"] if event_row else None
    event_t = event_row["t_stat"] if event_row else None
    event_p = event_row["p_value"] if event_row else None
    final_row = rows[-1] if rows else {}
    available_post_days = max(0, min(event_end, len(common) - 1 - pos))
    complete = evt_right >= evt_right_requested
    context = {
        "available": False,
        "summary": "AR/CAR рассчитаны только по фактическим рыночным данным. Новостной и фундаментальный контекст не блокирует основной расчёт.",
        "official_source": None,
    }

    regression_public = {
        "observations": n,
        "degrees_of_freedom": df_resid,
        "alpha": alpha,
        "alpha_pct_daily": alpha * 100.0,
        "se_alpha": regression["se_alpha"],
        "se_alpha_pct_daily": regression["se_alpha"] * 100.0,
        "t_alpha": regression["t_alpha"],
        "p_alpha": regression["p_alpha"],
        "beta": beta,
        "se_beta": regression["se_beta"],
        "t_beta": regression["t_beta"],
        "p_beta": regression["p_beta"],
        "r_squared": regression["r_squared"],
        "sse": regression["sse"],
        "residual_variance": regression["residual_variance"],
        "residual_std": regression["residual_std"],
        "residual_std_pct_daily": regression["residual_std"] * 100.0,
    }

    result = {
        "ticker": ticker,
        "benchmark": bench,
        "event_date_requested": event_target.strftime("%Y-%m-%d"),
        "event_date_used": event_day.strftime("%Y-%m-%d"),
        "event_day_definition": "t=0 = выбранная дата события, выровненная на фактическую торговую сессию; -5 = пять торговых сессий до; +5 = пять после",
        "after_close_convention": "Если публикация вышла после закрытия рынка, t=0 не переносится; основная ценовая реакция может проявиться на t=+1.",
        "estimation_window": {"start": estimation_start, "end": estimation_end, "observations": n},
        "event_window": {
            "start": event_start,
            "end_requested": event_end,
            "end_used": event_start + len(rows) - 1,
            "observations": len(rows),
            "complete": bool(complete),
            "available_post_event_days": int(available_post_days),
        },
        "data_warning": None if complete else (
            f"После дня 0 доступно только +{available_post_days} торговых дней. "
            f"Расчёт остановлен на последнем реальном наблюдении; будущие дни не моделируются."
        ),
        "alpha": alpha,
        "alpha_pct_daily": alpha * 100,
        "beta": beta,
        "se": se,
        "se_pct_daily": se * 100,
        "regression": regression_public,
        "event_day_ar_pct": event_ar,
        "event_day_t_stat": event_t,
        "event_day_p_value": event_p,
        "car_event_window_pct": final_car * 100,
        "car_event_window_t_stat": final_row.get("car_t_stat"),
        "car_event_window_p_value": final_row.get("car_p_value"),
        "event_day_significant": bool(event_p is not None and event_p < 0.05),
        "car_event_window_significant": bool(final_row.get("car_p_value") is not None and final_row.get("car_p_value") < 0.05),
        "report_context": context,
        "thesis": _build_thesis(ticker, event_day, event_ar, event_t, event_p, final_car, final_row.get("car_p_value"), context, complete, available_post_days),
        "observations": rows,
        "data_provenance": {
            "stock_prices": "real adjusted historical close",
            "benchmark_prices": "real historical market-index close",
            "requested_range": {"start": range_start, "end_exclusive": range_end},
            "synthetic_prices_used": False,
        },
        "verification": {
            "passed": True,
            "regression_recomputed": True,
            "car_recomputed": True,
            "alpha_abs_diff": abs(alpha - alpha_check),
            "beta_abs_diff": abs(beta - beta_check),
            "car_abs_diff": abs(car - car_check),
        },
        "methodology": [
            "Each selected asset is calculated independently against its market benchmark.",
            "Estimation window: -110 to -11 trading sessions (100 observations).",
            "Main event window: -5 to +5 trading sessions (11 observations when complete).",
            "Market model: R_i,t = alpha + beta * R_m,t + e_t.",
            "Expected return: E(R_i,t) = alpha + beta * R_m,t.",
            "Abnormal return: AR_t = R_i,t - E(R_i,t).",
            "SE(AR) includes residual variance plus alpha/beta estimation uncertainty.",
            "CAR_t is cumulative AR from -5 through t; CAR significance includes estimation uncertainty.",
            "Two-sided p-values use the Student-t distribution with N-2 residual degrees of freedom.",
            "If an announcement is after market close, t=0 remains the report date; reaction can appear at t=+1.",
            "Only real historical prices are used. Incomplete post-event windows stop at the latest real observation.",
            "Before returning the result, alpha/beta and CAR are independently recomputed and cross-checked.",
        ],
    }
    with _event_cache_lock:
        _event_cache[cache_key] = (time.time(), result)
    return result


def _build_thesis(
    ticker: str,
    event_day: pd.Timestamp,
    ar_pct: float | None,
    tstat: float | None,
    p_value: float | None,
    car_pct: float,
    car_p_value: float | None,
    context: dict,
    complete: bool,
    available_post_days: int,
) -> str:
    if ar_pct is None:
        return f"Для {ticker} не удалось получить AR в день 0."
    direction = "положительную" if ar_pct > 0 else "отрицательную" if ar_pct < 0 else "нейтральную"
    sig = "статистически значимую" if p_value is not None and p_value < 0.05 else "не получившую статистического подтверждения"
    t_text = f"t = {tstat:.2f}" if tstat is not None else "t = n/a"
    p_text = f"p = {p_value:.4f}" if p_value is not None else "p = n/a"
    car_sig = "статистически значим" if car_p_value is not None and car_p_value < 0.05 else "статистически не подтверждён"
    context_note = context.get("summary") or "Контекст отчётности недоступен."
    completeness = (
        "Окно -5…+5 полностью наблюдается."
        if complete else
        f"Важно: данные после отчёта пока неполные — доступны только +{available_post_days} торговых дней."
    )
    return (
        f"Инвестиционный тезис: публикация отчётности {event_day.strftime('%Y-%m-%d')} для {ticker} сопровождалась "
        f"{direction} abnormal return {ar_pct:+.2f}% в день 0; эффект {sig} ({t_text}, {p_text}). "
        f"CAR за доступное окно -5…+5 составил {car_pct:+.2f}% и {car_sig}. "
        f"Краткий фундаментальный/новостной контекст: {context_note} {completeness} "
        f"Если публикация была после закрытия рынка, реакция может концентрироваться на t=+1. "
        f"Это исследовательский сигнал, а не доказательство причинности или гарантия будущей доходности."
    )
