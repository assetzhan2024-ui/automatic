"""Educational Markowitz portfolio analytics for user-selected assets.

Pipeline
--------
1. Load up to five years of daily history for every selected asset.
2. Estimate annual expected returns and the annual covariance/correlation matrix.
3. Build a long-only Markowitz efficient frontier.
4. Select either the maximum-Sharpe or minimum-variance long-only portfolio.

No security is ever added automatically.  A selected asset may receive 0% if
it does not improve the optimal historical risk/return trade-off under the
constraints.  Missing selected assets stop the calculation instead of being
silently removed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Callable
from functools import lru_cache

import numpy as np
import pandas as pd

from config.markets import asset_type_for_ticker
from fetcher.bonds import fetch_bond, get_curve_history, MATURITIES
from fetcher.fx import fetch_fx_history_usd, get_rate

TRADING_DAYS = 252
MIN_OBSERVATIONS = 190          # approximately one trading year
FRONTIER_POINTS = 36


@dataclass
class SeriesMeta:
    ticker: str
    name: str
    asset_type: str
    market: str
    method: str
    annual_return_hint: float | None = None


def _safe_float(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _years_to_maturity(record: dict) -> float:
    raw = str(record.get("maturity") or "").strip()
    if not raw:
        return 5.0
    low = raw.lower()
    if "perpetual" in low:
        return 10.0
    if "month" in low:
        try:
            return max(float(raw.split()[0]) / 12.0, 1 / 12)
        except Exception:
            return 0.5
    if "year" in low:
        try:
            return max(float(raw.split()[0]), 0.25)
        except Exception:
            return 5.0
    try:
        d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        return max((d - date.today()).days / 365.25, 0.25)
    except Exception:
        return 5.0


def _nearest_curve_symbol(years: float) -> str:
    choices = []
    for sym, (label, _key) in MATURITIES.items():
        if "Month" in label:
            x = float(label.split()[0]) / 12.0
        else:
            x = float(label.split()[0])
        choices.append((abs(x - years), sym))
    return min(choices)[1]


def _price_return_series(history: dict, currency: str = "USD") -> pd.Series | None:
    dates = history.get("dates") or []
    closes = history.get("closes") or []
    if len(dates) < 3 or len(closes) < 3:
        return None
    s = pd.Series(
        pd.to_numeric(pd.Series(closes), errors="coerce").values,
        index=pd.to_datetime(dates, errors="coerce"),
        dtype="float64",
    ).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    currency = (currency or "USD").strip()
    if currency.upper() != "USD":
        fx = fetch_fx_history_usd(currency, period="5y")
        if fx is None or len(fx) < 20:
            return None
        # Forward-fill only: never use a future FX observation for an earlier
        # asset date. All foreign assets are converted to USD before returns.
        fx = fx.reindex(s.index).ffill()
        s = (s * fx).replace([np.inf, -np.inf], np.nan).dropna()
    r = s.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return r if len(r) >= 20 else None


def _bond_return_series(record: dict, curve_history: pd.DataFrame) -> pd.Series | None:
    if curve_history is None or curve_history.empty:
        return None
    years = _years_to_maturity(record)
    curve_sym = _nearest_curve_symbol(years)
    if curve_sym not in curve_history.columns:
        return None
    y = pd.to_numeric(curve_history[curve_sym], errors="coerce").dropna() / 100.0
    if len(y) < 20:
        return None

    carry_pct = _safe_float(record.get("yield_pct"))
    if carry_pct is None:
        carry_pct = _safe_float(record.get("coupon_pct"), 0.0)
    carry = (carry_pct or 0.0) / 100.0

    # Modified-duration proxy when a free daily traded-price series is not
    # available.  It does not introduce any unselected bond into the portfolio.
    duration = min(max(years / (1.0 + max(carry, 0.0)), 0.20), 12.0)
    dy = y.diff()
    r = (carry / TRADING_DAYS) - duration * dy
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    return r if len(r) >= 20 else None


def _record_for(ticker: str) -> dict:
    at = asset_type_for_ticker(ticker)
    if at == "bond":
        return fetch_bond(ticker)
    from fetcher.ticker import fetch_ticker
    return fetch_ticker(ticker)


def _expected_return(series: pd.Series, hint: float | None = None) -> float:
    """Annual historical arithmetic mean return used by Markowitz.

    Stocks/ETFs follow mean(daily return) * 252 as shown in the educational
    explanation.  For bonds without daily traded prices a carry hint is blended
    with the duration-proxy history because the proxy alone mainly captures
    rate shocks rather than total bond carry.
    """
    hist = float(series.mean() * TRADING_DAYS)
    if hint is not None and math.isfinite(hint):
        return float(0.65 * hint + 0.35 * hist)
    return hist


def _nearest_psd(cov: np.ndarray) -> np.ndarray:
    sym = (cov + cov.T) / 2.0
    vals, vecs = np.linalg.eigh(sym)
    vals = np.maximum(vals, 1e-10)
    out = vecs @ np.diag(vals) @ vecs.T
    return (out + out.T) / 2.0

def _estimate_covariance(returns: pd.DataFrame, names: list[str], method: str = "ledoit_wolf") -> tuple[np.ndarray, dict]:
    """Estimate annualized covariance using a named, explicit method.

    Ledoit-Wolf uses complete aligned daily return vectors, which is required by
    the shrinkage estimator. Sample covariance keeps the existing pairwise
    estimator and is projected to the nearest PSD matrix for numerical stability.
    """
    method = str(method or "ledoit_wolf").strip().lower()
    aliases = {"lw":"ledoit_wolf", "ledoit-wolf":"ledoit_wolf", "sample_covariance":"sample"}
    method = aliases.get(method, method)
    if method not in {"ledoit_wolf", "sample"}:
        raise ValueError("Covariance method должен быть ledoit_wolf или sample")

    if method == "ledoit_wolf":
        complete = returns[names].dropna(how="any")
        if len(complete) < MIN_OBSERVATIONS:
            raise ValueError(
                f"Ledoit-Wolf требует не менее {MIN_OBSERVATIONS} общих дневных наблюдений; доступно {len(complete)}"
            )
        try:
            from sklearn.covariance import LedoitWolf
        except Exception as exc:
            raise RuntimeError("Для Ledoit-Wolf установите scikit-learn") from exc
        est = LedoitWolf(assume_centered=False).fit(complete.to_numpy(float))
        cov = np.asarray(est.covariance_, dtype=float) * float(TRADING_DAYS)
        cov = _nearest_psd(cov)
        meta = {
            "method": "ledoit_wolf",
            "label": "Ledoit-Wolf Shrinkage",
            "observations": int(len(complete)),
            "shrinkage": float(est.shrinkage_),
        }
        return cov, meta

    daily_cov_df = returns[names].cov(min_periods=MIN_OBSERVATIONS).reindex(index=names, columns=names)
    raw_cov = daily_cov_df.to_numpy(dtype=float) * float(TRADING_DAYS)
    if not np.all(np.isfinite(raw_cov)):
        raise ValueError("Sample covariance содержит невалидные значения")
    cov = _nearest_psd(raw_cov)
    pair_counts = [int(returns[[names[i], names[j]]].dropna().shape[0]) for i in range(len(names)) for j in range(i+1, len(names))]
    meta = {
        "method": "sample",
        "label": "Sample Covariance",
        "observations": int(min(pair_counts) if pair_counts else returns[names].dropna().shape[0]),
        "shrinkage": None,
    }
    return cov, meta


def _portfolio_stats(weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float = 0.0):
    ret = float(weights @ mu)
    var = float(max(weights @ cov @ weights, 0.0))
    risk = math.sqrt(var)
    sharpe = (ret - rf) / risk if risk > 1e-12 else -math.inf
    return ret, risk, sharpe


def _concentration_cap(n: int, mode: str = "constrained") -> float:
    """Maximum position weight for the chosen portfolio-management policy.

    ``unconstrained`` keeps the academic long-only Markowitz benchmark at
    0..100%. ``constrained`` applies the agreed practical concentration policy:
    2 assets -> 60%, 3 -> 45%, 4 -> 35%, 5+ -> 25%. A single-asset portfolio
    necessarily remains 100%.
    """
    mode = str(mode or "constrained").strip().lower()
    if mode == "unconstrained":
        return 1.0
    if mode != "constrained":
        raise ValueError("Режим концентрации должен быть constrained или unconstrained")
    if n <= 1:
        return 1.0
    if n == 2:
        return 0.60
    if n == 3:
        return 0.45
    if n == 4:
        return 0.35
    return 0.25


@lru_cache(maxsize=128)
def _fetch_etf_holdings(ticker: str) -> dict[str, float]:
    """Best-effort ETF look-through using current yfinance fund holdings.

    yfinance exposes ``Ticker.funds_data.equity_holdings`` and
    ``top_holdings`` for ETF/fund symbols. Holdings are returned as
    normalized ticker -> portfolio weight. If the provider is unavailable or
    the fund does not expose holdings, an empty mapping is returned and the
    caller reports that concentration could not be fully checked.
    """
    try:
        import yfinance as yf  # type: ignore
        from fetcher.session import _SESSION
        obj = yf.Ticker(ticker, session=_SESSION) if _SESSION else yf.Ticker(ticker)
        fd = obj.funds_data
        if fd is None:
            return {}
        frames = []
        for attr in ("equity_holdings", "top_holdings"):
            try:
                df = getattr(fd, attr, None)
            except Exception:
                df = None
            if df is not None and hasattr(df, "empty") and not df.empty:
                frames.append(df.copy())
                if attr == "equity_holdings":
                    break
        if not frames:
            return {}
        df = frames[0]
        out: dict[str, float] = {}
        pct_col = next((c for c in df.columns if str(c).strip().lower() in {"holding percent", "holding_percent", "percent", "weight"}), None)
        if pct_col is None:
            for c in df.columns:
                vals = pd.to_numeric(df[c], errors="coerce")
                if vals.notna().any() and float(vals.dropna().max()) <= 1.0:
                    pct_col = c
                    break
        if pct_col is None:
            return {}
        for idx, row in df.iterrows():
            sym = str(idx).strip().upper()
            if not sym or sym in {"NAN", "NONE"}:
                for name_col in ("Symbol", "symbol", "Ticker", "ticker"):
                    if name_col in df.columns and str(row.get(name_col) or "").strip():
                        sym = str(row.get(name_col)).strip().upper()
                        break
            try:
                w = float(row[pct_col])
                if w > 1.0:
                    w /= 100.0
            except Exception:
                continue
            if sym and 0 < w <= 1.0:
                out[sym] = out.get(sym, 0.0) + w
        return out
    except Exception:
        return {}


def _exposure_constraints(names: list[str], records: dict[str, dict], direct_cap: float) -> tuple[np.ndarray | None, float, dict[str, dict]]:
    """Return ETF look-through metadata without constraining optimization.

    Concentration limits were removed. ETF holdings can still be inspected,
    but they no longer impose hidden optimization constraints.
    """
    details: dict[str, dict] = {}
    missing_etf: list[str] = []
    for t in names:
        at = records[t].get("asset_type") or asset_type_for_ticker(t)
        if at == "etf":
            h = _fetch_etf_holdings(t)
            if h:
                details[t] = {"holdings_count": len(h), "holdings": h}
            else:
                missing_etf.append(t)
    details["_missing_etf_holdings"] = missing_etf
    return None, 1.0, details

def _require_scipy():
    try:
        from scipy.optimize import minimize  # type: ignore
        return minimize
    except Exception as exc:
        raise RuntimeError(
            "Для Markowitz Efficient Frontier нужен scipy. Установите: pip install scipy"
        ) from exc


def _greedy_extreme_return(mu: np.ndarray, cap: float, maximize: bool) -> tuple[float, np.ndarray]:
    n = len(mu)
    order = np.argsort(mu)
    if maximize:
        order = order[::-1]
    w = np.zeros(n, dtype=float)
    left = 1.0
    for i in order:
        take = min(cap, left)
        w[i] = take
        left -= take
        if left <= 1e-12:
            break
    if left > 1e-8:
        raise ValueError("Ограничение концентрации несовместимо с количеством выбранных активов")
    return float(w @ mu), w


def _solve_min_variance(mu: np.ndarray, cov: np.ndarray, cap: float, target_return: float | None = None,
                        x0: np.ndarray | None = None, exposure_matrix: np.ndarray | None = None,
                        exposure_cap: float | None = None) -> np.ndarray | None:
    minimize = _require_scipy()
    n = len(mu)
    if n == 1:
        return np.array([1.0])
    if x0 is None:
        x0 = np.full(n, 1.0 / n)
    x0 = np.clip(np.asarray(x0, dtype=float), 0.0, cap)
    x0 = x0 / x0.sum()

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    if exposure_matrix is not None and exposure_cap is not None:
        constraints.append({"type": "ineq", "fun": lambda w, A=exposure_matrix, c=exposure_cap: c - A @ w})
    if target_return is not None:
        constraints.append({"type": "eq", "fun": lambda w, t=target_return: float(w @ mu - t)})

    res = minimize(
        lambda w: float(w @ cov @ w),
        x0,
        method="SLSQP",
        bounds=[(0.0, cap)] * n,
        constraints=constraints,
        options={"maxiter": 1500, "ftol": 1e-12, "disp": False},
    )
    if not res.success or not np.all(np.isfinite(res.x)):
        return None
    w = np.maximum(res.x, 0.0)
    w[np.abs(w) < 1e-9] = 0.0
    total = float(w.sum())
    return w / total if total > 0 else None


def _efficient_frontier(mu: np.ndarray, cov: np.ndarray, cap: float, points: int = FRONTIER_POINTS,
                        exposure_matrix: np.ndarray | None = None, exposure_cap: float | None = None):
    n = len(mu)
    if n == 1:
        ret, risk, _ = _portfolio_stats(np.array([1.0]), mu, cov)
        return [{"return": ret, "risk": risk, "weights": np.array([1.0])}], np.array([1.0])

    gmv = _solve_min_variance(mu, cov, cap, exposure_matrix=exposure_matrix, exposure_cap=exposure_cap)
    if gmv is None:
        raise RuntimeError("Не удалось построить minimum-variance portfolio")
    gmv_ret, _, _ = _portfolio_stats(gmv, mu, cov)
    # Maximum-return corner. With the current long-only/no-cap architecture
    # this is simply the asset with the highest expected return. Keep the
    # constrained solver path for future optional exposure constraints.
    if exposure_matrix is None:
        max_ret, max_w = _greedy_extreme_return(mu, cap, maximize=True)
    else:
        minimize = _require_scipy()
        cons = [{"type":"eq", "fun": lambda w: float(np.sum(w)-1.0)}]
        if exposure_cap is not None:
            cons.append({"type":"ineq", "fun": lambda w, A=exposure_matrix, c=exposure_cap: c-A@w})
        seed = np.full(n, 1.0/n)
        res = minimize(lambda w: -float(w @ mu), seed, method="SLSQP", bounds=[(0.0, cap)]*n, constraints=cons, options={"maxiter":1200,"ftol":1e-11,"disp":False})
        if not res.success or not np.all(np.isfinite(res.x)):
            raise ValueError("Ограничения несовместимы с выбранным набором активов")
        max_w = np.maximum(res.x, 0.0)
        max_w /= float(max_w.sum())
        max_ret = float(max_w @ mu)

    if max_ret <= gmv_ret + 1e-10:
        ret, risk, _ = _portfolio_stats(gmv, mu, cov)
        return [{"return": ret, "risk": risk, "weights": gmv}], gmv

    targets = np.linspace(gmv_ret, max_ret, max(8, int(points)))
    frontier = []
    warm = gmv.copy()
    for target in targets:
        w = _solve_min_variance(mu, cov, cap, float(target), warm, exposure_matrix, exposure_cap)
        if w is None:
            # Try a feasible blend between GMV and the max-return corner.
            alpha = (target - gmv_ret) / max(max_ret - gmv_ret, 1e-12)
            guess = (1 - alpha) * gmv + alpha * max_w
            w = _solve_min_variance(mu, cov, cap, float(target), guess)
        if w is None:
            continue
        ret, risk, _ = _portfolio_stats(w, mu, cov)
        frontier.append({"return": ret, "risk": risk, "weights": w})
        warm = w
    if not frontier:
        raise RuntimeError("Не удалось построить эффективную границу")
    return frontier, gmv


def _max_sharpe(mu: np.ndarray, cov: np.ndarray, cap: float, rf: float,
                frontier: list[dict], gmv: np.ndarray, exposure_matrix: np.ndarray | None = None,
                exposure_cap: float | None = None) -> np.ndarray:
    minimize = _require_scipy()
    n = len(mu)
    if n == 1:
        return np.array([1.0])

    def objective(w):
        _ret, _risk, sh = _portfolio_stats(w, mu, cov, rf)
        return 1e9 if not math.isfinite(sh) else -sh

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    if exposure_matrix is not None and exposure_cap is not None:
        constraints.append({"type": "ineq", "fun": lambda w, A=exposure_matrix, c=exposure_cap: c - A @ w})
    starts = [np.full(n, 1.0 / n), gmv]
    # Frontier points are excellent deterministic multi-start seeds.
    starts.extend(pt["weights"] for pt in frontier[::max(1, len(frontier)//8)])

    best = None
    best_sh = -math.inf
    for start in starts:
        res = minimize(
            objective,
            np.asarray(start, dtype=float),
            method="SLSQP",
            bounds=[(0.0, cap)] * n,
            constraints=constraints,
            options={"maxiter": 1500, "ftol": 1e-12, "disp": False},
        )
        if not res.success or not np.all(np.isfinite(res.x)):
            continue
        w = np.maximum(res.x, 0.0)
        w[np.abs(w) < 1e-8] = 0.0
        w /= w.sum()
        _ret, _risk, sh = _portfolio_stats(w, mu, cov, rf)
        if sh > best_sh:
            best, best_sh = w, sh

    if best is None:
        # The best sampled point on the efficient frontier is still a valid
        # Markowitz solution if the direct nonlinear solve ever fails.
        best_pt = max(frontier, key=lambda p: _portfolio_stats(p["weights"], mu, cov, rf)[2])
        best = best_pt["weights"].copy()
    return best


def _history_quality(obs: int) -> tuple[str, str | None]:
    if obs >= 1050:
        return "~5Y daily history", None
    if obs >= 756:
        return "~3Y daily history", "использовано около 3 лет истории вместо 5 лет"
    if obs >= 420:
        return "~2Y daily history", "использовано около 2 лет истории вместо 5 лет"
    if obs >= MIN_OBSERVATIONS:
        return "~1Y daily history", "использован сокращённый период около 1 года; оценка менее устойчива"
    return "insufficient", "менее одного года наблюдений"



def simulate_portfolio_gbm(
    amount_kzt: float,
    allocation: list[dict],
    individual_metrics: list[dict],
    covariance: list[list[float]],
    *,
    horizon_days: int = TRADING_DAYS,
    simulations: int = 10_000,
    seed: int | None = None,
    summary_only: bool = False,
    return_terminal_values: bool = False,
    return_asset_terminal_values: bool = False,
) -> dict:
    """Run a correlated GBM Monte Carlo forecast for the Markowitz allocation.

    Paths are generated with trading-day steps over ``horizon_days``.
    The same covariance matrix used by Markowitz preserves the historical
    correlation structure between the selected assets.

    Scenario labels are intentionally beginner-friendly:
      - Best Case = 95th percentile
      - Base / Median Case = 50th percentile
      - Worst Case = 5th percentile = VaR 95% threshold

    VaR 95% is reported as the modeled loss from the starting capital to the
    5th percentile, floored at zero so a modeled gain is not called a loss.
    """
    amount = _safe_float(amount_kzt)
    if amount is None or amount <= 0:
        raise ValueError("Сумма инвестирования должна быть больше 0")
    if horizon_days <= 0:
        raise ValueError("Горизонт прогноза должен быть больше 0 дней")
    if simulations < 100:
        raise ValueError("Количество симуляций должно быть не меньше 100")

    names = [str(x.get("ticker") or "").strip().upper() for x in individual_metrics]
    if not names:
        raise ValueError("Нет данных по выбранным активам для прогноза")

    by_ticker = {str(x.get("ticker")).upper(): x for x in allocation}
    weights = np.array(
        [float(by_ticker.get(t, {}).get("weight", float(by_ticker.get(t, {}).get("weight_pct", 0.0)) / 100.0)) for t in names],
        dtype=float,
    )
    if not np.any(weights > 0):
        raise ValueError("Markowitz не назначил положительные веса выбранным активам")
    if np.any(weights < -1e-10):
        raise ValueError("Snapshot содержит отрицательные веса, хотя модель long-only")
    weights = np.maximum(weights, 0.0)
    weights /= weights.sum()

    mu = np.array(
        [float(x.get("expected_return_pct", 0.0)) / 100.0 for x in individual_metrics],
        dtype=float,
    )
    cov = np.asarray(covariance, dtype=float)
    if cov.shape != (len(names), len(names)):
        raise ValueError("Некорректная матрица covariance для Monte Carlo")

    cov = _nearest_psd(cov)
    # Numerical guard for assets with effectively zero historical variance.
    sigma = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    dt = 1.0 / float(TRADING_DAYS)
    steps = int(horizon_days)
    rng = np.random.default_rng(seed)

    # Cholesky of a tiny diagonal-jittered PSD covariance so correlated
    # Brownian shocks remain stable on all machines.
    jitter = max(float(np.max(np.diag(cov))) * 1e-10, 1e-12)
    chol = np.linalg.cholesky(cov + np.eye(len(names)) * jitter)

    # Keep current paths only; ``simulations`` is the complete Monte Carlo sample.
    # For the chart we store a small number of checkpoints from these same paths.
    start = float(amount)
    asset_values = amount * weights
    terminal_assets = np.tile(asset_values, (simulations, 1))

    drift = (mu - 0.5 * sigma**2) * dt
    diffusion_scale = math.sqrt(dt)
    checkpoint = max(1, steps // 60)
    band_days = [0]
    band = [] if summary_only else [{
        "day": 0,
        "worst_kzt": round(start, 2),
        "median_kzt": round(start, 2),
        "best_kzt": round(start, 2),
    }]

    for day in range(1, steps + 1):
        z = rng.standard_normal((simulations, len(names)))
        correlated = z @ chol.T
        terminal_assets *= np.exp(
            drift[None, :] + correlated * diffusion_scale
        )
        if (not summary_only) and (day % checkpoint == 0 or day == steps):
            day_values = terminal_assets.sum(axis=1)
            q5, q50, q95 = np.percentile(day_values, [5, 50, 95])
            band_days.append(day)
            band.append({
                "day": int(day),
                "worst_kzt": round(float(q5), 2),
                "median_kzt": round(float(q50), 2),
                "best_kzt": round(float(q95), 2),
            })

    terminal_portfolio = terminal_assets.sum(axis=1)
    dist = summarize_terminal_distribution(terminal_portfolio, start)
    p5, p50, p95 = dist["p05"], dist["p50"], dist["p95"]
    risk = _loss_tail_metrics(terminal_portfolio, start)
    p05_return_pct = (float(p5) / start - 1.0) * 100.0

    # Asset-level terminal distributions are optional in validation mode, where
    # only portfolio-level terminal diagnostics are required.
    asset_scenarios = []
    if not summary_only:
        for i, ticker in enumerate(names):
            vals = terminal_assets[:, i]
            ap5, ap50, ap95 = np.percentile(vals, [5, 50, 95])
            initial = float(asset_values[i])
            arisk = _loss_tail_metrics(vals, initial) if initial > 0 else {"var95_kzt": 0.0, "var95_pct": 0.0, "cvar95_kzt": 0.0, "cvar95_pct": 0.0}
            asset_scenarios.append({
                "ticker": ticker,
                "weight_pct": float(round(float(weights[i] * 100.0), 4)),
                "initial_amount_kzt": round(initial, 2),
                "best_case_kzt": round(float(ap95), 2),
                "median_case_kzt": round(float(ap50), 2),
                "worst_case_kzt": round(float(ap5), 2),
                "var95_kzt": round(float(arisk["var95_kzt"]), 2),
                "var95_pct": round(float(arisk["var95_pct"]), 2),
                "cvar95_kzt": round(float(arisk["cvar95_kzt"]), 2),
                "cvar95_pct": round(float(arisk["cvar95_pct"]), 2),
            })

    out = {
        "amount_kzt": round(start, 2),
        "horizon_days": int(horizon_days),
        "simulations": int(simulations),
        "method": "Geometric Brownian Motion (GBM) + Monte Carlo",
        "time_basis": f"{TRADING_DAYS} trading days = 1 year",
        "rebalancing": "buy_and_hold",
        "seed": seed,
        "scenarios": {
            "best_case_kzt": round(float(p95), 2),
            "median_case_kzt": round(float(p50), 2),
            "worst_case_kzt": round(float(p5), 2),
            "p05_return_pct": round(p05_return_pct, 2),
            "worst_case_is_gain": bool(float(p5) > start),
            "raw_var95_kzt": round(float(risk["raw_var95_kzt"]), 2),
            "best_case_pct": round((float(p95) / start - 1.0) * 100.0, 2),
            "median_case_pct": round((float(p50) / start - 1.0) * 100.0, 2),
            "worst_case_pct": round((float(p5) / start - 1.0) * 100.0, 2),
            "var95_kzt": round(float(risk["var95_kzt"]), 2),
            "var95_pct": round(float(risk["var95_pct"]), 2),
            "raw_cvar95_kzt": round(float(risk["raw_cvar95_kzt"]), 2),
            "cvar95_kzt": round(float(risk["cvar95_kzt"]), 2),
            "cvar95_pct": round(float(risk["cvar95_pct"]), 2),
        },
        "asset_scenarios": asset_scenarios,
        "chart": band,
        "education": {
            "best": "95-й перцентиль: сильный, но правдоподобный положительный сценарий по модели.",
            "median": f"50-й перцентиль: середина {simulations:,} смоделированных результатов.",
            "worst": "5-й перцентиль: нижние 5% результатов модели.",
            "var95": "VaR 95% — loss-oriented метрика: Start − P05, с нижней границей 0 для пользовательского отображения. Если P05 выше старта, модель не показывает убыток в нижнем 5%-пороговом сценарии.",
            "cvar95": "CVaR 95% (Expected Shortfall) — средняя потеря внутри худших 5% сценариев. Она отвечает на вопрос: «если мы уже попали в хвост, насколько плохим в среднем оказался результат?»",
            "note": "GBM и Bootstrap — альтернативные модели риска. Они не должны тихо смешиваться в один результат: пользователь должен видеть, насколько оценка риска зависит от методологии.",
        },
    }
    if return_terminal_values:
        out["_terminal_values"] = terminal_portfolio.astype(float).tolist()
    if return_asset_terminal_values:
        out["_asset_terminal_values"] = terminal_assets.astype(float).tolist()
    return out


def summarize_terminal_distribution(terminal_values: np.ndarray, start: float) -> dict:
    """Canonical terminal-distribution summary used by Portfolio and HMV.

    This is the single source of truth for P05/P50/P95 and loss-oriented
    VaR/CVaR. HMV must not reinterpret risk metrics independently.
    """
    terminal = np.asarray(terminal_values, dtype=float)
    terminal = terminal[np.isfinite(terminal)]
    if terminal.size == 0:
        raise ValueError("Нет валидных terminal values для risk summary")
    if not math.isfinite(float(start)) or float(start) <= 0:
        raise ValueError("Start capital должен быть положительным")
    p05, p50, p95 = [float(x) for x in np.percentile(terminal, [5, 50, 95])]
    risk = _loss_tail_metrics(terminal, float(start))
    return {
        "p05": p05, "p50": p50, "p95": p95,
        "var95": float(risk["var95_kzt"]),
        "var95_pct": float(risk["var95_pct"]),
        "cvar95": float(risk["cvar95_kzt"]),
        "cvar95_pct": float(risk["cvar95_pct"]),
        "raw_var95": float(risk["raw_var95_kzt"]),
        "raw_cvar95": float(risk["raw_cvar95_kzt"]),
    }


def _loss_tail_metrics(terminal_values: np.ndarray, start: float) -> dict:
    """Loss-oriented VaR/CVaR from terminal portfolio values.

    Loss is defined as L = start - terminal_value. VaR95 is the 95th
    percentile of L, while CVaR95 (Expected Shortfall) is the average loss in
    the worst 5% tail. For beginner-facing display we floor negative losses at
    zero, because a negative "loss" is a gain rather than downside risk.
    """
    terminal = np.asarray(terminal_values, dtype=float)
    losses = start - terminal
    raw_var = float(np.percentile(losses, 95))
    tail = losses[losses >= raw_var - 1e-12]
    raw_cvar = float(np.mean(tail)) if tail.size else raw_var
    var_loss = max(0.0, raw_var)
    cvar_loss = max(0.0, raw_cvar)
    p05 = float(np.percentile(terminal, 5))
    return {
        "p05_kzt": p05,
        "raw_var95_kzt": raw_var,
        "var95_kzt": var_loss,
        "var95_pct": (var_loss / start) * 100.0,
        "raw_cvar95_kzt": raw_cvar,
        "cvar95_kzt": cvar_loss,
        "cvar95_pct": (cvar_loss / start) * 100.0,
    }


def simulate_portfolio_bootstrap(
    amount_kzt: float,
    allocation: list[dict],
    historical_returns: list[dict],
    *,
    horizon_days: int = TRADING_DAYS,
    simulations: int = 10_000,
    block_size: int = 21,
    seed: int | None = None,
    summary_only: bool = False,
    return_terminal_values: bool = False,
    return_asset_terminal_values: bool = False,
) -> dict:
    """Historical block bootstrap for portfolio Monte Carlo.

    Unlike GBM, this model does not assume normal returns. It resamples real
    historical cross-asset return vectors in short blocks, preserving the
    cross-sectional dependence of the selected assets and some short-memory
    structure. The method is an empirical alternative risk model, not a second
    prediction engine that changes Markowitz weights.
    """
    amount = _safe_float(amount_kzt)
    if amount is None or amount <= 0:
        raise ValueError("Сумма инвестирования должна быть больше 0")
    if horizon_days <= 0:
        raise ValueError("Горизонт прогноза должен быть больше 0 дней")
    if simulations < 100:
        raise ValueError("Количество симуляций должно быть не меньше 100")
    block_size = int(block_size)
    if block_size <= 0:
        raise ValueError("Длина Bootstrap-блока должна быть больше 0")

    rows = historical_returns or []
    if len(rows) < 60:
        raise ValueError("Для Bootstrap нужно не менее 60 совместных исторических наблюдений")

    names = [str(x.get("ticker") or "").strip().upper() for x in allocation]
    if not names:
        raise ValueError("Нет активов для Bootstrap")
    by_ticker = {str(x.get("ticker") or "").upper(): x for x in allocation}
    weights = np.array([float(by_ticker.get(t, {}).get("weight", float(by_ticker.get(t, {}).get("weight_pct", 0.0)) / 100.0)) for t in names], dtype=float)
    if weights.sum() <= 0:
        raise ValueError("Нет положительных весов для Bootstrap")
    if np.any(weights < -1e-10):
        raise ValueError("Snapshot содержит отрицательные веса, хотя модель long-only")
    weights = np.maximum(weights, 0.0)
    weights /= weights.sum()

    valid_rows = []
    for r in rows:
        ret = {str(k).upper(): v for k, v in (r.get("returns") or {}).items()}
        if not all(t in ret for t in names):
            continue
        try:
            vals = [float(ret[t]) for t in names]
        except Exception:
            continue
        if np.all(np.isfinite(vals)):
            valid_rows.append(vals)
    if not valid_rows:
        raise ValueError("Исторические доходности не содержат совместных наблюдений по всем выбранным активам")
    matrix = np.asarray(valid_rows, dtype=float)
    if len(matrix) < 60:
        raise ValueError("Для Bootstrap нужно не менее 60 совместных валидных наблюдений")
    if block_size > len(matrix):
        raise ValueError(
            f"Средняя длина Bootstrap-блока ({block_size}) не может превышать доступную совместную историю ({len(matrix)} наблюдений)"
        )

    rng = np.random.default_rng(seed)
    steps = int(horizon_days)
    n_hist = len(matrix)
    batch_size = 250
    # Stationary bootstrap: block lengths are random with geometric mean
    # approximately ``block_size``. This preserves short-run dependence
    # without imposing a fixed 5-day cut-and-shuffle pattern.
    restart_prob = 1.0 / float(block_size)
    checkpoint = max(1, steps // 60)
    checkpoints = list(range(0, steps + 1, checkpoint))
    if checkpoints[-1] != steps:
        checkpoints.append(steps)
    chart_values = {} if summary_only else {day: [] for day in checkpoints}
    terminals = np.empty(simulations, dtype=float)
    start = float(amount)
    asset_initial = amount * weights
    asset_terminal = np.empty((simulations, len(names)), dtype=float)

    pos = 0
    while pos < simulations:
        bs = min(batch_size, simulations - pos)
        current = rng.integers(0, n_hist, size=bs)
        # Summary-only mode compounds in-place and never allocates the large
        # (batch × horizon × assets) tensor. This materially speeds rolling HMV
        # while preserving the exact stationary-bootstrap sampling rule.
        if summary_only:
            growth = np.ones((bs, len(names)), dtype=float)
            for _t in range(steps):
                growth *= (1.0 + matrix[current, :])
                restart = rng.random(bs) < restart_prob
                fresh = rng.integers(0, n_hist, size=bs)
                current = np.where(restart, fresh, (current + 1) % n_hist)
            terminal_assets_batch = asset_initial[None, :] * growth
            terminal = np.maximum(terminal_assets_batch.sum(axis=1), 1e-9)
            terminals[pos:pos+bs] = terminal
            asset_terminal[pos:pos+bs, :] = terminal_assets_batch
        else:
            sample = np.empty((bs, steps, len(names)), dtype=float)
            for t in range(steps):
                sample[:, t, :] = matrix[current, :]
                restart = rng.random(bs) < restart_prob
                fresh = rng.integers(0, n_hist, size=bs)
                current = np.where(restart, fresh, (current + 1) % n_hist)
            asset_paths_full = asset_initial[None, None, :] * np.cumprod(1.0 + sample, axis=1)
            wealth = np.maximum(asset_paths_full.sum(axis=2), 1e-9)
            terminal = wealth[:, -1]
            terminals[pos:pos+bs] = terminal
            asset_terminal[pos:pos+bs, :] = asset_paths_full[:, -1, :]
            for day in checkpoints[1:]:
                chart_values[day].extend(wealth[:, day-1].tolist())
        pos += bs

    dist = summarize_terminal_distribution(terminals, start)
    risk = _loss_tail_metrics(terminals, start)
    p5, p50, p95 = dist["p05"], dist["p50"], dist["p95"]
    chart = []
    if not summary_only:
        chart = [{
            "day": int(day),
            "worst_kzt": round(float(np.percentile(np.asarray(vals), 5)) if vals else start, 2),
            "median_kzt": round(float(np.percentile(np.asarray(vals), 50)) if vals else start, 2),
            "best_kzt": round(float(np.percentile(np.asarray(vals), 95)) if vals else start, 2),
        } for day, vals in chart_values.items()]
        chart[0] = {"day": 0, "worst_kzt": round(start, 2), "median_kzt": round(start, 2), "best_kzt": round(start, 2)}

    asset_scenarios = []
    if not summary_only:
        for i, ticker in enumerate(names):
            vals = asset_terminal[:, i]
            ap5, ap50, ap95 = np.percentile(vals, [5, 50, 95])
            initial_i = float(asset_initial[i])
            if initial_i <= 0:
                arisk = {"var95_kzt": 0.0, "cvar95_kzt": 0.0}
            else:
                arisk = _loss_tail_metrics(vals, initial_i)
            asset_scenarios.append({
                "ticker": ticker,
                "weight_pct": round(float(weights[i] * 100.0), 4),
                "initial_amount_kzt": round(float(asset_initial[i]), 2),
                "best_case_kzt": round(float(ap95), 2),
                "median_case_kzt": round(float(ap50), 2),
                "worst_case_kzt": round(float(ap5), 2),
                "var95_kzt": round(float(arisk["var95_kzt"]), 2),
                "cvar95_kzt": round(float(arisk["cvar95_kzt"]), 2),
            })

    out = {
        "amount_kzt": round(start, 2),
        "horizon_days": steps,
        "simulations": int(simulations),
        "block_size_days": int(block_size),
        "method": "Historical Stationary Bootstrap",
        "time_basis": f"{TRADING_DAYS} trading days = 1 year",
        "rebalancing": "buy_and_hold",
        "seed": seed,
        "scenarios": {
            "best_case_kzt": round(float(p95), 2),
            "median_case_kzt": round(float(p50), 2),
            "worst_case_kzt": round(float(p5), 2),
            "p05_return_pct": round((float(p5) / start - 1.0) * 100.0, 2),
            "worst_case_is_gain": bool(float(p5) > start),
            "best_case_pct": round((float(p95) / start - 1.0) * 100.0, 2),
            "median_case_pct": round((float(p50) / start - 1.0) * 100.0, 2),
            "worst_case_pct": round((float(p5) / start - 1.0) * 100.0, 2),
            **{k: round(float(v), 2) for k, v in risk.items() if k.endswith("_kzt")},
            **{k: round(float(v), 2) for k, v in risk.items() if k.endswith("_pct")},
        },
        "asset_scenarios": asset_scenarios,
        "chart": chart,
        "education": {
            "why": "Bootstrap не задаёт будущие доходности через нормальное распределение GBM. Он переиспользует реальные исторические совместные доходности выбранных активов и применяет ту же buy-and-hold политику, что и GBM.",
            "block": f"Используется stationary bootstrap со средней длиной блока около {block_size} торговых дней; фактическая длина блока меняется случайно.",
            "warning": "Исторический Bootstrap предполагает, что будущая структура рынка похожа на наблюдаемую историю. Это не гарантия и не предсказание конкретного события.",
        },
    }
    if return_terminal_values:
        out["_terminal_values"] = terminals.astype(float).tolist()
    if return_asset_terminal_values:
        out["_asset_terminal_values"] = asset_terminal.astype(float).tolist()
    return out

def analyze_portfolio(
    tickers: list[str],
    amount_kzt: float,
    record_fetcher: Callable[[str], dict] | None = None,
    chart_fetcher: Callable | None = None,
    curve_history: pd.DataFrame | None = None,
    include_historical_returns: bool = False,
    objective: str = "max_sharpe",
    risk_free_rate_pct: float = 0.0,
    concentration_mode: str = "constrained",
    include_etf_holdings: bool = True,
    covariance_method: str = "ledoit_wolf",
) -> dict:
    """Build a Markowitz efficient frontier and maximum-Sharpe allocation.

    The exact selected ticker set is preserved.  Missing history is an error;
    selected securities are never replaced by an automatically-added asset.
    """
    objective = str(objective or "max_sharpe").strip().lower()
    if objective not in {"max_sharpe", "min_variance", "equal_weight"}:
        raise ValueError("Цель портфеля должна быть max_sharpe, min_variance или equal_weight")
    selected = list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))
    if not selected:
        raise ValueError("Выберите хотя бы один актив")
    amount = _safe_float(amount_kzt)
    if amount is None or amount <= 0:
        raise ValueError("Сумма инвестирования должна быть больше 0")

    record_fetcher = record_fetcher or _record_for
    if chart_fetcher is None:
        from fetcher.chart import fetch_history
        chart_fetcher = fetch_history
    if curve_history is None:
        try:
            curve_history = get_curve_history(years=5)
        except TypeError:  # compatibility with injected/older implementations
            curve_history = get_curve_history()
        except Exception:
            curve_history = pd.DataFrame()

    records: dict[str, dict] = {}
    series_map: dict[str, pd.Series] = {}
    meta: dict[str, SeriesMeta] = {}
    warnings: list[str] = []
    missing: list[str] = []

    for raw in selected:
        rec = record_fetcher(raw) or {"ticker": raw, "name": raw, "asset_type": asset_type_for_ticker(raw)}
        ticker = raw
        at = rec.get("asset_type") or asset_type_for_ticker(ticker)
        records[ticker] = rec

        if at == "bond":
            s = _bond_return_series(rec, curve_history)
            hint_pct = _safe_float(rec.get("yield_pct"))
            if hint_pct is None:
                hint_pct = _safe_float(rec.get("coupon_pct"))
            hint = hint_pct / 100.0 if hint_pct is not None else None
            method = "5Y Treasury-yield duration proxy"
            currency = str(rec.get("currency") or "USD")
            if currency.upper() != "USD" and s is not None:
                fx = fetch_fx_history_usd(currency, period="5y")
                if fx is None or len(fx) < 20:
                    s = None
                else:
                    fx = fx.reindex(s.index).ffill()
                    fx_ret = fx.pct_change().reindex(s.index).fillna(0.0)
                    s = ((1.0 + s) * (1.0 + fx_ret) - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
                    method = "5Y Treasury-yield duration proxy, USD-normalized"
            if rec.get("market") != "US":
                warnings.append(f"{ticker}: риск облигации без свободной дневной цены оценён через Treasury-rate duration proxy.")
        else:
            try:
                hist = chart_fetcher(ticker, period="5y")
            except TypeError:
                hist = chart_fetcher(ticker)
            currency = str(rec.get("currency") or "USD").upper()
            s = _price_return_series(hist or {}, currency=currency)
            hint = None
            method = "5Y adjusted daily close, USD-normalized" if currency.upper() != "USD" else "5Y adjusted daily close (USD)"

        if s is None or len(s) < MIN_OBSERVATIONS:
            missing.append(ticker)
            continue

        quality, quality_warning = _history_quality(len(s))
        if quality_warning:
            warnings.append(f"{ticker}: {quality_warning}.")
        method = quality if at != "bond" else method + f" ({quality})"
        series_map[ticker] = s
        meta[ticker] = SeriesMeta(
            ticker=ticker,
            name=rec.get("name") or ticker,
            asset_type=at,
            market=rec.get("market") or rec.get("region") or "—",
            method=method,
            annual_return_hint=hint,
        )

    if missing:
        raise ValueError(
            "Недостаточно исторических данных (нужно примерно ≥1 года) для: " + ", ".join(missing) +
            ". Расчёт остановлен: выбранные активы не удаляются и не заменяются автоматически."
        )

    names = selected[:]
    # Pairwise correlations preserve observations across different exchange calendars.
    returns = pd.concat({t: series_map[t] for t in names}, axis=1).sort_index()
    corr_df = returns.corr(min_periods=MIN_OBSERVATIONS).reindex(index=names, columns=names)
    daily_cov_df = returns.cov(min_periods=MIN_OBSERVATIONS).reindex(index=names, columns=names)
    missing_pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if (not math.isfinite(float(corr_df.iloc[i, j])) or
                    not math.isfinite(float(daily_cov_df.iloc[i, j]))):
                overlap = int(returns[[names[i], names[j]]].dropna().shape[0])
                missing_pairs.append(f"{names[i]} + {names[j]} ({overlap} общих наблюдений)")
    if missing_pairs:
        raise ValueError(
            "Недостаточно совместных исторических наблюдений для расчёта covariance/correlation: "
            + "; ".join(missing_pairs)
            + f". Нужно не менее {MIN_OBSERVATIONS} общих торговых дней на каждую пару."
        )

    cov, cov_meta = _estimate_covariance(returns, names, covariance_method)
    vols = np.sqrt(np.maximum(np.diag(cov), 0.0))
    denom = np.outer(vols, vols)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 1e-18)
    corr = np.clip((corr + corr.T) / 2.0, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)

    mu = np.array([_expected_return(series_map[t], meta[t].annual_return_hint) for t in names])

    currencies = {str(records[t].get("currency") or "USD").upper() for t in names}
    if len(currencies) > 1 or "USD" not in currencies:
        warnings.append(
            "Базовая валюта портфеля — USD. Иностранные активы конвертируются в USD по историческим FX-курсам до расчёта доходностей, volatility и covariance."
        )

    concentration_mode = str(concentration_mode or "constrained").strip().lower()
    cap = _concentration_cap(len(names), concentration_mode)
    if include_etf_holdings:
        exposure_matrix, exposure_cap, exposure_details = _exposure_constraints(names, records, cap)
    else:
        exposure_matrix, exposure_cap, exposure_details = None, 1.0, {"_missing_etf_holdings": []}
    missing_etfs = (exposure_details or {}).get("_missing_etf_holdings", [])
    if missing_etfs:
        warnings.append("Не удалось получить состав ETF для: " + ", ".join(missing_etfs) + ". Look-through exposure для них не ограничена; проверьте состав фонда вручную.")
    rf_pct = _safe_float(risk_free_rate_pct)
    if rf_pct is None:
        raise ValueError("Некорректная безрисковая ставка")
    rf = float(rf_pct) / 100.0
    frontier, gmv = _efficient_frontier(mu, cov, cap, exposure_matrix=exposure_matrix, exposure_cap=exposure_cap)
    max_sharpe_weights = _max_sharpe(mu, cov, cap, rf, frontier, gmv, exposure_matrix, exposure_cap)
    if objective == "min_variance":
        weights = gmv.copy()
    elif objective == "equal_weight":
        weights = np.full(len(names), 1.0 / len(names), dtype=float)
    else:
        weights = max_sharpe_weights.copy()
    # Normalize tiny numerical residues once, before any UI/snapshot/downstream use.
    # This guarantees that a displayed 0% position is also exactly 0 in GBM/Bootstrap.
    weights = np.asarray(weights, dtype=float)
    weights[np.abs(weights) < 5e-4] = 0.0
    if float(weights.sum()) <= 0:
        raise RuntimeError("Оптимизатор вернул нулевой портфель")
    weights /= float(weights.sum())
    expected_return, portfolio_risk, sharpe = _portfolio_stats(weights, mu, cov, rf)
    gmv_return, gmv_risk, _ = _portfolio_stats(gmv, mu, cov, rf)
    max_sharpe_return, max_sharpe_risk, max_sharpe_ratio = _portfolio_stats(max_sharpe_weights, mu, cov, rf)

    allocation = []
    zero_weight_assets = []
    for i, ticker in enumerate(names):
        w = float(weights[i])
        rec = records[ticker]
        row = {
            "ticker": ticker,
            "name": rec.get("name") or ticker,
            "asset_type": rec.get("asset_type") or asset_type_for_ticker(ticker),
            "market": rec.get("market") or rec.get("region") or "—",
            "weight": float(weights[i]),
            "weight_pct": round(w * 100, 4),
            "amount_kzt": round(amount * w, 2),
        }
        allocation.append(row)
        if w == 0.0:
            zero_weight_assets.append({
                "ticker": ticker,
                "name": row["name"],
                "reason": (
                    "В исторической Markowitz-модели актив был учтён, но не снизил минимум дисперсии выбранного портфеля."
                    if objective == "min_variance" else
                    ("Equal Weight назначает одинаковые ненулевые веса всем допустимым активам." if objective == "equal_weight" else
                     "В исторической Markowitz-модели актив был учтён, но не улучшил максимальное соотношение excess return к риску при выбранной политике концентрации.")
                ),
            })

    # Reconcile numerical / currency rounding.  Use exact optimized weights for
    # the residual so a genuine 0%-asset never receives a positive purchase amount.
    if allocation:
        rounded_total = round(sum(float(r["amount_kzt"]) for r in allocation), 2)
        residual = round(amount - rounded_total, 2)
        if abs(residual) >= 0.01:
            positive = [i for i, w in enumerate(weights) if w > 0.0005]
            largest = max(positive, key=lambda i: weights[i]) if positive else int(np.argmax(weights))
            allocation[largest]["amount_kzt"] = round(allocation[largest]["amount_kzt"] + residual, 2)

    effective_exposure = {}
    for j, t in enumerate(names):
        w = float(weights[j])
        at = records[t].get("asset_type") or asset_type_for_ticker(t)
        if at == "etf":
            h = (exposure_details or {}).get(t, {}).get("holdings", {})
            for u, hw in h.items():
                effective_exposure[u] = effective_exposure.get(u, 0.0) + w * float(hw)
        else:
            effective_exposure[t] = effective_exposure.get(t, 0.0) + w
    top_exposures = [
        {"underlying": u, "effective_weight_pct": round(v * 100.0, 3)}
        for u, v in sorted(effective_exposure.items(), key=lambda kv: kv[1], reverse=True)
        if v > 1e-9
    ]

    individual = []
    for i, ticker in enumerate(names):
        individual.append({
            "ticker": ticker,
            "name": meta[ticker].name,
            "asset_type": meta[ticker].asset_type,
            "market": meta[ticker].market,
            "expected_return_pct": round(mu[i] * 100, 3),
            "historical_risk_pct": round(vols[i] * 100, 3),
            "history_method": meta[ticker].method,
            "observations": int(series_map[ticker].count()),
        })

    frontier_payload = []
    for pt in frontier:
        ret, risk, sh = _portfolio_stats(pt["weights"], mu, cov, rf)
        frontier_payload.append({
            "risk_pct": round(risk * 100, 4),
            "return_pct": round(ret * 100, 4),
            "sharpe": round(sh, 5) if math.isfinite(sh) else None,
        })

    expected_gain_kzt = amount * expected_return
    return {
        "amount_kzt": round(amount, 2),
        "selected": names,
        "used_assets": names,
        "excluded_assets": [],
        "portfolio": {
            "expected_return_pct": round(expected_return * 100, 3),
            "expected_gain_kzt": round(expected_gain_kzt, 2),
            "historical_risk_pct": round(portfolio_risk * 100, 3),
            "sharpe_ratio": round(float(sharpe), 4) if math.isfinite(sharpe) else None,
            "concentration_cap_pct": None,
            "risk_free_rate_pct": round(rf * 100, 3),
            "base_currency": "USD",
            "concentration_mode": concentration_mode,
            "max_position_weight_pct": round(cap * 100, 2),
            "method": ("1/N Equal Weight" if objective == "equal_weight" else "Markowitz Efficient Frontier + " + ("Maximum Sharpe" if objective == "max_sharpe" else "Minimum Variance")),
            "objective": objective,
        },
        "minimum_variance_portfolio": {
            "expected_return_pct": round(gmv_return * 100, 3),
            "historical_risk_pct": round(gmv_risk * 100, 3),
        },
        "allocation": allocation,
        "zero_weight_assets": zero_weight_assets,
        "exposure_analysis": {
            "direct_cap_pct": None,
            "effective_exposure_cap_pct": None,
            "etf_holdings": exposure_details,
            "top_effective_exposures": top_exposures[:20],
        },
        "individual_metrics": individual,
        "correlation": {
            "labels": names,
            "matrix": [[round(float(x), 4) for x in row] for row in corr],
        },
        "covariance": {
            "labels": names,
            "matrix": [[round(float(x), 8) for x in row] for row in cov],
            "units": "annualized return covariance",
            **cov_meta,
        },
        "efficient_frontier": {
            "points": frontier_payload,
            "max_sharpe": {
                "risk_pct": round(max_sharpe_risk * 100, 4),
                "return_pct": round(max_sharpe_return * 100, 4),
                "sharpe": round(float(max_sharpe_ratio), 5) if math.isfinite(max_sharpe_ratio) else None,
            },
            "minimum_variance": {
                "risk_pct": round(gmv_risk * 100, 4),
                "return_pct": round(gmv_return * 100, 4),
            },
        },
        "warnings": list(dict.fromkeys(warnings)),
        "_engine": {
            "names": names,
            "weights": [float(x) for x in weights],
            "expected_returns": [float(x) for x in mu],
            "covariance": [[float(x) for x in row] for row in cov],
            "covariance_method": cov_meta.get("method"),
            "covariance_label": cov_meta.get("label"),
            "covariance_observations": cov_meta.get("observations"),
            "covariance_shrinkage": cov_meta.get("shrinkage"),
            "risk_free_rate": float(rf),
            "base_currency": "USD",
            "concentration_mode": concentration_mode,
            "max_position_weight": float(cap),
            "time_basis_trading_days": TRADING_DAYS,
            "rebalancing": "buy_and_hold",
        },
        **({"_historical_returns": [
            {"date": str(idx.date()), "returns": {t: float(row[t]) for t in names if pd.notna(row[t])}}
            for idx, row in returns.dropna().iterrows()
        ]} if include_historical_returns else {}),
        "methodology": [
            "Only user-selected assets are included; no security is added automatically.",
            "Stocks/ETFs: up to five years of adjusted daily prices; approximately one year is the minimum accepted history.",
            "Expected annual return for stocks/ETFs: arithmetic mean of daily returns × 252.",
            ("Annual covariance: Ledoit-Wolf shrinkage on aligned USD-normalized daily returns × 252; matrix is projected to PSD for numerical safety." if cov_meta.get("method") == "ledoit_wolf" else "Annual covariance: pairwise sample covariance of USD-normalized daily returns × 252, projected to a numerically PSD matrix."),
            "Markowitz efficient frontier: minimum portfolio variance for a grid of target returns, long-only.",
            ("Academic unconstrained mode allows 0–100% per asset." if concentration_mode == "unconstrained" else f"Practical concentration policy caps each position at {cap * 100:.0f}% for {len(names)} selected assets."),
            "ETF look-through holdings may be displayed for transparency, but they do not constrain portfolio weights.",
            f"Maximum-Sharpe uses the automatically refreshed U.S. 13-week Treasury bill risk-free proxy: {rf * 100:.3f}% p.a.; the portfolio base currency is USD.",
            "A selected asset may receive 0% if it does not improve the optimal historical risk/return trade-off under the constraints.",
            "Historical estimates are educational model outputs, not forecasts or guarantees of future returns or maximum loss.",
        ],
    }
