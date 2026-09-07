"""Automatic similar-company discovery for issuer research.

This is intentionally separate from the existing manual compare feature.
Peer selection follows the user's five rules:
1) same/close industry, 2) similar business model, 3) similar market cap,
4) similar geography when relevant, 5) enough financial data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import re
from urllib.request import Request, urlopen
from typing import Any

from cache.ticker_cache import get_status
from config.markets import market_tickers
from fetcher.ticker import fetch_ticker

_YAHOO_REC_URL = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{ticker}"


def _tokens(text: str) -> set[str]:
    stop = {"the","and","for","with","from","that","this","its","into","company","companies","services","business","provides","through","including","inc","plc","corp","corporation","limited"}
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in stop}


def _jaccard(a: str, b: str) -> float:
    aa, bb = _tokens(a), _tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def _enough_data(rec: dict) -> bool:
    keys = ("price", "market_cap", "pe_ratio", "ev_ebitda", "roe_pct", "fcf", "net_income", "total_debt")
    present = sum(rec.get(k) is not None for k in keys)
    return rec.get("price") is not None and rec.get("market_cap") is not None and present >= 5


def _recommended_symbols(ticker: str) -> list[str]:
    try:
        req = Request(_YAHOO_REC_URL.format(ticker=ticker), headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=5) as r:
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
        result = (((payload or {}).get("finance") or {}).get("result") or [])
        if not result:
            return []
        rows = result[0].get("recommendedSymbols") or []
        return [str(x.get("symbol") or "").upper() for x in rows if x.get("symbol")]
    except Exception:
        return []


def _cached_records() -> dict[str, dict]:
    return {str(r.get("ticker") or "").upper(): r for r in (get_status().get("data") or []) if r.get("ticker")}


def _business_summary(ticker: str) -> str:
    # Avoid making business-summary availability a hard dependency. yfinance is
    # imported lazily and only for the small recommended candidate set.
    try:
        import yfinance as yf
        from fetcher.session import SESSION
        obj = yf.Ticker(ticker, session=SESSION) if SESSION else yf.Ticker(ticker)
        info = obj.info or {}
        return str(info.get("longBusinessSummary") or "")
    except Exception:
        return ""


def _market_cap_score(target_cap: float | None, peer_cap: float | None) -> tuple[float, float | None]:
    try:
        a, b = float(target_cap), float(peer_cap)
        if a <= 0 or b <= 0:
            return 0.0, None
        ratio = b / a
        # Full points at parity, gradually falls across a 0.25x–4x accepted range.
        distance = abs(math.log(ratio)) / math.log(4.0)
        return max(0.0, 20.0 * (1.0 - distance)), ratio
    except Exception:
        return 0.0, None


def _score_peer(target: dict, peer: dict, target_summary: str = "", peer_summary: str = "") -> tuple[float, dict]:
    same_industry = bool(target.get("industry") and peer.get("industry") and target.get("industry") == peer.get("industry"))
    same_sector = bool(target.get("sector") and peer.get("sector") and target.get("sector") == peer.get("sector"))
    industry_score = 35.0 if same_industry else 16.0 if same_sector else 0.0
    summary_similarity = _jaccard(target_summary, peer_summary)
    business_score = min(20.0, summary_similarity * 45.0)
    if same_industry and business_score < 8.0:
        business_score = 8.0  # industry is a transparent business-model proxy when summaries are unavailable
    cap_score, cap_ratio = _market_cap_score(target.get("market_cap"), peer.get("market_cap"))
    same_market = target.get("market") == peer.get("market")
    same_region = target.get("region") == peer.get("region")
    geo_score = 15.0 if same_market else 8.0 if same_region else 0.0
    data_score = 10.0 if _enough_data(peer) else 0.0
    total = industry_score + business_score + cap_score + geo_score + data_score
    reasons = {
        "same_industry": same_industry,
        "same_sector": same_sector,
        "business_similarity": round(summary_similarity, 3),
        "market_cap_ratio": round(cap_ratio, 3) if cap_ratio is not None else None,
        "same_market": same_market,
        "same_region": same_region,
        "enough_financial_data": _enough_data(peer),
    }
    return round(total, 2), reasons


def find_similar_companies(ticker: str, *, limit: int = 8) -> dict:
    ticker = ticker.upper().strip()
    cached = _cached_records()
    target = cached.get(ticker) or fetch_ticker(ticker)
    if not target or target.get("error"):
        return {"error": "target_unavailable", "ticker": ticker, "peers": []}
    if (target.get("asset_type") or "stock") != "stock":
        return {"error": "stocks_only", "ticker": ticker, "peers": []}

    # Start with Yahoo's recommendation graph, then supplement with records the
    # user has already loaded. This avoids scanning/fetching hundreds of names.
    candidates = []
    seen = {ticker}
    for s in _recommended_symbols(ticker):
        if s not in seen:
            candidates.append(s); seen.add(s)
    for s, rec in cached.items():
        if s in seen or (rec.get("asset_type") or "stock") != "stock":
            continue
        if rec.get("market") == target.get("market") or rec.get("region") == target.get("region"):
            candidates.append(s); seen.add(s)
    # Curated-market fallback. The universe is intentionally grouped by industry
    # in config/tickers.py, so use neighbours around the selected symbol rather
    # than blindly taking the first names in the market (which would bias US
    # fallback toward mega-cap technology).
    if len(candidates) < 12:
        universe = [s.upper() for s in market_tickers(target.get("market") or "All", "stock")]
        if ticker in universe:
            pos = universe.index(ticker)
            lo, hi = max(0, pos - 36), min(len(universe), pos + 37)
            fallback = universe[lo:hi]
        else:
            fallback = universe[:72]
        for s in fallback:
            if s not in seen:
                candidates.append(s); seen.add(s)
            if len(candidates) >= 48:
                break

    candidates = candidates[:40]
    records: dict[str, dict] = {s: cached[s] for s in candidates if s in cached}
    missing = [s for s in candidates if s not in records]
    if missing:
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as pool:
            futs = {pool.submit(fetch_ticker, s): s for s in missing[:24]}
            for fut in as_completed(futs):
                try:
                    rec = fut.result()
                    if rec and not rec.get("error"):
                        records[futs[fut]] = rec
                except Exception:
                    pass

    target_summary = _business_summary(ticker)
    # Summary similarity is a bonus, not a requirement. Fetch only the small
    # set that already passes coarse sector/industry/geography/data filters.
    coarse = []
    for s, rec in records.items():
        if s == ticker or not _enough_data(rec):
            continue
        if target.get("market") == "Kazakhstan" and rec.get("market") != "Kazakhstan":
            continue
        same_ind = bool(target.get("industry") and rec.get("industry") == target.get("industry"))
        same_sec = bool(target.get("sector") and rec.get("sector") == target.get("sector"))
        if not (same_ind or same_sec):
            continue
        _, ratio = _market_cap_score(target.get("market_cap"), rec.get("market_cap"))
        if ratio is not None and not (0.25 <= ratio <= 4.0):
            continue
        coarse.append((s, rec))

    summaries: dict[str, str] = {}
    if coarse and target_summary:
        with ThreadPoolExecutor(max_workers=min(6, len(coarse))) as pool:
            futs = {pool.submit(_business_summary, s): s for s, _ in coarse[:12]}
            for fut in as_completed(futs):
                try: summaries[futs[fut]] = fut.result()
                except Exception: pass

    ranked = []
    for s, rec in coarse:
        score, reasons = _score_peer(target, rec, target_summary, summaries.get(s, ""))
        ranked.append({
            "ticker": s,
            "name": rec.get("name") or s,
            "market": rec.get("market"),
            "region": rec.get("region"),
            "sector": rec.get("sector"),
            "industry": rec.get("industry"),
            "market_cap": rec.get("market_cap"),
            "price": rec.get("price"),
            "currency": rec.get("currency"),
            "pe_ratio": rec.get("pe_ratio"),
            "ps_ratio": rec.get("ps_ratio"),
            "ev_ebitda": rec.get("ev_ebitda"),
            "roe_pct": rec.get("roe_pct"),
            "de_ratio": rec.get("de_ratio"),
            "fcf": rec.get("fcf"),
            "net_income": rec.get("net_income"),
            "score_pct": rec.get("score_pct"),
            "peer_score": score,
            "match": reasons,
        })
    ranked.sort(key=lambda x: x["peer_score"], reverse=True)

    return {
        "ticker": ticker,
        "target": {
            "ticker": ticker,
            "name": target.get("name") or ticker,
            "market": target.get("market"),
            "region": target.get("region"),
            "sector": target.get("sector"),
            "industry": target.get("industry"),
            "market_cap": target.get("market_cap"),
        },
        "peers": ranked[:max(1, min(int(limit), 12))],
        "filters": [
            "same_or_close_industry",
            "similar_business_model",
            "similar_market_cap_range_0.25x_to_4x",
            "similar_geography_when_relevant",
            "enough_financial_data",
        ],
        "note": "Peer discovery is a research aid, not an automatic buy/sell decision. The existing manual Compare feature is unchanged.",
    }
