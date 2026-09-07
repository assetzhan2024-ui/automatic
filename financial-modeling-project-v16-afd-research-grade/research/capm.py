"""Local-market CAPM analytics with automatic data refresh.

Developed markets use a standard local CAPM. Kazakhstan uses a country-risk
adjusted form when current country-risk-premium data are available.

Current model:
    Developed: Ke = Rf + beta * ERP_country
    Kazakhstan: Ke = (local sovereign yield - default spread)
                    + beta * MatureERP + CRP

For Kazakhstan the local sovereign yield is not treated as literally risk-free.
The country default spread is removed first, then the equity country-risk
premium is added separately. This avoids mechanically counting sovereign risk
twice. If the default-spread input is unavailable, Required Return remains N/A.

Beta is estimated from weekly stock/benchmark returns over a 2-year rolling
window. Risk-free rates and ERP/CRP are fetched automatically and cached on
disk; stale values are explicitly labelled rather than silently fabricated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from fetcher.chart import fetch_history
from fetcher.risk_free import get_usd_risk_free_rate

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
RF_CACHE = CACHE_DIR / "capm_risk_free.json"
ERP_CACHE = CACHE_DIR / "capm_country_erp.json"
LOCK = threading.RLock()
RF_TTL = 60 * 60        # 1 hour: new published values are picked up automatically
ERP_TTL = 24 * 60 * 60  # 1 day: Damodaran updates are infrequent

MARKETS = {
    "US": {"country":"United States", "benchmark":"^GSPC", "benchmark_name":"S&P 500", "currency":"USD", "rf_series":"DGS10"},
    "London": {"country":"United Kingdom", "benchmark":"^FTSE", "benchmark_name":"FTSE 100", "currency":"GBP", "rf_series":"IRLTLT01GBM156N"},
    "Japan": {"country":"Japan", "benchmark":"^TOPX", "benchmark_name":"TOPIX", "benchmark_fallback":"^N225", "benchmark_fallback_name":"Nikkei 225", "currency":"JPY", "rf_series":"IRLTLT01JPM156N"},
    "France": {"country":"France", "benchmark":"^FCHI", "benchmark_name":"CAC 40", "currency":"EUR", "rf_series":"IRLTLT01FRM156N"},
    "Australia": {"country":"Australia", "benchmark":"^AXJO", "benchmark_name":"S&P/ASX 200", "benchmark_fallback":"^AORD", "benchmark_fallback_name":"All Ordinaries", "currency":"AUD", "rf_series":"IRLTLT01AUM156N"},
    "Kazakhstan": {"country":"Kazakhstan", "benchmark":"^KZKAK", "benchmark_name":"KASE Index", "currency":"KZT", "rf_series":None},
}

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
DAMODARAN_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx"
KASE_RF_URL = "https://kase.kz/en/indexes-and-indicators/gsecs/kzgb-ym1m"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _http_bytes(url: str, timeout: int = 7) -> bytes:
    req = Request(url, headers={"User-Agent":"Mozilla/5.0 PortfolioResearch/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def _fred_series(series: str) -> pd.Series:
    raw = _http_bytes(FRED_URL.format(series=series), timeout=7).decode("utf-8", errors="replace")
    df = pd.read_csv(StringIO(raw))
    if df.empty or len(df.columns) < 2:
        return pd.Series(dtype=float)
    ds = pd.to_datetime(df.iloc[:, 0], errors="coerce")
    vals = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s = pd.Series(vals.values, index=ds).dropna().sort_index()
    return s


def _kase_rf_latest() -> dict | None:
    html = _http_bytes(KASE_RF_URL, timeout=7).decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # The official page labels KZGB_Ym1m as the yield indicator and prints a
    # 'recent value' followed by its date/time. Keep parsing narrow.
    m = re.search(r"KZGB_Ym1m.{0,500}?([0-9]{1,2}[,.][0-9]{1,4})\s*(?:recent value|%)", text, re.I)
    if not m:
        m = re.search(r"([0-9]{1,2}[,.][0-9]{1,4})\s*recent value\s*,?\s*%", text, re.I)
    if not m:
        return None
    rate = float(m.group(1).replace(",", "."))
    dm = re.search(r"Time of recent data:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})", text, re.I)
    as_of = datetime.now(timezone.utc).date().isoformat()
    if dm:
        try: as_of = datetime.strptime(dm.group(1), "%d.%m.%Y").date().isoformat()
        except Exception: pass
    return {"rate_pct":rate, "as_of":as_of, "source":"KASE KZGB_Ym1m", "instrument":"Kazakhstan Ministry of Finance government-securities yield indicator", "stale":False}


def get_market_risk_free(market: str, *, force_refresh: bool = False) -> dict:
    market = market if market in MARKETS else "US"
    with LOCK:
        cache = _read_json(RF_CACHE)
        item = cache.get(market) if isinstance(cache, dict) else None
        if item and not force_refresh and time.time() - float(item.get("fetched_ts", 0) or 0) < RF_TTL:
            return dict(item)

        live = None
        try:
            if market == "Kazakhstan":
                live = _kase_rf_latest()
            else:
                series = MARKETS[market]["rf_series"]
                s = _fred_series(series)
                if not s.empty:
                    obs_date = s.index[-1].date()
                    age_days = (datetime.now(timezone.utc).date() - obs_date).days
                    live = {
                        "rate_pct": float(s.iloc[-1]),
                        "as_of": obs_date.isoformat(),
                        "source": f"FRED/OECD {series}" if series != "DGS10" else "FRED DGS10 (U.S. Treasury)",
                        "instrument": "10-year government bond yield",
                        "stale": age_days > (7 if series == "DGS10" else 45),
                        "age_days": int(age_days),
                    }
        except Exception:
            live = None

        # US remains usable if FRED is unavailable because the project already
        # has an automatic Treasury-bill provider. We disclose the fallback.
        if live is None and market == "US":
            base = get_usd_risk_free_rate(force_refresh=force_refresh)
            live = {**base, "instrument": base.get("instrument") or "13-week U.S. Treasury bill", "source": str(base.get("source") or "") + " · CAPM fallback"}

        if live:
            live["fetched_ts"] = time.time()
            cache[market] = live
            _write_json(RF_CACHE, cache)
            return dict(live)
        if item:
            out = dict(item); out["stale"] = True; out["source"] = str(out.get("source") or "cached") + " (cached)"
            return out
        return {"rate_pct":None, "as_of":None, "source":"unavailable", "instrument":"10-year government bond yield", "stale":True}


def _pct_value(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, str):
        s = v.strip().replace("%", "").replace(",", "")
        try: return float(s)
        except Exception: return None
    try:
        x = float(v)
        # Excel may store percentages as 0.0508 rather than 5.08.
        return x * 100.0 if abs(x) <= 1.0 else x
    except Exception:
        return None


def _download_country_erp() -> dict[str, dict]:
    raw = _http_bytes(DAMODARAN_URL, timeout=10)
    sheets = pd.read_excel(BytesIO(raw), sheet_name=None, engine="openpyxl")

    def parse_table(tmp: pd.DataFrame) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if tmp is None or tmp.empty:
            return out
        cols = [str(c).strip() for c in tmp.columns]
        tmp = tmp.copy(); tmp.columns = cols
        country_col = next((c for c in cols if c.lower() == "country"), None)
        erp_cols = [c for c in cols if "equity risk premium" in c.lower()]
        crp_cols = [c for c in cols if "country risk premium" in c.lower()]
        default_spread_cols = [c for c in cols if "default spread" in c.lower()]
        if not country_col or not erp_cols:
            return out
        erp_col = next((c for c in erp_cols if "total" in c.lower()), erp_cols[0])
        crp_col = crp_cols[0] if crp_cols else None
        default_spread_col = default_spread_cols[0] if default_spread_cols else None
        for _, row in tmp.iterrows():
            country = str(row.get(country_col) or "").strip()
            if not country or country.lower() in {"nan", "none"}:
                continue
            erp = _pct_value(row.get(erp_col))
            crp = _pct_value(row.get(crp_col)) if crp_col else 0.0
            default_spread = _pct_value(row.get(default_spread_col)) if default_spread_col else None
            if erp is not None:
                out[country.lower()] = {
                    "total_erp_pct": erp,
                    "country_risk_premium_pct": crp or 0.0,
                    "default_spread_pct": default_spread,
                }
        return out

    for df in sheets.values():
        # Most workbook versions are already parsed with the real header.
        rows = parse_table(df)
        if rows:
            return rows
        # Older/newer versions may contain title rows before the header.
        # Work from the already-loaded cells by reconstructing potential headers.
        for header_row in range(min(12, len(df))):
            vals = [str(x).strip() for x in df.iloc[header_row].tolist()]
            if any(x.lower() == "country" for x in vals):
                tmp = pd.DataFrame(df.iloc[header_row + 1:].values, columns=vals)
                rows = parse_table(tmp)
                if rows:
                    return rows
    return {}


def get_country_erp(market: str, *, force_refresh: bool = False) -> dict:
    market = market if market in MARKETS else "US"
    country = MARKETS[market]["country"]
    with LOCK:
        cache = _read_json(ERP_CACHE)
        fetched_ts = float(cache.get("fetched_ts", 0) or 0) if isinstance(cache, dict) else 0
        rows = cache.get("rows", {}) if isinstance(cache, dict) else {}
        if (force_refresh or not rows or time.time() - fetched_ts >= ERP_TTL):
            try:
                rows = _download_country_erp()
                if rows:
                    cache = {"fetched_ts":time.time(), "as_of":datetime.now(timezone.utc).date().isoformat(), "source":"Aswath Damodaran country risk premium dataset", "rows":rows}
                    _write_json(ERP_CACHE, cache)
            except Exception:
                pass
        rec = (rows or {}).get(country.lower())
        if rec:
            return {**rec, "as_of":cache.get("as_of"), "source":cache.get("source"), "stale": bool(time.time() - float(cache.get("fetched_ts",0) or 0) >= ERP_TTL * 2)}
        return {"total_erp_pct":None, "country_risk_premium_pct":None, "default_spread_pct":None, "as_of":None, "source":"unavailable", "stale":True}


def _history_series(history: dict) -> pd.Series:
    if not history or history.get("error"):
        return pd.Series(dtype=float)
    idx = pd.to_datetime(history.get("dates") or [], errors="coerce")
    vals = pd.to_numeric(history.get("closes") or [], errors="coerce")
    s = pd.Series(vals, index=idx).replace([np.inf,-np.inf], np.nan).dropna()
    s = s[s > 0]
    return s[~s.index.duplicated(keep="last")].sort_index()


def _weekly_returns(s: pd.Series) -> pd.Series:
    if s.empty:
        return pd.Series(dtype=float)
    return s.resample("W-FRI").last().pct_change().replace([np.inf,-np.inf], np.nan).dropna()


def _rolling_beta(stock: pd.Series, market: pd.Series, window: int = 104, min_obs: int = 52) -> pd.Series:
    df = pd.concat([stock.rename("s"), market.rename("m")], axis=1, join="inner").dropna()
    if len(df) < min_obs:
        return pd.Series(dtype=float)
    cov = df["s"].rolling(window=window, min_periods=min_obs).cov(df["m"])
    var = df["m"].rolling(window=window, min_periods=min_obs).var()
    beta = (cov / var.replace(0, np.nan)).replace([np.inf,-np.inf], np.nan).dropna()
    return beta


def _benchmark_history(config: dict) -> tuple[str, str, dict]:
    primary = config["benchmark"]
    h = fetch_history(primary, period="5y")
    if (h.get("error") or len(h.get("closes") or []) < 80) and config.get("benchmark_fallback"):
        fb = config["benchmark_fallback"]
        h2 = fetch_history(fb, period="5y")
        if not h2.get("error") and len(h2.get("closes") or []) >= 80:
            return fb, config.get("benchmark_fallback_name") or fb, h2
    return primary, config.get("benchmark_name") or primary, h

def _beta_diagnostics(stock_returns: pd.Series, market_returns: pd.Series) -> dict:
    df = pd.concat([stock_returns.rename("s"), market_returns.rename("m")], axis=1, join="inner").dropna().tail(104)
    n = len(df)
    if n < 20:
        return {"observations": n, "r_squared": None, "beta_se": None, "beta_t_stat": None}
    x = df["m"].to_numpy(float); y = df["s"].to_numpy(float)
    X = np.column_stack([np.ones(n), x])
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        sse = float(resid @ resid)
        sst = float(((y-y.mean())**2).sum())
        r2 = 1.0 - sse/sst if sst > 0 else None
        sigma2 = sse / max(n-2, 1)
        inv = np.linalg.inv(X.T @ X)
        beta_se = math.sqrt(max(float(sigma2 * inv[1,1]), 0.0))
        beta_t = float(coef[1]) / beta_se if beta_se > 0 else None
        return {"observations": n, "r_squared": round(r2,4) if r2 is not None else None, "beta_se": round(beta_se,4), "beta_t_stat": round(beta_t,3) if beta_t is not None else None}
    except Exception:
        return {"observations": n, "r_squared": None, "beta_se": None, "beta_t_stat": None}


def analyze_capm(ticker: str, *, market: str | None = None, force_refresh: bool = False) -> dict:
    ticker = ticker.upper().strip()
    from config.markets import symbol_market
    market = market or symbol_market(ticker)
    if market not in MARKETS:
        # For France listings explicitly supported by .PA.
        market = "France" if ticker.endswith(".PA") else market
    if market not in MARKETS:
        return {"error":"unsupported_market", "ticker":ticker, "market":market}
    cfg = MARKETS[market]

    stock_h = fetch_history(ticker, period="5y")
    bench_symbol, bench_name, bench_h = _benchmark_history(cfg)
    sr = _weekly_returns(_history_series(stock_h))
    mr = _weekly_returns(_history_series(bench_h))
    betas = _rolling_beta(sr, mr)
    beta = float(betas.iloc[-1]) if not betas.empty else None

    rf_raw = get_market_risk_free(market, force_refresh=force_refresh)
    erp = get_country_erp(market, force_refresh=force_refresh)
    rf = dict(rf_raw)
    sovereign_yield = rf_raw.get("rate_pct")
    total_erp = erp.get("total_erp_pct")
    crp = erp.get("country_risk_premium_pct")
    default_spread = erp.get("default_spread_pct")

    # One consistent currency-local framework for all supported markets:
    # default-free local RF = sovereign yield - sovereign default spread;
    # mature ERP = total country ERP - CRP; then add CRP once, separately.
    # For AAA/zero-spread countries this naturally collapses to standard CAPM.
    adjusted_rf = None
    mature_erp = None
    if sovereign_yield is not None and default_spread is not None:
        try:
            adjusted_rf = float(sovereign_yield) - float(default_spread)
            if not math.isfinite(adjusted_rf) or not (-5.0 < adjusted_rf < 40.0):
                adjusted_rf = None
        except Exception:
            adjusted_rf = None
    elif sovereign_yield is not None and market in {"Australia", "Japan", "France", "London"}:
        # A source row may omit a zero/near-zero spread. Keep the observable yield
        # but disclose the simplification rather than fabricating an adjustment.
        adjusted_rf = float(sovereign_yield)

    if total_erp is not None and crp is not None:
        mature_erp = float(total_erp) - float(crp)
    required = None
    if beta is not None and adjusted_rf is not None and mature_erp is not None and crp is not None:
        required = adjusted_rf + beta * mature_erp + float(crp)

    rf = {
        **rf_raw,
        "sovereign_yield_pct": sovereign_yield,
        "default_spread_deduction_pct": default_spread,
        "rate_pct": adjusted_rf,
        "instrument": f"{cfg['currency']} default-free proxy = local sovereign yield − country default spread" if default_spread is not None else rf_raw.get("instrument"),
    }
    method = "country_risk_consistent_local_capm"
    formula = "Ke = (Sovereign Yield − Default Spread) + β × Mature ERP + CRP"
    diagnostics = _beta_diagnostics(sr, mr)
    # Historical rolling-beta snapshots are point-in-time and do not reuse the
    # current beta for past years. We intentionally do not fabricate historical
    # ERP/CRP, so the chart is labelled Beta History rather than fake CAPM history.
    beta_history = []
    if not betas.empty:
        by_year = betas.groupby(betas.index.year).tail(1)
        for dt, val in by_year.tail(6).items():
            beta_history.append({"date":dt.date().isoformat(), "year":int(dt.year), "beta":round(float(val),4)})

    return {
        "ticker": ticker,
        "market": market,
        "country": cfg["country"],
        "currency": cfg["currency"],
        "benchmark": bench_symbol,
        "benchmark_name": bench_name,
        "benchmark_fallback_used": bool(bench_symbol != cfg["benchmark"]),
        "method": method,
        "formula": formula,
        "beta": round(beta, 4) if beta is not None else None,
        "beta_observations": int(len(pd.concat([sr,mr],axis=1,join="inner").dropna())),
        "beta_diagnostics": diagnostics,
        "risk_free": rf,
        "erp": {
            **erp,
            "base_erp_pct": round(mature_erp,4) if mature_erp is not None else None,
            "mature_erp_pct": round(mature_erp,4) if mature_erp is not None else None,
        },
        "required_return_pct": round(required,4) if required is not None else None,
        "research_expected_return_pct": None,
        "expected_alpha_pct": None,
        "beta_history": beta_history,
        "history_note": "Исторический график показывает rolling beta по прошлым данным. Исторический Required Return не рисуется без point-in-time ERP/CRP, чтобы не подменять прошлые значения сегодняшними assumptions.",
        "refresh_policy": {
            "risk_free": "automatic; provider cache up to 1 hour",
            "erp_crp": "automatic; source checked daily",
            "prices_beta": "automatic; market-price cache up to 1 hour",
            "manual_year_update_required": False,
        },
        "methodology": {
            "beta_frequency": "weekly returns",
            "beta_window": "rolling 104 weeks; minimum 52 aligned observations",
            "all_markets": "local-currency, country-risk-consistent CAPM: sovereign yield is stripped of source default spread when available; mature ERP is separated from CRP; CRP is added once",
            "benchmark": "beta is estimated against the actual benchmark symbol returned by the data provider; fallback name is displayed when fallback is used",
            "no_fabrication": "required return is N/A when a required live/source input is unavailable",
        },
    }
