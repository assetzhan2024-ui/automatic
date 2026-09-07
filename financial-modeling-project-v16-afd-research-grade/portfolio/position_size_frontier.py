"""Marginal portfolio-impact and Position Size Frontier analysis.

The module starts from an immutable portfolio snapshot, adds one candidate at a
user-selected weight using proportional funding, and evaluates the same
candidate from 0% to 20%. It does not re-optimize the existing holdings.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from config.markets import asset_type_for_ticker, symbol_market
from fetcher.chart import fetch_history
from fetcher.ticker import fetch_ticker
from portfolio.optimizer import TRADING_DAYS, _price_return_series, _estimate_covariance
from portfolio.risk_contribution import concentration_metrics, risk_contribution_from_arrays


def _snapshot_returns(snapshot: dict, names: list[str]) -> pd.DataFrame:
    rows = snapshot.get("historical_returns") or []
    records = []
    for row in rows:
        dt = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(dt):
            continue
        vals = row.get("returns") or {}
        rec = {"date": dt}
        ok = True
        for t in names:
            try:
                v = float(vals[t])
            except Exception:
                ok = False
                break
            if not math.isfinite(v):
                ok = False
                break
            rec[t] = v
        if ok:
            records.append(rec)
    if not records:
        raise ValueError("Portfolio snapshot не содержит совместную historical return history")
    return pd.DataFrame(records).set_index("date").sort_index()


def _candidate_returns(ticker: str) -> tuple[pd.Series, dict]:
    rec = fetch_ticker(ticker)
    at = rec.get("asset_type") or asset_type_for_ticker(ticker)
    if at == "bond":
        raise ValueError("Position Size Frontier для прямой облигации требует real traded total-return history; используйте bond ETF")
    history = fetch_history(ticker, period="5y")
    currency = str(rec.get("currency") or "USD").upper()
    returns = _price_return_series(history, currency=currency)
    if returns is None or len(returns) < 190:
        raise ValueError(f"{ticker}: недостаточно исторических данных для Position Size Frontier")
    return returns.rename(ticker), rec


def _stationary_bootstrap_growth(matrix: np.ndarray, *, simulations: int = 3000, horizon_days: int = 252, block_size: int = 21, seed: int = 314159) -> np.ndarray:
    """Return simulated terminal growth factors for each asset.

    A single stationary-bootstrap sample is shared across every tested candidate
    weight. That makes the frontier comparable and much faster than re-running a
    separate bootstrap for each 1% weight.
    """
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or len(x) < 60:
        raise ValueError("Недостаточно совместной return history для bootstrap CVaR")
    if np.any(x <= -1.0):
        raise ValueError("Historical return <= -100% обнаружена; bootstrap growth некорректен")
    rng = np.random.default_rng(seed)
    sims = int(simulations)
    steps = int(horizon_days)
    n_hist, n_assets = x.shape
    restart_prob = 1.0 / float(block_size)
    current = rng.integers(0, n_hist, size=sims)
    growth = np.ones((sims, n_assets), dtype=float)
    for _ in range(steps):
        growth *= (1.0 + x[current, :])
        restart = rng.random(sims) < restart_prob
        fresh = rng.integers(0, n_hist, size=sims)
        current = np.where(restart, fresh, (current + 1) % n_hist)
    return growth


def _terminal_cvar_pct(growth: np.ndarray, weights: np.ndarray) -> float:
    terminal = np.asarray(growth, dtype=float) @ np.asarray(weights, dtype=float)
    losses = 1.0 - terminal
    var = float(np.percentile(losses, 95))
    tail = losses[losses >= var - 1e-12]
    cvar = float(np.mean(tail)) if len(tail) else var
    return max(0.0, cvar) * 100.0


def _portfolio_beta(common_returns: pd.DataFrame, weights: np.ndarray, names: list[str], candidate_record: dict) -> tuple[float | None, str | None]:
    markets = {symbol_market(t) for t in names}
    if len(markets) != 1:
        return None, "Mixed-market portfolio: one local-market beta is not economically comparable"
    market = next(iter(markets))
    try:
        from research.capm import MARKETS
        cfg = MARKETS.get(market)
        if not cfg:
            return None, "No benchmark configured"
        h = fetch_history(cfg["benchmark"], period="5y")
        bret = _price_return_series(h, currency=str(cfg.get("currency") or "USD"))
        if bret is None:
            fb = cfg.get("benchmark_fallback")
            if fb:
                h = fetch_history(fb, period="5y")
                bret = _price_return_series(h, currency=str(cfg.get("currency") or "USD"))
        if bret is None:
            return None, "Benchmark history unavailable"
        p = common_returns[names].to_numpy(float) @ weights
        ps = pd.Series(p, index=common_returns.index, name="p")
        aligned = pd.concat([ps, bret.rename("m")], axis=1, join="inner").dropna()
        if len(aligned) < 60 or float(aligned["m"].var()) <= 1e-18:
            return None, "Insufficient aligned benchmark observations"
        beta = float(aligned["p"].cov(aligned["m"]) / aligned["m"].var())
        return beta, cfg.get("benchmark_name") or cfg.get("benchmark")
    except Exception as exc:
        return None, str(exc)


def _weights_after(existing_weights: np.ndarray, candidate_weight: float) -> np.ndarray:
    x = float(candidate_weight)
    if x < 0 or x >= 1:
        raise ValueError("Candidate weight должен быть в диапазоне [0,1)")
    existing = (1.0 - x) * np.asarray(existing_weights, dtype=float)
    return np.concatenate([existing, np.array([x])])


def analyze_position_size_frontier(
    snapshot: dict,
    candidate: str,
    *,
    selected_weight_pct: float = 5.0,
    max_weight_pct: int = 20,
    step_pct: int = 1,
    bootstrap_simulations: int = 3000,
    bootstrap_block_size: int = 21,
) -> dict:
    result = snapshot.get("result") or {}
    engine = result.get("_engine") or {}
    base_names = list(engine.get("names") or [])
    base_weights = np.asarray(engine.get("weights") or [], dtype=float)
    base_mu = np.asarray(engine.get("expected_returns") or [], dtype=float)
    if not base_names or len(base_weights) != len(base_names) or len(base_mu) != len(base_names):
        raise ValueError("Portfolio snapshot повреждён")
    candidate = str(candidate or "").strip().upper()
    if not candidate:
        raise ValueError("Укажите candidate ticker")
    if candidate in base_names:
        raise ValueError(f"{candidate} уже находится в текущем портфеле")
    selected_weight_pct = float(selected_weight_pct)
    if not (0.0 <= selected_weight_pct <= float(max_weight_pct)):
        raise ValueError(f"Candidate weight должен быть 0–{max_weight_pct}%")

    base_df = _snapshot_returns(snapshot, base_names)
    cand, cand_rec = _candidate_returns(candidate)
    common = pd.concat([base_df, cand], axis=1, join="inner").dropna(how="any")
    if len(common) < 190:
        raise ValueError(f"Недостаточно совместной истории портфеля и {candidate}: {len(common)} дней")

    names = base_names + [candidate]
    cov_method = str(engine.get("covariance_method") or "ledoit_wolf")
    cov, cov_meta = _estimate_covariance(common[names], names, cov_method)
    cand_mu = float(common[candidate].mean() * TRADING_DAYS)
    mu = np.concatenate([base_mu, np.array([cand_mu])])
    rf = float(engine.get("risk_free_rate") or 0.0)

    growth = _stationary_bootstrap_growth(
        common[names].to_numpy(float), simulations=bootstrap_simulations,
        horizon_days=TRADING_DAYS, block_size=bootstrap_block_size,
    )

    base_port_daily = common[base_names].to_numpy(float) @ base_weights
    corr_candidate = float(np.corrcoef(base_port_daily, common[candidate].to_numpy(float))[0, 1])
    if not math.isfinite(corr_candidate):
        corr_candidate = None

    frontier = []
    for wpct in range(0, int(max_weight_pct) + 1, int(step_pct)):
        w = _weights_after(base_weights, wpct / 100.0)
        ret = float(w @ mu)
        variance = float(max(w @ cov @ w, 0.0))
        vol = math.sqrt(variance)
        sharpe = (ret - rf) / vol if vol > 1e-14 else None
        rc = risk_contribution_from_arrays(names, w, cov)
        conc = concentration_metrics(w)
        cvar = _terminal_cvar_pct(growth, w)
        frontier.append({
            "candidate_weight_pct": float(wpct),
            "expected_return_pct": round(ret * 100.0, 4),
            "volatility_pct": round(vol * 100.0, 4),
            "sharpe": round(float(sharpe), 5) if sharpe is not None and math.isfinite(sharpe) else None,
            "cvar95_pct": round(cvar, 4),
            "risk_share_pct": next((r["risk_share_pct"] for r in rc["rows"] if r["ticker"] == candidate), None),
            "mrc": next((r["mrc"] for r in rc["rows"] if r["ticker"] == candidate), None),
            "hhi": round(float(conc["hhi"]), 6),
            "effective_n": round(float(conc["effective_n"]), 4) if conc["effective_n"] is not None else None,
        })

    def argmin(key): return min(frontier, key=lambda r: float(r[key]) if r.get(key) is not None else float("inf"))
    def argmax(key): return max(frontier, key=lambda r: float(r[key]) if r.get(key) is not None else -float("inf"))
    min_vol = argmin("volatility_pct")
    max_sharpe = argmax("sharpe")
    min_cvar = argmin("cvar95_pct")
    cvar_worsens = None
    start_idx = frontier.index(min_cvar)
    for i in range(start_idx + 1, len(frontier)):
        if frontier[i]["cvar95_pct"] > frontier[i-1]["cvar95_pct"] + 1e-8:
            cvar_worsens = frontier[i]
            break
    risk15 = next((r for r in frontier if r.get("risk_share_pct") is not None and float(r["risk_share_pct"]) > 15.0), None)

    chosen = min(frontier, key=lambda r: abs(float(r["candidate_weight_pct"]) - selected_weight_pct))
    before = frontier[0]
    after_w = _weights_after(base_weights, chosen["candidate_weight_pct"] / 100.0)
    rc_after = risk_contribution_from_arrays(names, after_w, cov)
    candidate_rc = next(r for r in rc_after["rows"] if r["ticker"] == candidate)
    beta_before, beta_benchmark = _portfolio_beta(common[base_names], base_weights, base_names, cand_rec)
    beta_after, _ = _portfolio_beta(common[names], after_w, names, cand_rec)

    return {
        "module": "Position Size Frontier",
        "candidate": candidate,
        "funding_rule": "proportional",
        "funding_formula": "w'_j = (1 - x) * w_j; candidate weight = x",
        "covariance": cov_meta,
        "common_history_observations": int(len(common)),
        "candidate_expected_return_pct": round(cand_mu * 100.0, 4),
        "candidate_expected_return_method": "historical arithmetic mean daily return × 252; research expected return can replace this in the future research portfolio mode",
        "correlation_with_current_portfolio": round(corr_candidate, 4) if corr_candidate is not None else None,
        "frontier": frontier,
        "key_points": {
            "maximum_sharpe_weight_pct": max_sharpe["candidate_weight_pct"],
            "minimum_volatility_weight_pct": min_vol["candidate_weight_pct"],
            "minimum_cvar_weight_pct": min_cvar["candidate_weight_pct"],
            "cvar_starts_worsening_weight_pct": cvar_worsens["candidate_weight_pct"] if cvar_worsens else None,
            "risk_share_above_15_weight_pct": risk15["candidate_weight_pct"] if risk15 else None,
        },
        "selected_weight_pct": chosen["candidate_weight_pct"],
        "marginal_impact": {
            "before": {
                "expected_return_pct": before["expected_return_pct"],
                "volatility_pct": before["volatility_pct"],
                "sharpe": before["sharpe"],
                "cvar95_pct": before["cvar95_pct"],
                "portfolio_beta": round(beta_before, 4) if beta_before is not None else None,
                "hhi": before["hhi"],
                "effective_n": before["effective_n"],
            },
            "after": {
                "expected_return_pct": chosen["expected_return_pct"],
                "volatility_pct": chosen["volatility_pct"],
                "sharpe": chosen["sharpe"],
                "cvar95_pct": chosen["cvar95_pct"],
                "portfolio_beta": round(beta_after, 4) if beta_after is not None else None,
                "hhi": chosen["hhi"],
                "effective_n": chosen["effective_n"],
            },
            "candidate": {
                "capital_weight_pct": chosen["candidate_weight_pct"],
                "risk_contribution_pct_points": candidate_rc["risk_contribution_vol_pct_points"],
                "risk_share_pct": candidate_rc["risk_share_pct"],
                "mrc": candidate_rc["mrc"],
                "correlation_with_current_portfolio": round(corr_candidate, 4) if corr_candidate is not None else None,
            },
            "portfolio_beta_benchmark": beta_benchmark,
        },
        "tail_risk": {
            "model": "Stationary Bootstrap one-year terminal CVaR 95%",
            "simulations": int(bootstrap_simulations),
            "horizon_days": TRADING_DAYS,
            "mean_block_days": int(bootstrap_block_size),
            "shared_paths_across_weights": True,
        },
        "methodology": [
            "Existing portfolio weights are not re-optimized; the candidate is funded proportionally from every existing holding.",
            "All frontier points use the same aligned return window and the same covariance estimator.",
            "MRC/RC use the selected covariance matrix; Ledoit-Wolf is preferred for stability but is not mathematically required for MRC.",
            "CVaR uses one shared stationary-bootstrap simulation set across all candidate weights, avoiding apples-to-oranges random-path differences.",
        ],
    }
