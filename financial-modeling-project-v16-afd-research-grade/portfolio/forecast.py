"""Downstream risk-model orchestration for an immutable Markowitz snapshot."""
from __future__ import annotations

from portfolio.optimizer import simulate_portfolio_gbm, simulate_portfolio_bootstrap


def run_snapshot_forecast(
    snapshot: dict,
    *,
    model: str,
    horizon_days: int = 252,
    simulations: int = 10_000,
    block_size: int = 21,
    seed: int | None = None,
) -> dict:
    """Run one risk model without rerunning portfolio optimization.

    The exact optimized weights, expected returns and covariance stored in the
    snapshot are used. Both risk models use the same buy-and-hold policy and
    trading-day time basis.
    """
    result = snapshot.get("result") or {}
    historical_returns = snapshot.get("historical_returns") or []
    engine = result.get("_engine") or {}
    names = list(engine.get("names") or result.get("selected") or [])
    exact_weights = list(engine.get("weights") or [])
    exact_mu = list(engine.get("expected_returns") or [])
    exact_covariance = engine.get("covariance") or result.get("covariance", {}).get("matrix")

    if not names or len(exact_weights) != len(names) or len(exact_mu) != len(names):
        raise ValueError("Portfolio snapshot повреждён: отсутствуют точные параметры Markowitz")

    by_alloc = {str(row.get("ticker") or "").upper(): row for row in result.get("allocation", [])}
    by_metric = {str(row.get("ticker") or "").upper(): row for row in result.get("individual_metrics", [])}
    allocation_exact = []
    metrics_exact = []
    for i, ticker in enumerate(names):
        row = dict(by_alloc.get(ticker, {"ticker": ticker}))
        row["weight"] = float(exact_weights[i])
        row["weight_pct"] = float(exact_weights[i]) * 100.0
        allocation_exact.append(row)

        metric = dict(by_metric.get(ticker, {"ticker": ticker}))
        metric["expected_return_pct"] = float(exact_mu[i]) * 100.0
        metrics_exact.append(metric)

    model = str(model or "gbm").strip().lower()
    if model == "gbm":
        forecast = simulate_portfolio_gbm(
            amount_kzt=result["amount_kzt"],
            allocation=allocation_exact,
            individual_metrics=metrics_exact,
            covariance=exact_covariance,
            horizon_days=horizon_days,
            simulations=simulations,
            seed=seed,
        )
    elif model == "bootstrap":
        forecast = simulate_portfolio_bootstrap(
            amount_kzt=result["amount_kzt"],
            allocation=allocation_exact,
            historical_returns=historical_returns,
            horizon_days=horizon_days,
            simulations=simulations,
            block_size=block_size,
            seed=seed,
        )
    else:
        raise ValueError("Модель должна быть gbm или bootstrap")

    forecast["portfolio_objective"] = result.get("portfolio", {}).get("objective")
    forecast["portfolio_weights"] = [
        {"ticker": names[i], "weight": float(exact_weights[i]), "weight_pct": float(exact_weights[i]) * 100.0}
        for i in range(len(names))
    ]
    return forecast
