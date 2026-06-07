"""
fetcher/ticker.py
=================
Получение финансовых данных по одному тикеру через yfinance.

Публичный API:
    fetch_ticker(symbol: str) → dict   — все поля для строки скринера
"""

from datetime import datetime

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip install yfinance pandas")

from fetcher.session import SESSION as _SESSION

from config.kase import KASE_META, kase_candidates
from regions.detector import detect_region
from metrics.benchmarks import rate_regional, score_record, region_medians_for
from fetcher.fx import get_rate, to_usd

# Валюта по умолчанию для региона — когда yfinance не вернул currency
_REGION_DEFAULT_CURRENCY: dict[str, str] = {
    "US": "USD", "Europe": "EUR", "Asia": "USD",
    "Emerging": "USD", "KZ": "KZT", "Other": "USD",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def _safe(v, mult: float = 1, div: float = 1):
    """Безопасно конвертировать значение в float, вернуть None при ошибке или NaN."""
    try:
        f = float(v) * mult / div
        return round(f, 3) if (f == f) else None  # NaN guard
    except Exception:
        return None


def _fetch_info(sym: str) -> dict:
    """Вернуть yfinance .info dict или {} при любой ошибке."""
    try:
        return yf.Ticker(sym, session=_SESSION).info if _SESSION else yf.Ticker(sym).info
    except Exception:
        return {}


def _info_has_data(info: dict) -> bool:
    """Проверить, содержит ли info хотя бы минимальные полезные данные."""
    return bool(
        info.get("longName") or info.get("shortName") or
        info.get("regularMarketPrice") or info.get("currentPrice") or
        info.get("marketCap")
    )


def _parse_source_date(info: dict):
    """Распарсить timestamp последней котировки в читаемую строку UTC."""
    last_ts = info.get("regularMarketTime")
    if last_ts:
        try:
            return datetime.utcfromtimestamp(int(last_ts)).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Основная функция
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ticker(symbol: str) -> dict:
    """
    Получить все финансовые данные по тикеру.

    Для KASE (.KZ) перебирает несколько вариантов символа и использует
    статический fallback из KASE_META если yfinance не вернул данные.

    Returns:
        dict со всеми полями строки скринера, поле "error" = None при успехе.
    """
    try:
        is_kase  = symbol.upper().endswith(".KZ")
        fallback = KASE_META.get(symbol.upper(), {})
        info     = {}
        resolved = symbol

        # Разрешение символа: для KASE пробуем несколько вариантов
        if is_kase:
            for cand in kase_candidates(symbol):
                inf = _fetch_info(cand)
                if _info_has_data(inf):
                    info     = inf
                    resolved = cand
                    break
        else:
            info = _fetch_info(symbol)

        region   = detect_region(symbol, info)
        # Если info пустой — определяем регион по символу без info
        if region == "Other" and not _info_has_data(info):
            region = detect_region(symbol, {})

        # Для US тикеров без данных — скорее всего делистинг или смена символа
        # Угадываем валюту по региону
        name     = info.get("longName") or info.get("shortName") or fallback.get("name") or symbol
        currency = info.get("currency") or ("KZT" if is_kase else _REGION_DEFAULT_CURRENCY.get(region, "USD"))
        sector   = info.get("sector")   or fallback.get("sector",   "")
        industry = info.get("industry") or fallback.get("industry", "")

        # ── Цена ──────────────────────────────────────────────────────────────
        price      = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        price_change = price_change_p = None
        if price and prev_close and float(prev_close) != 0:
            price_change   = round(float(price) - float(prev_close), 4)
            price_change_p = round(price_change / float(prev_close) * 100, 2)

        # ── Финансовые данные ─────────────────────────────────────────────────
        mktcap     = info.get("marketCap")
        net_income = info.get("netIncomeToCommon")
        ebitda     = info.get("ebitda")
        total_debt = info.get("totalDebt")
        cash       = info.get("totalCash")
        equity     = info.get("totalStockholderEquity")
        bvps       = info.get("bookValue")
        fcf        = info.get("freeCashflow")
        w52_lo     = info.get("fiftyTwoWeekLow")
        w52_hi     = info.get("fiftyTwoWeekHigh")

        # ── Мультипликаторы ───────────────────────────────────────────────────
        pe_ratio  = _safe(info.get("trailingPE") or info.get("forwardPE"))
        pb_ratio  = _safe(info.get("priceToBook"))
        ps_ratio  = _safe(info.get("priceToSalesTrailing12Months"))
        ev_ebitda = _safe(info.get("enterpriseToEbitda"))
        ev_revenue = _safe(info.get("enterpriseToRevenue"))
        de_ratio  = _safe(info.get("debtToEquity"), div=100)
        roe_pct   = _safe(info.get("returnOnEquity"), mult=100)
        roa_pct   = _safe(info.get("returnOnAssets"), mult=100)
        eps_trail = _safe(info.get("trailingEps"))
        eps_fwd   = _safe(info.get("forwardEps"))

        net_debt_ebitda = None
        if total_debt is not None and cash is not None and ebitda not in (None, 0):
            net_debt_ebitda = round((float(total_debt) - float(cash)) / float(ebitda), 2)

        # ── Рейтинги и балл ───────────────────────────────────────────────────
        ratings = {
            "pe_ratio":        rate_regional("pe_ratio",        pe_ratio,        region),
            "pb_ratio":        rate_regional("pb_ratio",        pb_ratio,        region),
            "ps_ratio":        rate_regional("ps_ratio",        ps_ratio,        region),
            "ev_ebitda":       rate_regional("ev_ebitda",       ev_ebitda,       region),
            "roe_pct":         rate_regional("roe_pct",         roe_pct,         region),
            "de_ratio":        rate_regional("de_ratio",        de_ratio,        region),
            "net_debt_ebitda": rate_regional("net_debt_ebitda", net_debt_ebitda, region),
        }

        record = {
            "ticker":               symbol,
            "resolved_as":          resolved if resolved != symbol else None,
            "name":                 name,
            "currency":             currency,
            "sector":               sector,
            "industry":             industry,
            "region":               region,
            "is_kase":              is_kase,
            "fetched_at":           datetime.utcnow().isoformat(),
            "source_date":          _parse_source_date(info),
            "price":                price,
            "price_change":         price_change,
            "price_change_p":       price_change_p,
            "market_cap":           mktcap,
            "net_income":           net_income,
            "ebitda":               ebitda,
            "total_debt":           total_debt,
            "cash":                 cash,
            "equity":               equity,
            "book_value_per_share": bvps,
            "pe_ratio":             pe_ratio,
            "de_ratio":             de_ratio,
            "ev_ebitda":            ev_ebitda,
            "ev_revenue":           ev_revenue,
            "net_debt_ebitda":      net_debt_ebitda,
            "roe_pct":              roe_pct,
            "roa_pct":              roa_pct,
            "pb_ratio":             pb_ratio,
            "ps_ratio":             ps_ratio,
            "eps_trailing":         eps_trail,
            "eps_forward":          eps_fwd,
            "ratings":              ratings,
            "score_pct":            score_record(ratings),
            "region_medians":       region_medians_for(region),
            "fcf":                  fcf,
            "week52_low":           w52_lo,
            "week52_high":          w52_hi,
            "error":                None,
        }

        # Если KASE тикер и Yahoo не вернул цену — пробуем kase.kz напрямую
        if is_kase and record.get("price") is None:
            try:
                from fetcher.kase_fetcher import enrich_with_kase
                record = enrich_with_kase(record)
            except Exception as kase_err:
                print(f"  [KASE enrich error] {symbol}: {kase_err}")

        # Google Finance как дополнительный источник — заполняет пустые поля
        if record.get("price") is None or record.get("pe_ratio") is None:
            try:
                from fetcher.google_finance import enrich_with_google
                record = enrich_with_google(record)
            except Exception as gf_err:
                print(f"  [Google Finance error] {symbol}: {gf_err}")

        # ── Конвертация в USD ─────────────────────────────────────────────────
        # Для USD тикеров fx_rate=1.0, для остальных запрашиваем курс.
        # Мультипликаторы (P/E, P/B и т.д.) безразмерны — не конвертируем.
        # Денежные поля и цена дублируются как *_usd для единообразного сравнения.
        fx = get_rate(record["currency"])
        record["fx_rate_to_usd"] = fx  # None если курс недоступен

        _monetary = [
            "price", "price_change",
            "market_cap", "net_income", "ebitda", "fcf",
            "equity", "total_debt", "cash",
            "book_value_per_share",
            "week52_low", "week52_high",
            "eps_trailing",
        ]
        for field in _monetary:
            val = record.get(field)
            record[f"{field}_usd"] = (
                round(val * fx, 6) if (val is not None and fx is not None) else None
            )

        return record

    except Exception as exc:
        return {
            "ticker":        symbol,
            "name":          symbol,
            "currency":      "",
            "sector":        "",
            "industry":      "",
            "region":        "Other",
            "is_kase":       symbol.upper().endswith(".KZ"),
            "fetched_at":    datetime.utcnow().isoformat(),
            "source_date":   None,
            "resolved_as":   None,
            "price":         None,
            "price_change":  None,
            "price_change_p":None,
            "score_pct":     0,
            "ratings":       {},
            "region_medians":{},
            "error":         str(exc),
        }
