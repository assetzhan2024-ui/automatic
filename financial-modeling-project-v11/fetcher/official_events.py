"""Official corporate-event sources for Event Study.

Primary sources:
- SEC EDGAR submissions for US / SEC-reporting issuers.
- KASE issuer pages for Kazakhstan securities.

The module is intentionally best-effort and never blocks the research workflow:
if an official source is unavailable, Event Study can fall back to the existing
market-data provider. Returned metadata includes the source URL so the user can
inspect the underlying filing/event.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import json
import re
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
KASE_ISSUER_URL = "https://kase.kz/en/listing/issuers/{ticker}/"
CACHE_TTL = 24 * 3600

_sec_ticker_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


def _http_json(url: str, user_agent: str = "PortfolioResearch/1.0 research@example.com") -> Any:
    req = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_text(url: str, user_agent: str = "PortfolioResearch/1.0 research@example.com") -> str:
    req = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,*/*"})
    with urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _load_sec_tickers() -> dict[str, dict[str, Any]]:
    global _sec_ticker_cache
    now = time.time()
    if _sec_ticker_cache and now - _sec_ticker_cache[0] < CACHE_TTL:
        return _sec_ticker_cache[1]
    try:
        raw = _http_json(SEC_TICKERS_URL)
        out: dict[str, dict[str, Any]] = {}
        for item in (raw or {}).values():
            ticker = str(item.get("ticker") or "").upper().strip()
            cik = str(item.get("cik_str") or "").zfill(10)
            if ticker and cik:
                out[ticker] = {"cik": cik, "name": item.get("title")}
        _sec_ticker_cache = (now, out)
        return out
    except Exception:
        return {}


def _sec_filing_url(cik: str, accession: str, primary: str | None) -> str | None:
    accession_compact = accession.replace("-", "")
    if not primary:
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{primary}"


def sec_event_candidates(ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return official SEC report dates for a ticker when SEC coverage exists."""
    ticker = ticker.upper().strip()
    meta = _load_sec_tickers().get(ticker)
    if not meta:
        return []
    try:
        data = _http_json(f"https://data.sec.gov/submissions/CIK{meta['cik']}.json")
        recent = ((data or {}).get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        filing_dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        out: list[dict[str, Any]] = []
        for form, filing_date, accession, primary in zip(forms, filing_dates, accessions, docs):
            if form not in {"10-Q", "10-K", "20-F", "40-F", "6-K"}:
                continue
            if not filing_date:
                continue
            if form == "10-K":
                label = "Годовой отчёт"
                event_type = "annual_report"
            elif form in {"20-F", "40-F"}:
                label = "Годовой отчёт"
                event_type = "annual_report"
            elif form == "10-Q":
                label = "Квартальный отчёт"
                event_type = "quarterly_report"
            else:
                label = "Корпоративный отчёт"
                event_type = "information_report"
            out.append({
                "label": f"{label} · {str(filing_date)[:4]}",
                "date": str(filing_date),
                "is_past": str(filing_date) <= date.today().isoformat(),
                "source_name": "SEC EDGAR",
                "source_url": _sec_filing_url(meta["cik"], str(accession), primary),
                "form": form,
                "event_type": event_type,
            })
            if len(out) >= max(limit * 2, 12):
                break
        # Make quarter labels relative to recency, while annual reports remain annual.
        q_rank = 0
        dedup: dict[str, dict[str, Any]] = {}
        for row in out:
            old = dedup.get(row["date"])
            if old:
                continue
            if row["event_type"] == "quarterly_report":
                q_rank += 1
                row["label"] = f"Квартальный отчёт {q_rank}" if q_rank <= 4 else "Квартальный отчёт"
            dedup[row["date"]] = row
        return list(dedup.values())[:limit]
    except Exception:
        return []


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_data(self, data: str):
        s = " ".join(data.split())
        if not s:
            return
        self.chunks.append(s)
        if self._href is not None:
            self._anchor.append(s)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href = None
            self._anchor = []


def kase_official_issuer_page(ticker: str) -> dict[str, Any]:
    """Return an official KASE issuer page link, even when news scraping is unavailable."""
    base = ticker.upper().replace(".KZ", "")
    return {
        "source_name": "KASE",
        "source_url": KASE_ISSUER_URL.format(ticker=base),
        "available": True,
    }


def kase_event_candidates(ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Best-effort extraction of report/news dates from the official KASE issuer page."""
    base = ticker.upper().replace(".KZ", "")
    url = KASE_ISSUER_URL.format(ticker=base)
    try:
        html = _http_text(url)
        parser = _VisibleTextParser()
        parser.feed(html)
        # KASE issuer pages usually expose report/news links. Match anchors whose
        # title indicates financial reporting, dividends or corporate results and
        # recover a nearby date from the raw HTML.
        out: list[dict[str, Any]] = []
        for href, title in parser.links:
            low = title.lower()
            if not any(k in low for k in (
                "financial statement", "financial report", "annual report",
                "quarter", "financial results", "отчет", "отчёт", "финансов",
                "дивиденд", "dividend", "income"
            )):
                continue
            full = href if href.startswith("http") else "https://kase.kz" + (href if href.startswith("/") else "/" + href)
            # Look for a date close to this title in raw HTML. This is deliberately
            # loose because the page is server-rendered differently across locales.
            pos = html.lower().find(title[:80].lower()) if title else -1
            nearby = html[max(0, pos - 600):pos + 1200] if pos >= 0 else ""
            m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})|([0-3]?\d)\.([01]?\d)\.(20\d{2})", nearby)
            if not m:
                continue
            if m.group(1):
                d = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            else:
                d = f"{int(m.group(6)):04d}-{int(m.group(5)):02d}-{int(m.group(4)):02d}"
            event_type = "quarterly_report" if any(k in low for k in ("quarter", "квартал")) else "annual_report" if any(k in low for k in ("annual", "год", "year")) else "information_report"
            base_label = "Квартальный отчёт" if event_type == "quarterly_report" else "Годовой отчёт" if event_type == "annual_report" else "Информационное событие"
            out.append({
                "label": f"{base_label} · {d[:4]}",
                "date": d,
                "is_past": d <= date.today().isoformat(),
                "source_name": "KASE",
                "source_url": full,
                "event_type": event_type,
            })
            if len(out) >= limit * 2:
                break
        # newest first, deduplicated
        out.sort(key=lambda x: x["date"], reverse=True)
        return list({x["date"]: x for x in out}.values())[:limit]
    except Exception:
        return []


def official_event_candidates(ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Combine official candidates, preferring SEC/KASE over fallback providers."""
    candidates = sec_event_candidates(ticker, limit=limit) if not ticker.upper().endswith(".KZ") else kase_event_candidates(ticker, limit=limit)
    if candidates:
        return candidates
    if ticker.upper().endswith(".KZ"):
        return []
    return []
