"""
Fetch stock/ETF data for one exchange-traded symbol through yfinance.

Stocks and ETFs intentionally have different analytical fields. Corporate
ratios (P/E, ROE, EBITDA, etc.) are scored only for operating companies.
"""

from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance pandas")

from fetcher.session import SESSION as _SESSION
from config.kase import KASE_META, kase_candidates
from regions.detector import detect_region, detect_market
from metrics.benchmarks import rate_regional, score_record, region_medians_for
from fetcher.fx import get_rate
from config.markets import asset_type_for_ticker

_REGION_DEFAULT_CURRENCY: dict[str, str] = {
    "US": "USD", "Europe": "EUR", "Asia": "USD",
    "Emerging": "USD", "KZ": "KZT", "Other": "USD",
}


def _safe(v, mult: float = 1, div: float = 1):
    try:
        f = float(v) * mult / div
        return round(f, 3) if (f == f) else None
    except Exception:
        return None


def _pct(v):
    """Normalize a ratio-like yfinance field to percentage points."""
    x = _safe(v)
    if x is None:
        return None
    return round(x * 100, 3) if abs(x) <= 1 else x


def _fetch_info(sym: str) -> dict:
    try:
        return yf.Ticker(sym, session=_SESSION).info if _SESSION else yf.Ticker(sym).info
    except Exception:
        return {}


def _info_has_data(info: dict) -> bool:
    return bool(
        info.get("longName") or info.get("shortName") or
        info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None or
        info.get("marketCap") is not None or info.get("totalAssets") is not None
    )


def _parse_source_date(info: dict):
    last_ts = info.get("regularMarketTime")
    if last_ts:
        try:
            return datetime.utcfromtimestamp(int(last_ts)).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
    return None


def _parse_date_ts(v):
    if v is None:
        return None
    try:
        return datetime.utcfromtimestamp(int(v)).strftime("%Y-%m-%d")
    except Exception:
        return str(v)[:10] if v else None


STOCK_DATA_FIELDS = (
    "price", "market_cap", "net_income", "ebitda", "total_debt", "cash", "equity",
    "pe_ratio", "pb_ratio", "ps_ratio", "ev_ebitda", "roe_pct", "roa_pct", "fcf",
    "eps_trailing", "week52_low", "week52_high",
)
ETF_DATA_FIELDS = (
    "price", "total_assets", "nav_price", "yield_pct", "expense_ratio_pct",
    "three_year_return_pct", "five_year_return_pct", "ytd_return_pct",
    "volume", "average_volume", "week52_low", "week52_high",
)


def has_meaningful_data(record: dict) -> bool:
    """False only when the row is effectively all-null for its asset type.

    A partially populated row is retained. This is deliberately permissive:
    the user requested removal only when essentially every useful field is N/A.
    """
    at = record.get("asset_type", "stock")
    fields = ETF_DATA_FIELDS if at == "etf" else STOCK_DATA_FIELDS
    return any(record.get(k) is not None for k in fields)


def fetch_ticker(symbol: str) -> dict:
    try:
        is_kase = symbol.upper().endswith(".KZ")
        fallback = KASE_META.get(symbol.upper(), {})
        info: dict = {}
        resolved = symbol

        if is_kase:
            for cand in kase_candidates(symbol):
                inf = _fetch_info(cand)
                if _info_has_data(inf):
                    info, resolved = inf, cand
                    break
        else:
            info = _fetch_info(symbol)

        region = detect_region(symbol, info)
        market = detect_market(symbol, info)
        declared_type = asset_type_for_ticker(symbol)
        quote_type = str(info.get("quoteType") or "").upper()
        asset_type = "etf" if quote_type in {"ETF", "MUTUALFUND"} else declared_type

        if region == "Other" and not _info_has_data(info):
            region = detect_region(symbol, {})

        name = info.get("longName") or info.get("shortName") or fallback.get("name") or symbol
        currency = info.get("currency") or ("KZT" if is_kase else _REGION_DEFAULT_CURRENCY.get(region, "USD"))
        sector = info.get("sector") or fallback.get("sector", "")
        industry = info.get("industry") or fallback.get("industry", "")

        price = info.get("currentPrice")
        if price is None:
            price = info.get("regularMarketPrice")
        prev_close = info.get("previousClose")
        if prev_close is None:
            prev_close = info.get("regularMarketPreviousClose")
        price_change = price_change_p = None
        if price is not None and prev_close not in (None, 0):
            price_change = round(float(price) - float(prev_close), 4)
            price_change_p = round(price_change / float(prev_close) * 100, 2)

        mktcap = info.get("marketCap")
        net_income = info.get("netIncomeToCommon")
        ebitda = info.get("ebitda")
        total_debt = info.get("totalDebt")
        cash = info.get("totalCash")
        equity = info.get("totalStockholderEquity")
        bvps = info.get("bookValue")
        fcf = info.get("freeCashflow")
        w52_lo = info.get("fiftyTwoWeekLow")
        w52_hi = info.get("fiftyTwoWeekHigh")

        pe_ratio = _safe(info.get("trailingPE") or info.get("forwardPE"))
        pb_ratio = _safe(info.get("priceToBook"))
        ps_ratio = _safe(info.get("priceToSalesTrailing12Months"))
        ev_ebitda = _safe(info.get("enterpriseToEbitda"))
        ev_revenue = _safe(info.get("enterpriseToRevenue"))
        de_ratio = _safe(info.get("debtToEquity"), div=100)
        roe_pct = _pct(info.get("returnOnEquity"))
        roa_pct = _pct(info.get("returnOnAssets"))
        eps_trail = _safe(info.get("trailingEps"))
        eps_fwd = _safe(info.get("forwardEps"))

        net_debt_ebitda = None
        if total_debt is not None and cash is not None and ebitda not in (None, 0):
            net_debt_ebitda = round((float(total_debt) - float(cash)) / float(ebitda), 2)

        # ETF-specific fields. Many company fundamentals are not applicable to funds.
        total_assets = info.get("totalAssets")
        nav_price = info.get("navPrice")
        yield_pct = _pct(info.get("yield") if info.get("yield") is not None else info.get("trailingAnnualDividendYield"))
        expense_ratio_pct = _pct(
            info.get("netExpenseRatio") if info.get("netExpenseRatio") is not None
            else info.get("annualReportExpenseRatio")
        )
        three_year_return_pct = _pct(info.get("threeYearAverageReturn"))
        five_year_return_pct = _pct(info.get("fiveYearAverageReturn"))
        ytd_return_pct = _pct(info.get("ytdReturn"))
        beta_3y = _safe(info.get("beta3Year") if info.get("beta3Year") is not None else info.get("beta"))
        volume = info.get("volume") or info.get("regularMarketVolume")
        average_volume = info.get("averageVolume") or info.get("averageDailyVolume10Day")
        fund_family = info.get("fundFamily") or ""
        fund_category = info.get("category") or info.get("legalType") or ""
        fund_inception = _parse_date_ts(info.get("fundInceptionDate"))

        if asset_type == "stock":
            ratings = {
                "pe_ratio": rate_regional("pe_ratio", pe_ratio, region),
                "pb_ratio": rate_regional("pb_ratio", pb_ratio, region),
                "ps_ratio": rate_regional("ps_ratio", ps_ratio, region),
                "ev_ebitda": rate_regional("ev_ebitda", ev_ebitda, region),
                "roe_pct": rate_regional("roe_pct", roe_pct, region),
                "de_ratio": rate_regional("de_ratio", de_ratio, region),
                "net_debt_ebitda": rate_regional("net_debt_ebitda", net_debt_ebitda, region),
            }
            score_pct = score_record(ratings)
        else:
            ratings = {}
            score_pct = None

        record = {
            "ticker": symbol,
            "resolved_as": resolved if resolved != symbol else None,
            "name": name,
            "currency": currency,
            "sector": sector,
            "industry": industry,
            "region": region,
            "market": market,
            "asset_type": asset_type,
            "quote_type": quote_type or None,
            "is_kase": is_kase,
            "fetched_at": datetime.utcnow().isoformat(),
            "source_date": _parse_source_date(info),
            "price": price,
            "price_change": price_change,
            "price_change_p": price_change_p,
            "market_cap": mktcap,
            "net_income": net_income,
            "ebitda": ebitda,
            "total_debt": total_debt,
            "cash": cash,
            "equity": equity,
            "book_value_per_share": bvps,
            "pe_ratio": pe_ratio,
            "de_ratio": de_ratio,
            "ev_ebitda": ev_ebitda,
            "ev_revenue": ev_revenue,
            "net_debt_ebitda": net_debt_ebitda,
            "roe_pct": roe_pct,
            "roa_pct": roa_pct,
            "pb_ratio": pb_ratio,
            "ps_ratio": ps_ratio,
            "eps_trailing": eps_trail,
            "eps_forward": eps_fwd,
            "ratings": ratings,
            "score_pct": score_pct,
            "region_medians": region_medians_for(region) if asset_type == "stock" else {},
            "fcf": fcf,
            "week52_low": w52_lo,
            "week52_high": w52_hi,
            # ETF metrics
            "total_assets": total_assets,
            "nav_price": nav_price,
            "yield_pct": yield_pct,
            "expense_ratio_pct": expense_ratio_pct,
            "three_year_return_pct": three_year_return_pct,
            "five_year_return_pct": five_year_return_pct,
            "ytd_return_pct": ytd_return_pct,
            "beta_3y": beta_3y,
            "volume": volume,
            "average_volume": average_volume,
            "fund_family": fund_family,
            "fund_category": fund_category,
            "fund_inception": fund_inception,
            "error": None,
        }

        if is_kase and record.get("price") is None:
            try:
                from fetcher.kase_fetcher import enrich_with_kase
                record = enrich_with_kase(record)
            except Exception as kase_err:
                print(f"  [KASE enrich error] {symbol}: {kase_err}")

        # Google Finance enrichment is useful for companies; avoid asking it for
        # ETF corporate ratios that are not conceptually applicable.
        if asset_type == "stock" and (record.get("price") is None or record.get("pe_ratio") is None):
            try:
                from fetcher.google_finance import enrich_with_google
                record = enrich_with_google(record)
            except Exception as gf_err:
                print(f"  [Google Finance error] {symbol}: {gf_err}")

        fx = get_rate(record["currency"])
        record["fx_rate_to_usd"] = fx
        monetary = [
            "price", "price_change", "market_cap", "net_income", "ebitda", "fcf",
            "equity", "total_debt", "cash", "book_value_per_share", "week52_low",
            "week52_high", "eps_trailing", "total_assets", "nav_price",
        ]
        for field in monetary:
            val = record.get(field)
            record[f"{field}_usd"] = round(val * fx, 6) if (val is not None and fx is not None) else None

        return record

    except Exception as exc:
        return {
            "ticker": symbol,
            "name": symbol,
            "currency": "",
            "sector": "",
            "industry": "",
            "region": "Other",
            "market": detect_market(symbol, {}),
            "asset_type": asset_type_for_ticker(symbol),
            "is_kase": symbol.upper().endswith(".KZ"),
            "fetched_at": datetime.utcnow().isoformat(),
            "source_date": None,
            "resolved_as": None,
            "price": None,
            "price_change": None,
            "price_change_p": None,
            "score_pct": None,
            "ratings": {},
            "region_medians": {},
            "error": str(exc),
        }
