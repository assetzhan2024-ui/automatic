"""Portfolio risk-contribution diagnostics for a frozen portfolio snapshot."""
from __future__ import annotations

import math
import numpy as np


def _as_engine(snapshot: dict) -> tuple[list[str], np.ndarray, np.ndarray, dict]:
    result = snapshot.get("result") or {}
    engine = result.get("_engine") or {}
    names = list(engine.get("names") or [])
    weights = np.asarray(engine.get("weights") or [], dtype=float)
    cov = np.asarray(engine.get("covariance") or [], dtype=float)
    if not names or weights.shape != (len(names),) or cov.shape != (len(names), len(names)):
        raise ValueError("Portfolio snapshot не содержит корректные frozen weights/covariance")
    if not np.all(np.isfinite(weights)) or not np.all(np.isfinite(cov)):
        raise ValueError("Portfolio snapshot содержит невалидные weights/covariance")
    if abs(float(weights.sum()) - 1.0) > 1e-7:
        raise ValueError("Frozen weights не суммируются к 100%")
    return names, weights, cov, engine


def concentration_metrics(weights: np.ndarray) -> dict:
    w = np.asarray(weights, dtype=float)
    hhi = float(np.sum(np.square(w)))
    effective_n = float(1.0 / hhi) if hhi > 1e-15 else None
    return {"hhi": hhi, "effective_n": effective_n}


def risk_contribution_from_arrays(names: list[str], weights: np.ndarray, cov: np.ndarray) -> dict:
    w = np.asarray(weights, dtype=float)
    c = np.asarray(cov, dtype=float)
    variance = float(w @ c @ w)
    if variance < -1e-10:
        raise ValueError("Covariance дала отрицательную portfolio variance")
    sigma = math.sqrt(max(variance, 0.0))
    marginal = (c @ w) / sigma if sigma > 1e-14 else np.zeros_like(w)
    contribution = w * marginal
    pct = contribution / sigma if sigma > 1e-14 else np.zeros_like(w)

    # Euler decomposition should reconcile to total volatility.
    if sigma > 1e-12 and abs(float(np.sum(contribution)) - sigma) > max(1e-8, sigma * 1e-7):
        raise RuntimeError("Risk Contribution integrity check failed")

    rows = []
    for i, ticker in enumerate(names):
        rows.append({
            "ticker": ticker,
            "weight_pct": round(float(w[i]) * 100.0, 4),
            "mrc": round(float(marginal[i]), 8),
            "mrc_pct_points_per_1_weight": round(float(marginal[i]) * 100.0, 6),
            "risk_contribution": round(float(contribution[i]), 8),
            "risk_contribution_vol_pct_points": round(float(contribution[i]) * 100.0, 6),
            "risk_share_pct": round(float(pct[i]) * 100.0, 4),
        })
    conc = concentration_metrics(w)
    return {
        "portfolio_volatility_pct": round(sigma * 100.0, 6),
        "rows": rows,
        "hhi": round(conc["hhi"], 8),
        "effective_n": round(float(conc["effective_n"]), 6) if conc["effective_n"] is not None else None,
        "identity_check": {
            "sum_risk_contribution_pct_points": round(float(np.sum(contribution)) * 100.0, 6),
            "sum_risk_share_pct": round(float(np.sum(pct)) * 100.0, 6),
        },
    }


def analyze_snapshot_risk_contribution(snapshot: dict) -> dict:
    names, weights, cov, engine = _as_engine(snapshot)
    out = risk_contribution_from_arrays(names, weights, cov)
    out["covariance_method"] = engine.get("covariance_method") or "sample"
    out["covariance_label"] = engine.get("covariance_label") or "Sample Covariance"
    out["covariance_observations"] = engine.get("covariance_observations")
    out["note"] = (
        "MRC требует covariance matrix Σ, но не требует именно Ledoit-Wolf. "
        "Если выбран Ledoit-Wolf, MRC/RC используют shrinkage covariance; если Sample — sample covariance."
    )
    return out
