"""Out-of-sample Historical Model Validation for GBM and Bootstrap.

Each validation window is deliberately split into a three-calendar-year training
sample and one untouched test year:

2014-2016 -> 2017
2015-2017 -> 2018
2016-2018 -> 2019
2017-2019 -> 2020
2018-2020 -> 2021
2019-2021 -> 2022
2020-2022 -> 2023
2021-2023 -> 2024
2022-2024 -> 2025

The end year is generated automatically from the last fully completed calendar
year, so a new validation window appears after each year-end without a code
change.

For each window the module:
1. uses only adjusted historical prices available in the training period;
2. converts foreign assets to USD before returns are estimated;
3. estimates the historical U.S. 13-week T-bill proxy as of the training end;
4. runs the existing Markowitz optimizer and freezes its exact weights;
5. runs the same GBM / stationary-bootstrap assumptions used by the app
   (10,000 simulations, 252 trading days, buy-and-hold, bootstrap mean block 21);
6. only then opens the untouched test year and computes the realized buy-and-hold
   wealth path from actual adjusted closes;
7. compares actual return with each model's P05/P50/P95 and percentile.

Direct bonds are intentionally not labelled "real" because the project does not
currently have exact historical total-return price series for individual bonds.
For exact historical validation use listed bond ETFs (TLT, IEF, BND, etc.).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
import math
import threading
import time
import uuid
from typing import Iterable

import numpy as np
import pandas as pd

from config.markets import asset_type_for_ticker, symbol_market
from fetcher.chart import fetch_history_range
from fetcher.fx import fetch_fx_history_usd_range
from portfolio.optimizer import (
    TRADING_DAYS,
    analyze_portfolio,
    simulate_portfolio_gbm,
    simulate_portfolio_bootstrap,
    summarize_terminal_distribution,
)

SIMULATIONS = 10_000
HORIZON_DAYS = 252
BOOTSTRAP_BLOCK = 21
VALIDATION_CACHE_TTL = 30 * 60
_validation_cache: dict[tuple, tuple[float, dict]] = {}
_validation_cache_lock = threading.Lock()

FIRST_VALIDATION_YEAR = 2017
LAST_COMPLETED_YEAR = date.today().year - 1

VALIDATION_WINDOWS = tuple(
    (f"{year-3}-01-01", f"{year-1}-12-31", f"{year}-01-01", f"{year}-12-31")
    for year in range(FIRST_VALIDATION_YEAR, LAST_COMPLETED_YEAR + 1)
)

OVERALL_START = "2013-12-01"
# Provider end is exclusive; keep a short January buffer after the last
# completed calendar year. This updates automatically at each year-end.
OVERALL_END = f"{LAST_COMPLETED_YEAR + 1}-01-10"


@dataclass(frozen=True)
class AssetMeta:
    ticker: str
    asset_type: str
    market: str
    currency: str


def _currency_for_ticker(ticker: str) -> str:
    """Stable quote-currency mapping for the six supported exchange universes.

    A GBP/GBp scale difference is constant and therefore cancels in returns; GBP
    is sufficient for USD-normalized historical return calculations.
    """
    t = ticker.upper()
    if t.endswith(".L"):
        return "GBP"
    if t.endswith(".PA"):
        return "EUR"
    if t.endswith(".T"):
        return "JPY"
    if t.endswith(".AX"):
        return "AUD"
    if t.endswith(".KZ"):
        return "KZT"
    return "USD"


def _history_to_series(history: dict) -> pd.Series:
    dates = history.get("dates") or []
    closes = history.get("closes") or []
    if len(dates) < 2 or len(closes) < 2:
        return pd.Series(dtype="float64")
    s = pd.Series(
        pd.to_numeric(pd.Series(closes), errors="coerce").to_numpy(),
        index=pd.to_datetime(dates, errors="coerce"),
        dtype="float64",
    ).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s > 0]


def _to_history_payload(series: pd.Series) -> dict:
    s = series.dropna().sort_index()
    return {
        "dates": [str(x.date()) for x in s.index],
        "closes": [float(x) for x in s.to_numpy(float)],
    }


def _usd_normalize(local_prices: pd.Series, currency: str, fx: pd.Series | None) -> pd.Series:
    if currency == "USD":
        return local_prices.copy()
    if fx is None or fx.empty:
        raise ValueError(f"Нет исторического FX {currency}/USD для преобразования в базовую валюту USD")
    # Forward-fill only. A future FX observation is never moved backward.
    aligned = fx.reindex(local_prices.index).ffill()
    out = (local_prices * aligned).replace([np.inf, -np.inf], np.nan).dropna()
    if out.empty:
        raise ValueError(f"Не удалось совместить цены с историческим FX {currency}/USD")
    return out


def _asset_meta(ticker: str) -> AssetMeta:
    at = asset_type_for_ticker(ticker)
    return AssetMeta(ticker=ticker, asset_type=at, market=symbol_market(ticker), currency=_currency_for_ticker(ticker))


def _preload_prices(tickers: list[str]) -> tuple[dict[str, pd.Series], dict[str, AssetMeta], dict]:
    metas = {t: _asset_meta(t) for t in tickers}
    direct_bonds = [t for t, m in metas.items() if m.asset_type == "bond"]
    if direct_bonds:
        raise ValueError(
            "Historical Model Validation требует фактическую historical total-return/adjusted-price series. "
            "Для прямых облигаций она сейчас недоступна без подмены реальных данных модельным duration-proxy: "
            + ", ".join(direct_bonds)
            + ". Для точной проверки выберите bond ETF (например TLT, IEF, BND, AGG) или акции/ETF."
        )

    local: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}

    def fetch_one(t: str):
        h = fetch_history_range(t, OVERALL_START, OVERALL_END, timeout=7)
        s = _history_to_series(h)
        if s.empty:
            raise ValueError("нет adjusted historical prices за 2014-2025")
        return t, s

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(tickers)))) as pool:
        futures = {pool.submit(fetch_one, t): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                key, s = fut.result()
                local[key] = s
            except Exception as exc:
                errors[t] = str(exc)

    # Partial-universe policy: one unavailable ticker must not kill every year.
    # It is retained in provenance and can become eligible in later windows if
    # history exists.

    currencies = sorted({m.currency for m in metas.values() if m.currency != "USD"})
    fx_map: dict[str, pd.Series | None] = {}
    if currencies:
        with ThreadPoolExecutor(max_workers=min(4, len(currencies))) as pool:
            futures = {pool.submit(fetch_fx_history_usd_range, c, OVERALL_START, OVERALL_END): c for c in currencies}
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    fx_map[c] = fut.result()
                except Exception:
                    fx_map[c] = None

    usd: dict[str, pd.Series] = {}
    for t, s in local.items():
        m = metas[t]
        try:
            usd[t] = _usd_normalize(s, m.currency, fx_map.get(m.currency))
        except Exception as exc:
            errors[t] = str(exc)
            continue

    provenance = {
        "price_source": "Yahoo Finance adjusted historical close (KASE fallback only where actually available)",
        "base_currency": "USD",
        "fx_policy": "historical FX, forward-fill only; no backward fill",
        "unavailable_selected_assets": errors,
    }
    return usd, metas, provenance


def _fetch_historical_rf() -> pd.Series:
    h = fetch_history_range("^IRX", OVERALL_START, OVERALL_END, timeout=7)
    s = _history_to_series(h)
    if s.empty:
        raise ValueError("Не удалось получить historical ^IRX для risk-free rate без look-ahead")
    return s


def _rf_as_of(irx: pd.Series, train_end: str) -> tuple[float, str]:
    end = pd.Timestamp(train_end)
    available = irx[irx.index <= end]
    # Restrict to a recent pre-cutoff observation so a stale ancient yield is not
    # silently used as the risk-free rate for a later training date.
    if available.empty:
        raise ValueError(f"Нет U.S. risk-free observation до {train_end}")
    dt = available.index[-1]
    if (end - dt).days > 31:
        raise ValueError(f"U.S. risk-free rate слишком старая перед {train_end}: последняя дата {dt.date()}")
    rate = float(available.iloc[-1])
    if not math.isfinite(rate) or not (-5.0 < rate < 30.0):
        raise ValueError(f"Некорректная historical U.S. risk-free rate: {rate}")
    return rate, str(dt.date())


def _window_prices(prices: pd.Series, start: str, end: str) -> pd.Series:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    return prices[(prices.index >= lo) & (prices.index <= hi)].copy()


def _realized_buy_and_hold(
    usd_prices: dict[str, pd.Series],
    tickers: list[str],
    weights: np.ndarray,
    train_end: str,
    test_end: str,
    amount_usd: float,
) -> dict:
    cutoff = pd.Timestamp(train_end)
    end = pd.Timestamp(test_end)
    factors: dict[str, pd.Series] = {}
    asset_returns = []

    for i, t in enumerate(tickers):
        s = usd_prices[t].sort_index()
        before = s[s.index <= cutoff]
        after = s[(s.index > cutoff) & (s.index <= end)]
        if before.empty or after.empty:
            raise ValueError(f"{t}: нет фактических цен на границе {train_end} -> {test_end}")
        start_date = before.index[-1]
        start_px = float(before.iloc[-1])
        if start_px <= 0:
            raise ValueError(f"{t}: некорректная стартовая цена")
        f = (after / start_px).replace([np.inf, -np.inf], np.nan).dropna()
        # Synthetic value 1 at the known training cutoff is only a normalization
        # anchor; all test movements are still actual observed adjusted closes.
        f = pd.concat([pd.Series([1.0], index=pd.DatetimeIndex([cutoff])), f])
        f = f[~f.index.duplicated(keep="last")].sort_index()
        factors[t] = f
        asset_returns.append({
            "ticker": t,
            "weight_pct": round(float(weights[i]) * 100.0, 4),
            "start_price_date": str(start_date.date()),
            "end_price_date": str(after.index[-1].date()),
            "actual_return_pct": round((float(after.iloc[-1]) / start_px - 1.0) * 100.0, 3),
        })

    factor_df = pd.concat(factors, axis=1).sort_index().ffill()
    factor_df = factor_df.loc[(factor_df.index >= cutoff) & (factor_df.index <= end)]
    factor_df = factor_df.dropna(how="any")
    if len(factor_df) < 20:
        raise ValueError("Недостаточно совместных фактических торговых дат в test period")
    portfolio_factor = factor_df.to_numpy(float) @ weights
    if not np.all(np.isfinite(portfolio_factor)):
        raise ValueError("Actual buy-and-hold path содержит невалидные значения")

    final_factor = float(portfolio_factor[-1])
    wealth = amount_usd * portfolio_factor
    peaks = np.maximum.accumulate(wealth)
    drawdown = wealth / peaks - 1.0
    max_drawdown_pct = float(np.min(drawdown) * 100.0)
    return {
        "actual_return_pct": round((final_factor - 1.0) * 100.0, 3),
        "ending_wealth_usd": round(amount_usd * final_factor, 2),
        "profit_loss_usd": round(amount_usd * (final_factor - 1.0), 2),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "observations": int(len(factor_df) - 1),
        "last_market_date": str(factor_df.index[-1].date()),
        "asset_results": asset_returns,
    }


def _forecast_summary(result: dict, terminals: Iterable[float], actual_wealth: float, amount: float) -> dict:
    base = _forecast_only_summary(result, terminals, amount)
    return _comparison_with_actual(base, terminals, actual_wealth)


def _validate_one_window(
    tickers: list[str],
    amount_usd: float,
    usd_prices: dict[str, pd.Series],
    metas: dict[str, AssetMeta],
    irx: pd.Series,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
    objective: str,
    concentration_mode: str,
    covariance_method: str = "ledoit_wolf",
) -> dict:
    rf_pct, rf_date = _rf_as_of(irx, train_end)

    train_series: dict[str, pd.Series] = {}
    excluded_assets: list[dict] = []
    for t in tickers:
        full = usd_prices.get(t)
        if full is None or full.empty:
            excluded_assets.append({"ticker": t, "reason": "historical data unavailable"})
            continue
        tr = _window_prices(full, train_start, train_end)
        if len(tr) < 190:
            excluded_assets.append({"ticker": t, "reason": f"insufficient training history ({len(tr)} observations)"})
            continue
        # Need an observable next-year path for ex-post validation. This is an
        # availability check, not a return-based security selection rule.
        te = _window_prices(full, test_start, test_end)
        if len(te) < 20:
            excluded_assets.append({"ticker": t, "reason": f"insufficient/no test-year history ({len(te)} observations)"})
            continue
        train_series[t] = tr
    eligible = list(train_series)
    if len(eligible) < 2:
        reasons = "; ".join(f"{x['ticker']}: {x['reason']}" for x in excluded_assets)
        raise ValueError("Недостаточно eligible assets для этого года. " + reasons)
    max_train_dates = {t: str(series.index.max().date()) for t, series in train_series.items()}

    def chart_fetcher(ticker: str, period: str = "5y"):
        return _to_history_payload(train_series[ticker.upper()])

    def record_fetcher(ticker: str):
        t = ticker.upper()
        m = metas[t]
        # Price data are already USD-normalized. Marking currency USD prevents a
        # second FX conversion inside the shared Markowitz engine.
        return {
            "ticker": t,
            "name": t,
            "asset_type": m.asset_type,
            "market": m.market,
            "region": m.market,
            "currency": "USD",
        }

    result = analyze_portfolio(
        eligible,
        amount_usd,
        record_fetcher=record_fetcher,
        chart_fetcher=chart_fetcher,
        curve_history=pd.DataFrame(),
        include_historical_returns=True,
        objective=objective,
        risk_free_rate_pct=rf_pct,
        concentration_mode=concentration_mode,
        covariance_method=covariance_method,
        include_etf_holdings=False,  # current ETF holdings would be look-ahead
    )
    historical_returns = result.pop("_historical_returns", [])
    engine = result.get("_engine") or {}
    weights = np.asarray(engine.get("weights") or [], dtype=float)
    names = list(engine.get("names") or eligible)
    if len(weights) != len(names):
        raise ValueError("Markowitz snapshot missing exact weights")

    actual = _realized_buy_and_hold(usd_prices, names, weights, train_end, test_end, amount_usd)

    # Use the exact same core simulation functions as the main application, but
    # skip chart/asset payloads for speed. Seeds are fixed by test year so a
    # repeated validation is reproducible.
    alloc_by_ticker = {str(x.get("ticker") or "").upper(): x for x in result.get("allocation", [])}
    met_by_ticker = {str(x.get("ticker") or "").upper(): x for x in result.get("individual_metrics", [])}
    allocation = []
    metrics = []
    for i, t in enumerate(names):
        a = dict(alloc_by_ticker.get(t, {"ticker": t}))
        a["weight"] = float(weights[i])
        a["weight_pct"] = float(weights[i]) * 100.0
        allocation.append(a)
        m = dict(met_by_ticker.get(t, {"ticker": t}))
        m["expected_return_pct"] = float(engine["expected_returns"][i]) * 100.0
        metrics.append(m)

    test_year = int(test_start[:4])
    gbm = simulate_portfolio_gbm(
        amount_usd,
        allocation,
        metrics,
        engine["covariance"],
        horizon_days=HORIZON_DAYS,
        simulations=SIMULATIONS,
        seed=10_000 + test_year,
        summary_only=True,
        return_terminal_values=True,
        return_asset_terminal_values=True,
    )
    bootstrap = simulate_portfolio_bootstrap(
        amount_usd,
        allocation,
        historical_returns,
        horizon_days=HORIZON_DAYS,
        simulations=SIMULATIONS,
        block_size=BOOTSTRAP_BLOCK,
        seed=20_000 + test_year,
        summary_only=True,
        return_terminal_values=True,
    )
    gbm_terminals = gbm.pop("_terminal_values", [])
    boot_terminals = bootstrap.pop("_terminal_values", [])

    # Independent no-look-ahead integrity checks before the response is released.
    if any(d is None or d > train_end for d in max_train_dates.values()):
        raise RuntimeError("No-look-ahead verification failed: training contains a post-cutoff date")
    if actual["last_market_date"] > test_end:
        raise RuntimeError("Validation integrity failed: actual path extends past test end")
    if abs(float(weights.sum()) - 1.0) > 1e-8 or np.any(weights < -1e-10):
        raise RuntimeError("Portfolio integrity failed: invalid frozen Markowitz weights")

    allocation_public = [{
        "ticker": names[i],
        "weight_pct": round(float(weights[i]) * 100.0, 4),
        "amount_usd": round(float(amount_usd) * float(weights[i]), 2),
    } for i in range(len(names))]

    return {
        "training_period": {"start": train_start, "end": train_end},
        "test_period": {"start": test_start, "end": test_end, "year": test_year},
        "risk_free": {
            "rate_pct": round(float(rf_pct), 4),
            "as_of": rf_date,
            "instrument": "13-week U.S. Treasury bill (^IRX historical)",
        },
        "universe": {
            "selected": tickers,
            "eligible": eligible,
            "excluded": excluded_assets,
        },
        "portfolio": {
            "objective": objective,
            "covariance_method": covariance_method,
            "concentration_mode": concentration_mode,
            "allocation": allocation_public,
            "expected_return_pct": result.get("portfolio", {}).get("expected_return_pct"),
            "historical_risk_pct": result.get("portfolio", {}).get("historical_risk_pct"),
            "sharpe_ratio": result.get("portfolio", {}).get("sharpe_ratio"),
        },
        "gbm": _forecast_summary(gbm, gbm_terminals, actual["ending_wealth_usd"], amount_usd),
        "bootstrap": _forecast_summary(bootstrap, boot_terminals, actual["ending_wealth_usd"], amount_usd),
        "actual": actual,
        "integrity": {
            "no_lookahead_verified": True,
            "training_max_dates": max_train_dates,
            "frozen_weights_verified": True,
            "same_buy_and_hold_policy": True,
            "same_horizon_days": HORIZON_DAYS,
            "same_simulations": SIMULATIONS,
            "bootstrap_mean_block_days": BOOTSTRAP_BLOCK,
        },
    }


def run_historical_model_validation(
    tickers: list[str],
    amount_usd: float,
    *,
    objective: str = "max_sharpe",
    concentration_mode: str = "constrained",
    covariance_method: str = "ledoit_wolf",
) -> dict:
    selected = list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()))
    if not selected:
        raise ValueError("Выберите хотя бы один актив")
    try:
        amount = float(amount_usd)
    except Exception as exc:
        raise ValueError("Некорректный стартовый капитал") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Стартовый капитал должен быть больше 0")
    cache_key = (tuple(selected), round(amount, 2), objective, concentration_mode, covariance_method, LAST_COMPLETED_YEAR)
    now = time.time()
    with _validation_cache_lock:
        cached = _validation_cache.get(cache_key)
        if cached and now - cached[0] < VALIDATION_CACHE_TTL:
            return cached[1]

    # Price/FX history and historical U.S. T-bill history are independent I/O.
    # Start them together so live validation does not pay their network latency
    # sequentially. The numerical work below begins only after both are ready.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="hval-preload") as pool:
        prices_future = pool.submit(_preload_prices, selected)
        rf_future = pool.submit(_fetch_historical_rf)
        usd_prices, metas, provenance = prices_future.result()
        irx = rf_future.result()

    def validate_window(window):
        train_start, train_end, test_start, test_end = window
        try:
            row = _validate_one_window(
                selected, amount, usd_prices, metas, irx,
                train_start, train_end, test_start, test_end,
                objective, concentration_mode, covariance_method,
            )
            row["status"] = "ok"
            return int(test_start[:4]), row
        except Exception as exc:
            return int(test_start[:4]), {
                "status": "error",
                "training_period": {"start": train_start, "end": train_end},
                "test_period": {"start": test_start, "end": test_end, "year": int(test_start[:4])},
                "error": str(exc),
            }

    # All market I/O is already shared/preloaded; run independent numerical
    # windows concurrently. Order is restored by test year.
    rows_by_year = {}
    with ThreadPoolExecutor(max_workers=min(3, len(VALIDATION_WINDOWS)), thread_name_prefix="hval-window") as pool:
        futures = [pool.submit(validate_window, w) for w in VALIDATION_WINDOWS]
        for fut in as_completed(futures):
            year, row = fut.result(); rows_by_year[year] = row
    windows = [rows_by_year[int(w[2][:4])] for w in VALIDATION_WINDOWS]

    good = [w for w in windows if w.get("status") == "ok"]
    if not good:
        # Return all period-level diagnostics as a successful structured response;
        # the UI can explain exactly why the chosen assets could not be validated.
        summary = {
            "successful_windows": 0,
            "total_windows": len(windows),
            "gbm_coverage_pct": None,
            "bootstrap_coverage_pct": None,
        }
    else:
        summary = {
            "successful_windows": len(good),
            "total_windows": len(windows),
            "gbm_coverage_pct": round(100.0 * sum(bool(w["gbm"]["actual_inside_90_interval"]) for w in good) / len(good), 2),
            "bootstrap_coverage_pct": round(100.0 * sum(bool(w["bootstrap"]["actual_inside_90_interval"]) for w in good) / len(good), 2),
            "avg_abs_error_gbm_p50_pct_points": round(float(np.mean([abs(w["gbm"]["p50_return_pct"] - w["actual"]["actual_return_pct"]) for w in good])), 3),
            "avg_abs_error_bootstrap_p50_pct_points": round(float(np.mean([abs(w["bootstrap"]["p50_return_pct"] - w["actual"]["actual_return_pct"]) for w in good])), 3),
        }

    response = {
        "module": "Historical Model Validation",
        "selected": selected,
        "amount_usd": round(amount, 2),
        "base_currency": "USD",
        "windows": windows,
        "summary": summary,
        "provenance": provenance,
        "methodology": {
            "training": "3 calendar years, training data only",
            "test": "next untouched calendar year",
            "markowitz": "re-estimated separately inside every training window; exact weights frozen before test is opened",
            "covariance_method": covariance_method,
            "universe_policy": "assets without sufficient history are excluded only for affected years and automatically re-enter when eligible",
            "gbm": f"{SIMULATIONS:,} paths, {HORIZON_DAYS} trading days, buy-and-hold",
            "bootstrap": f"{SIMULATIONS:,} paths, {HORIZON_DAYS} trading days, stationary bootstrap mean block {BOOTSTRAP_BLOCK}",
            "actual": "real adjusted-close buy-and-hold path in USD for stocks/ETFs",
            "no_lookahead": True,
        },
    }
    with _validation_cache_lock:
        _validation_cache[cache_key] = (time.time(), response)
    return response


# ---------------------------------------------------------------------------
# Interactive single-window validation flow used by the v14 screener modal.
# The forecast endpoint is intentionally separated from the actual-market
# reveal endpoint so test-period prices are not fetched until the user asks to
# open Actual Market Results.
# ---------------------------------------------------------------------------

VALIDATION_WINDOWS_BY_YEAR = {
    year: (f"{year-3}-01-01", f"{year-1}-12-31", f"{year}-01-01", f"{year}-12-31")
    for year in range(FIRST_VALIDATION_YEAR, LAST_COMPLETED_YEAR + 1)
}

_INTERACTIVE_SESSION_TTL = 30 * 60
_interactive_sessions: dict[str, tuple[float, dict]] = {}
_interactive_sessions_lock = threading.Lock()


def _exclusive_day_after(day: str) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def _bounded_usd_prices(
    tickers: list[str],
    start: str,
    end_inclusive: str,
    *,
    min_observations: int = 2,
    allow_partial: bool = False,
) -> tuple[dict[str, pd.Series], dict[str, AssetMeta], dict]:
    """Fetch only the requested historical range and normalize to USD.

    No price observation after ``end_inclusive`` is requested.  A small
    pre-start FX buffer is allowed only to forward-fill the first local-market
    session; it contains information known before the training/test start.
    """
    selected = list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()))
    metas = {t: _asset_meta(t) for t in selected}
    direct_bonds = [t for t, m in metas.items() if m.asset_type == "bond"]
    if direct_bonds:
        raise ValueError(
            "Historical Model Validation требует реальную historical price/total-return series. "
            "Для прямых облигаций такая серия сейчас не поддерживается без модельной подмены: "
            + ", ".join(direct_bonds)
            + ". Используйте акции, ETF или bond ETF."
        )

    start_ts = pd.Timestamp(start)
    fetch_start = (start_ts - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    fetch_end = _exclusive_day_after(end_inclusive)
    local: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}

    def fetch_one(t: str):
        h = fetch_history_range(t, fetch_start, fetch_end, timeout=6)
        s = _history_to_series(h)
        if s.empty:
            raise ValueError(f"нет historical prices за {start}…{end_inclusive}")
        return t, s

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(selected)))) as pool:
        futures = {pool.submit(fetch_one, t): t for t in selected}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                key, series = fut.result()
                local[key] = series
            except Exception as exc:
                errors[t] = str(exc)
    if errors and not allow_partial:
        raise ValueError("Не удалось получить реальные historical prices: " + "; ".join(f"{t}: {e}" for t, e in errors.items()))

    currencies = sorted({m.currency for m in metas.values() if m.currency != "USD"})
    fx_map: dict[str, pd.Series | None] = {}
    if currencies:
        with ThreadPoolExecutor(max_workers=min(4, len(currencies))) as pool:
            futures = {
                pool.submit(fetch_fx_history_usd_range, c, fetch_start, fetch_end): c
                for c in currencies
            }
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    fx_map[c] = fut.result()
                except Exception:
                    fx_map[c] = None

    usd: dict[str, pd.Series] = {}
    lo, hi = pd.Timestamp(start), pd.Timestamp(end_inclusive)
    for t, series in local.items():
        m = metas[t]
        try:
            converted = _usd_normalize(series, m.currency, fx_map.get(m.currency))
            converted = converted[(converted.index >= lo) & (converted.index <= hi)].dropna()
            if len(converted) < min_observations:
                raise ValueError(f"недостаточно USD-normalized history ({len(converted)} observations)")
            usd[t] = converted
        except Exception as exc:
            if allow_partial:
                errors[t] = str(exc)
            else:
                raise

    provenance = {
        "price_source": "real adjusted historical close",
        "base_currency": "USD",
        "fx_policy": "historical FX; forward-fill from already-known past observations only",
        "requested_range": {"start": start, "end": end_inclusive},
        "unavailable_selected_assets": errors,
    }
    return usd, metas, provenance


def _historical_rf_bounded(train_end: str) -> tuple[float, str]:
    """Fetch a U.S. 13-week T-bill observation using pre-cutoff data only."""
    end_ts = pd.Timestamp(train_end)
    start = (end_ts - pd.Timedelta(days=75)).strftime("%Y-%m-%d")
    end = _exclusive_day_after(train_end)
    h = fetch_history_range("^IRX", start, end, timeout=6)
    s = _history_to_series(h)
    return _rf_as_of(s, train_end)


def _forecast_only_summary(result: dict, terminals: Iterable[float], amount: float) -> dict:
    """Compact forecast summary in both percentage and USD money terms."""
    terminal = np.asarray(list(terminals), dtype=float)
    if terminal.size == 0:
        raise ValueError("Simulation returned no terminal values")
    summary = summarize_terminal_distribution(terminal, amount)
    p05, p50, p95 = summary["p05"], summary["p50"], summary["p95"]
    var_loss = summary["var95"]
    cvar_loss = summary["cvar95"]

    def point(prefix: str, value: float) -> dict:
        return {
            f"{prefix}_return_pct": round((value / amount - 1.0) * 100.0, 3),
            f"{prefix}_portfolio_value_usd": round(value, 2),
            f"{prefix}_profit_loss_usd": round(value - amount, 2),
        }

    out = {}
    out.update(point("p05", p05))
    out.update(point("p50", p50))
    out.update(point("p95", p95))
    out.update({
        "var95_pct": round(float(summary["var95_pct"]), 3),
        "var95_loss_usd": round(var_loss, 2),
        "var95_portfolio_value_usd": round(amount - var_loss, 2),
        "var95_profit_loss_usd": round(-var_loss, 2),
        "cvar95_pct": round(float(summary["cvar95_pct"]), 3),
        "cvar95_loss_usd": round(cvar_loss, 2),
        "cvar95_portfolio_value_usd": round(amount - cvar_loss, 2),
        "cvar95_profit_loss_usd": round(-cvar_loss, 2),
    })
    return out


def _asset_forecast_breakdown(
    asset_terminal_values: Iterable[Iterable[float]],
    names: list[str],
    weights: np.ndarray,
    amount: float,
) -> list[dict]:
    """Summarize the same simulated buy-and-hold paths at asset level."""
    matrix = np.asarray(list(asset_terminal_values), dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(names):
        raise ValueError("Simulation returned invalid asset terminal values")
    if matrix.shape[0] == 0:
        raise ValueError("Simulation returned no asset terminal values")
    rows = []
    for i, ticker in enumerate(names):
        initial = float(amount) * float(weights[i])
        p05, p50, p95 = [float(x) for x in np.percentile(matrix[:, i], [5, 50, 95])]
        rows.append({
            "ticker": ticker,
            "weight_pct": round(float(weights[i]) * 100.0, 4),
            "start_amount_usd": round(initial, 2),
            "p05_value_usd": round(p05, 2),
            "p50_value_usd": round(p50, 2),
            "p95_value_usd": round(p95, 2),
            "p05_profit_loss_usd": round(p05 - initial, 2),
            "p50_profit_loss_usd": round(p50 - initial, 2),
            "p95_profit_loss_usd": round(p95 - initial, 2),
        })
    return rows


def _comparison_with_actual(forecast: dict, terminals: Iterable[float], actual_wealth: float) -> dict:
    """Add realized percentile/coverage without changing the frozen forecast."""
    terminal = np.asarray(list(terminals), dtype=float)
    if terminal.size == 0:
        raise ValueError("Simulation returned no terminal values")
    p05, p95 = [float(x) for x in np.percentile(terminal, [5, 95])]
    out = dict(forecast)
    out["actual_percentile"] = round(float(np.mean(terminal <= float(actual_wealth)) * 100.0), 2)
    out["actual_inside_90_interval"] = bool(p05 <= float(actual_wealth) <= p95)
    return out


def _cleanup_interactive_sessions(now: float | None = None) -> None:
    current = time.time() if now is None else float(now)
    with _interactive_sessions_lock:
        expired = [sid for sid, (ts, _) in _interactive_sessions.items() if current - ts > _INTERACTIVE_SESSION_TTL]
        for sid in expired:
            _interactive_sessions.pop(sid, None)


def build_historical_validation_forecast(
    tickers: list[str],
    amount_usd: float,
    test_year: int,
    *,
    objective: str = "max_sharpe",
    concentration_mode: str = "constrained",
    covariance_method: str = "ledoit_wolf",
) -> dict:
    """Build a forecast using *training data only* for one selected test year.

    This function deliberately does not fetch the test-year price range.  The
    untouched test period is opened later by :func:`reveal_historical_actual`.
    """
    selected = list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()))
    if len(selected) < 2:
        raise ValueError("Historical Model Validation требует минимум 2 выбранных актива")
    try:
        amount = float(amount_usd)
    except Exception as exc:
        raise ValueError("Некорректный стартовый капитал") from exc
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Стартовый капитал должен быть больше 0")
    try:
        year = int(test_year)
    except Exception as exc:
        raise ValueError("Некорректный test year") from exc
    if year not in VALIDATION_WINDOWS_BY_YEAR:
        raise ValueError(f"Test year должен быть одним из: {FIRST_VALIDATION_YEAR}–{LAST_COMPLETED_YEAR}")

    train_start, train_end, test_start, test_end = VALIDATION_WINDOWS_BY_YEAR[year]

    # Training prices and historical risk-free rate are independent reads and
    # both are bounded by train_end. No test-year market data is requested here.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="hval-forecast") as pool:
        prices_future = pool.submit(_bounded_usd_prices, selected, train_start, train_end, min_observations=190, allow_partial=True)
        rf_future = pool.submit(_historical_rf_bounded, train_end)
        usd_prices, metas, provenance = prices_future.result()
        rf_pct, rf_date = rf_future.result()

    eligible = [t for t in selected if t in usd_prices]
    excluded_assets = [{"ticker": t, "reason": provenance.get("unavailable_selected_assets", {}).get(t, "insufficient training history")} for t in selected if t not in usd_prices]
    if len(eligible) < 2:
        raise ValueError("Для выбранного test year осталось меньше 2 активов с достаточной training history")
    train_series = {t: usd_prices[t].copy() for t in eligible}
    max_train_dates = {t: str(series.index.max().date()) for t, series in train_series.items()}
    if any(d > train_end for d in max_train_dates.values()):
        raise RuntimeError("No-look-ahead verification failed: training data crossed the cutoff")

    def chart_fetcher(ticker: str, period: str = "3y"):
        return _to_history_payload(train_series[ticker.upper()])

    def record_fetcher(ticker: str):
        t = ticker.upper()
        m = metas[t]
        return {
            "ticker": t,
            "name": t,
            "asset_type": m.asset_type,
            "market": m.market,
            "region": m.market,
            "currency": "USD",
        }

    result = analyze_portfolio(
        eligible,
        amount,
        record_fetcher=record_fetcher,
        chart_fetcher=chart_fetcher,
        curve_history=pd.DataFrame(),
        include_historical_returns=True,
        objective=objective,
        risk_free_rate_pct=rf_pct,
        concentration_mode=concentration_mode,
        covariance_method=covariance_method,
        include_etf_holdings=False,
    )
    historical_returns = result.pop("_historical_returns", [])
    engine = result.get("_engine") or {}
    weights = np.asarray(engine.get("weights") or [], dtype=float)
    names = list(engine.get("names") or eligible)
    if len(weights) != len(names) or not len(names):
        raise RuntimeError("Historical Markowitz did not return exact frozen weights")
    if abs(float(weights.sum()) - 1.0) > 1e-8 or np.any(weights < -1e-10):
        raise RuntimeError("Portfolio integrity failed: invalid Markowitz weights")

    alloc_by_ticker = {str(x.get("ticker") or "").upper(): x for x in result.get("allocation", [])}
    met_by_ticker = {str(x.get("ticker") or "").upper(): x for x in result.get("individual_metrics", [])}
    allocation = []
    metrics = []
    for i, t in enumerate(names):
        a = dict(alloc_by_ticker.get(t, {"ticker": t}))
        a["weight"] = float(weights[i])
        a["weight_pct"] = float(weights[i]) * 100.0
        allocation.append(a)
        m = dict(met_by_ticker.get(t, {"ticker": t}))
        m["expected_return_pct"] = float(engine["expected_returns"][i]) * 100.0
        metrics.append(m)

    gbm = simulate_portfolio_gbm(
        amount,
        allocation,
        metrics,
        engine["covariance"],
        horizon_days=HORIZON_DAYS,
        simulations=SIMULATIONS,
        seed=10_000 + year,
        summary_only=True,
        return_terminal_values=True,
        return_asset_terminal_values=True,
    )
    bootstrap = simulate_portfolio_bootstrap(
        amount,
        allocation,
        historical_returns,
        horizon_days=HORIZON_DAYS,
        simulations=SIMULATIONS,
        block_size=BOOTSTRAP_BLOCK,
        seed=20_000 + year,
        summary_only=True,
        return_terminal_values=True,
        return_asset_terminal_values=True,
    )
    gbm_terminals = np.asarray(gbm.pop("_terminal_values", []), dtype=float)
    bootstrap_terminals = np.asarray(bootstrap.pop("_terminal_values", []), dtype=float)
    gbm_asset_terminals = np.asarray(gbm.pop("_asset_terminal_values", []), dtype=float)
    bootstrap_asset_terminals = np.asarray(bootstrap.pop("_asset_terminal_values", []), dtype=float)
    if gbm_terminals.size != SIMULATIONS or bootstrap_terminals.size != SIMULATIONS:
        raise RuntimeError("Monte Carlo integrity failed: unexpected terminal-simulation count")
    expected_asset_shape = (SIMULATIONS, len(names))
    if gbm_asset_terminals.shape != expected_asset_shape or bootstrap_asset_terminals.shape != expected_asset_shape:
        raise RuntimeError("Monte Carlo integrity failed: unexpected asset-terminal simulation shape")

    gbm_forecast = _forecast_only_summary(gbm, gbm_terminals, amount)
    gbm_forecast["asset_breakdown"] = _asset_forecast_breakdown(gbm_asset_terminals, names, weights, amount)
    bootstrap_forecast = _forecast_only_summary(bootstrap, bootstrap_terminals, amount)
    bootstrap_forecast["asset_breakdown"] = _asset_forecast_breakdown(bootstrap_asset_terminals, names, weights, amount)

    start_prices = {t: float(train_series[t].iloc[-1]) for t in names}
    session_id = uuid.uuid4().hex
    session = {
        "selected": names,
        "original_selected": selected,
        "excluded_assets": excluded_assets,
        "amount_usd": amount,
        "objective": objective,
        "concentration_mode": concentration_mode,
        "covariance_method": covariance_method,
        "training_period": {"start": train_start, "end": train_end},
        "test_period": {"start": test_start, "end": test_end, "year": year},
        "weights": weights.copy(),
        "allocation": [{
            "ticker": names[i],
            "weight_pct": round(float(weights[i]) * 100.0, 4),
            "amount_usd": round(amount * float(weights[i]), 2),
        } for i in range(len(names))],
        "start_prices_usd": start_prices,
        "gbm_terminals": gbm_terminals,
        "bootstrap_terminals": bootstrap_terminals,
        "gbm_forecast": gbm_forecast,
        "bootstrap_forecast": bootstrap_forecast,
        "risk_free": {
            "rate_pct": round(float(rf_pct), 4),
            "as_of": rf_date,
            "instrument": "13-week U.S. Treasury bill (^IRX historical)",
        },
        "portfolio_metrics": {
            "expected_return_pct": result.get("portfolio", {}).get("expected_return_pct"),
            "historical_risk_pct": result.get("portfolio", {}).get("historical_risk_pct"),
            "sharpe_ratio": result.get("portfolio", {}).get("sharpe_ratio"),
            "max_position_weight_pct": result.get("portfolio", {}).get("max_position_weight_pct"),
        },
        "provenance": provenance,
        "training_max_dates": max_train_dates,
    }
    _cleanup_interactive_sessions()
    with _interactive_sessions_lock:
        _interactive_sessions[session_id] = (time.time(), session)

    return {
        "module": "Historical Model Validation",
        "validation_id": session_id,
        "selected": names,
        "universe": {"selected": selected, "eligible": names, "excluded": excluded_assets},
        "amount_usd": round(amount, 2),
        "base_currency": "USD",
        "training_period": session["training_period"],
        "test_period": session["test_period"],
        "risk_free": session["risk_free"],
        "portfolio": {
            "objective": objective,
            "covariance_method": covariance_method,
            "concentration_mode": concentration_mode,
            "allocation": session["allocation"],
            **session["portfolio_metrics"],
        },
        "gbm": session["gbm_forecast"],
        "bootstrap": session["bootstrap_forecast"],
        "integrity": {
            "no_lookahead_verified": True,
            "training_max_dates": max_train_dates,
            "test_market_data_loaded": False,
            "frozen_weights_verified": True,
            "same_buy_and_hold_policy": True,
            "horizon_days": HORIZON_DAYS,
            "simulations": SIMULATIONS,
            "bootstrap_mean_block_days": BOOTSTRAP_BLOCK,
        },
        "provenance": provenance,
    }


def _realized_from_frozen_start(
    test_prices: dict[str, pd.Series],
    names: list[str],
    start_prices: dict[str, float],
    weights: np.ndarray,
    train_end: str,
    test_end: str,
    amount: float,
) -> dict:
    """Value the frozen buy-and-hold portfolio on one common real market date."""
    cutoff = pd.Timestamp(train_end)
    hi = pd.Timestamp(test_end)
    factors: dict[str, pd.Series] = {}
    for t in names:
        start_px = float(start_prices[t])
        s = test_prices[t].sort_index()
        after = s[(s.index > cutoff) & (s.index <= hi)]
        if after.empty:
            raise ValueError(f"{t}: нет реальных цен в test year")
        factor = (after / start_px).replace([np.inf, -np.inf], np.nan).dropna()
        factor = pd.concat([pd.Series([1.0], index=pd.DatetimeIndex([cutoff])), factor])
        factors[t] = factor[~factor.index.duplicated(keep="last")].sort_index()

    factor_df = pd.concat(factors, axis=1).sort_index().ffill().dropna(how="any")
    factor_df = factor_df[(factor_df.index >= cutoff) & (factor_df.index <= hi)]
    if len(factor_df) < 20:
        raise ValueError("Недостаточно совместных фактических торговых дат в test year")

    portfolio_factor = factor_df.to_numpy(float) @ weights
    wealth = amount * portfolio_factor
    peaks = np.maximum.accumulate(wealth)
    drawdown = wealth / peaks - 1.0
    final_factor = float(portfolio_factor[-1])
    common_end = factor_df.index[-1]

    asset_results = []
    final_asset_values = []
    for i, t in enumerate(names):
        initial = float(amount) * float(weights[i])
        factor = float(factor_df.iloc[-1][t])
        ending = initial * factor
        final_asset_values.append(ending)
        # Last actual observation at or before the common portfolio valuation date.
        observed = test_prices[t][test_prices[t].index <= common_end]
        observed_date = str(observed.index[-1].date()) if not observed.empty else str(common_end.date())
        asset_results.append({
            "ticker": t,
            "weight_pct": round(float(weights[i]) * 100.0, 4),
            "start_price_usd": round(float(start_prices[t]), 8),
            "valuation_date": str(common_end.date()),
            "last_observed_price_date": observed_date,
            "start_amount_usd": round(initial, 2),
            "ending_amount_usd": round(ending, 2),
            "profit_loss_usd": round(ending - initial, 2),
            "actual_return_pct": round((factor - 1.0) * 100.0, 3),
        })

    # Asset values and portfolio wealth are calculated from the exact same
    # common-date factors, so the money breakdown must reconcile.
    if abs(sum(final_asset_values) - float(wealth[-1])) > max(0.02, amount * 1e-9):
        raise RuntimeError("Actual asset-level values do not reconcile with portfolio ending wealth")

    return {
        "actual_return_pct": round((final_factor - 1.0) * 100.0, 3),
        "ending_wealth_usd": round(float(wealth[-1]), 2),
        "profit_loss_usd": round(float(wealth[-1] - amount), 2),
        "max_drawdown_pct": round(float(np.min(drawdown) * 100.0), 3),
        "observations": int(len(factor_df) - 1),
        "last_market_date": str(common_end.date()),
        "asset_results": asset_results,
    }


def reveal_historical_actual(validation_id: str) -> dict:
    """Open the untouched test year for a previously frozen forecast session."""
    sid = str(validation_id or "").strip()
    if not sid:
        raise ValueError("Отсутствует validation_id. Сначала рассчитайте historical forecast")
    _cleanup_interactive_sessions()
    with _interactive_sessions_lock:
        row = _interactive_sessions.get(sid)
    if not row:
        raise ValueError("Historical forecast устарел или не найден. Рассчитайте его заново")
    _, session = row

    names = list(session["selected"])
    test = session["test_period"]
    train = session["training_period"]
    test_prices, _metas, provenance = _bounded_usd_prices(
        names, test["start"], test["end"], min_observations=20
    )
    weights = np.asarray(session["weights"], dtype=float)
    actual = _realized_from_frozen_start(
        test_prices,
        names,
        session["start_prices_usd"],
        weights,
        train["end"],
        test["end"],
        float(session["amount_usd"]),
    )
    if actual["last_market_date"] > test["end"]:
        raise RuntimeError("Actual-market integrity failed: data crossed test-year end")

    gbm = _comparison_with_actual(
        session["gbm_forecast"],
        session["gbm_terminals"],
        actual["ending_wealth_usd"],
    )
    bootstrap = _comparison_with_actual(
        session["bootstrap_forecast"],
        session["bootstrap_terminals"],
        actual["ending_wealth_usd"],
    )

    return {
        "module": "Historical Model Validation",
        "validation_id": sid,
        "selected": names,
        "universe": {"selected": session.get("original_selected", names), "eligible": names, "excluded": session.get("excluded_assets", [])},
        "amount_usd": round(float(session["amount_usd"]), 2),
        "base_currency": "USD",
        "training_period": train,
        "test_period": test,
        "portfolio": {
            "objective": session["objective"],
            "covariance_method": session.get("covariance_method", "ledoit_wolf"),
            "concentration_mode": session["concentration_mode"],
            "allocation": session["allocation"],
            **session["portfolio_metrics"],
        },
        "risk_free": session["risk_free"],
        "gbm": gbm,
        "bootstrap": bootstrap,
        "actual": actual,
        "integrity": {
            "no_lookahead_verified": True,
            "forecast_was_frozen_before_actual": True,
            "test_market_data_loaded_after_forecast": True,
            "frozen_weights_verified": True,
            "same_buy_and_hold_policy": True,
            "horizon_days": HORIZON_DAYS,
            "simulations": SIMULATIONS,
            "bootstrap_mean_block_days": BOOTSTRAP_BLOCK,
        },
        "provenance": {
            "training": session["provenance"],
            "actual_test": provenance,
        },
    }
