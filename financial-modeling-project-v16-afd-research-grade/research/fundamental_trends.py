"""Fundamental Trend Engine.

Transforms already-fetched annual financial statements into transparent trends.
No synthetic values are created: missing source fields remain unavailable.
"""
from __future__ import annotations

from typing import Any
import math


ALIASES = {
    "revenue": ("Total Revenue", "Operating Revenue", "Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_income": ("Operating Income", "Operating Income Loss"),
    "net_income": ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"),
    "eps": ("Diluted EPS", "Basic EPS", "Normalized Diluted EPS", "Reported EPS"),
    "ocf": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "fcf": ("Free Cash Flow",),
    "capex": ("Capital Expenditure", "Capital Expenditures"),
    "total_debt": ("Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"),
    "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash And Cash Equivalents And Federal Funds Sold"),
}


def _finite(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _pick(row: dict, names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in row:
            v = _finite(row.get(name))
            if v is not None:
                return v
    return None


def _years(fd: dict) -> list[str]:
    years = set()
    for section in ("income", "balance", "cashflow"):
        years.update(str(y) for y in (fd.get(section) or {}).keys() if str(y).isdigit())
    return sorted(years)


def _series(fd: dict, key: str) -> dict[str, float | None]:
    section = "income" if key in {"revenue", "gross_profit", "operating_income", "net_income", "eps"} else "cashflow" if key in {"ocf", "fcf", "capex"} else "balance"
    src = fd.get(section) or {}
    return {y: _pick(src.get(y) or {}, ALIASES[key]) for y in _years(fd)}


def _yoy(values: dict[str, float | None]) -> dict[str, float | None]:
    ys = sorted(values)
    out: dict[str, float | None] = {}
    for i, y in enumerate(ys):
        if i == 0:
            out[y] = None
            continue
        prev, cur = values.get(ys[i - 1]), values.get(y)
        if prev in (None, 0) or cur is None:
            out[y] = None
        else:
            out[y] = (cur - prev) / abs(prev) * 100.0
    return out


def _cagr(values: dict[str, float | None]) -> float | None:
    valid = [(y, v) for y, v in sorted(values.items()) if v is not None]
    if len(valid) < 2:
        return None
    y0, v0 = valid[0]
    y1, v1 = valid[-1]
    n = int(y1) - int(y0)
    # Classical CAGR is not meaningful when the start/end values are <= 0.
    if n <= 0 or v0 <= 0 or v1 <= 0:
        return None
    return ((v1 / v0) ** (1.0 / n) - 1.0) * 100.0


def _latest_two_changes(yoy: dict[str, float | None]) -> tuple[float | None, float | None, float | None]:
    vals = [(y, v) for y, v in sorted(yoy.items()) if v is not None]
    if not vals:
        return None, None, None
    latest = vals[-1][1]
    prior = vals[-2][1] if len(vals) > 1 else None
    accel = latest - prior if prior is not None else None
    return latest, prior, accel


def _trend_label(latest_yoy: float | None, acceleration: float | None) -> str:
    if latest_yoy is None:
        return "insufficient_data"
    if latest_yoy > 0:
        if acceleration is not None and acceleration > 2:
            return "growth_accelerating"
        if acceleration is not None and acceleration < -2:
            return "growth_decelerating"
        return "growing"
    if latest_yoy < 0:
        if acceleration is not None and acceleration > 2:
            return "decline_moderating"
        return "declining"
    return "flat"


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def build_fundamental_trends(fd: dict) -> dict:
    if not fd or fd.get("error"):
        return {"error": "fundamentals_unavailable", "ticker": (fd or {}).get("ticker")}

    years = _years(fd)
    if len(years) < 2:
        return {"error": "insufficient_history", "ticker": fd.get("ticker"), "years": years}

    metrics: dict[str, dict] = {}
    for key in ("revenue", "net_income", "eps", "fcf", "total_debt"):
        vals = _series(fd, key)
        yoy = _yoy(vals)
        latest, prior, acceleration = _latest_two_changes(yoy)
        metrics[key] = {
            "values": vals,
            "yoy_pct": yoy,
            "latest_yoy_pct": latest,
            "previous_yoy_pct": prior,
            "acceleration_pp": acceleration,
            "cagr_pct": _cagr(vals),
            "trend": _trend_label(latest, acceleration),
        }

    revenue = _series(fd, "revenue")
    gross_profit = _series(fd, "gross_profit")
    operating_income = _series(fd, "operating_income")
    net_income = _series(fd, "net_income")
    ocf = _series(fd, "ocf")
    fcf = _series(fd, "fcf")

    margins = {
        "gross_margin_pct": {y: _ratio(gross_profit.get(y), revenue.get(y)) for y in years},
        "operating_margin_pct": {y: _ratio(operating_income.get(y), revenue.get(y)) for y in years},
        "net_margin_pct": {y: _ratio(net_income.get(y), revenue.get(y)) for y in years},
        "fcf_margin_pct": {y: _ratio(fcf.get(y), revenue.get(y)) for y in years},
    }
    cash_conversion = {
        "ocf_to_net_income_pct": {y: _ratio(ocf.get(y), net_income.get(y)) for y in years},
        "fcf_to_net_income_pct": {y: _ratio(fcf.get(y), net_income.get(y)) for y in years},
    }

    latest_year = years[-1]
    previous_year = years[-2]
    return {
        "ticker": fd.get("ticker"),
        "years": years[-5:],
        "latest_year": latest_year,
        "previous_year": previous_year,
        "metrics": metrics,
        "margins": margins,
        "cash_conversion": cash_conversion,
        "methodology": {
            "annualization": "reported annual financial statements",
            "cagr": "CAGR is returned only when beginning and ending values are positive",
            "missing_data": "missing provider fields are never imputed",
        },
    }
