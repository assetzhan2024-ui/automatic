"""
fetcher/kase_fetcher.py
=======================
Получение данных с kase.kz для тикеров которые Yahoo Finance не покрывает.

Публичный API:
    fetch_kase_quote(ticker_base)           → dict | None
    enrich_with_kase(record)                → dict
    fetch_kase_chart(ticker_base)           → dict   (годовые котировки)
    fetch_kase_fundamentals(ticker_base)    → dict   (финансовая отчётность)
"""

import csv
import io
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta

# Используем curl_cffi если доступен — обходит Cloudflare/anti-bot как yfinance
try:
    from fetcher.session import SESSION as _CURL_SESSION
except ImportError:
    _CURL_SESSION = None

_TIMEOUT = 20
_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer":         "https://kase.kz/",
    "Connection":      "keep-alive",
}


# ─────────────────────────────────────────────────────────────────────────────
#  HTTP-утилиты
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_url(url: str, accept: str = "text/html") -> bytes | None:
    """
    GET url. Пробует сначала curl_cffi (browser-impersonation), потом urllib.
    Возвращает bytes или None при любой ошибке.
    """
    headers = {**_BASE_HEADERS, "Accept": accept}

    # Попытка 1: curl_cffi (обходит Cloudflare)
    if _CURL_SESSION is not None:
        try:
            r = _CURL_SESSION.get(url, headers=headers, timeout=_TIMEOUT)
            if r.status_code == 200:
                return r.content
        except Exception:
            pass

    # Попытка 2: stdlib urllib
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read()
    except Exception:
        return None


def _fetch_json(url: str) -> dict | list | None:
    raw = _fetch_url(url, accept="application/json, text/javascript, */*")
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Парсинг текущей цены
# ─────────────────────────────────────────────────────────────────────────────

def _parse_kz_number(raw) -> float | None:
    """'7 900,00' → 7900.0"""
    try:
        cleaned = str(raw).strip().replace("\n", "").replace(" ", "").replace(",", ".")
        val = float(cleaned)
        return val if 0.01 < val < 1_000_000_000 else None
    except (ValueError, AttributeError):
        return None


def _extract_price(site_ticker: str, html: str) -> float | None:
    # Источник 1: JSON-блок с code+price
    m = re.compile(
        r'"code"\s*:\s*"' + re.escape(site_ticker.upper()) +
        r'"[^}]{0,300}"price"\s*:\s*([\d.]+)', re.DOTALL
    ).search(html)
    if m:
        val = _parse_kz_number(m.group(1))
        if val: return val

    # Источник 1b: первый share-объект
    m = re.compile(r'"sec_type"\s*:\s*"share"[^}]{0,200}"price"\s*:\s*([\d.]+)').search(html)
    if m:
        val = _parse_kz_number(m.group(1))
        if val: return val

    # Источник 2: last-deal div
    m = re.compile(r'class="last-deal"[^>]*>.*?>\s*([\d][\d\s,]{0,12}[\d])\s*<', re.DOTALL).search(html)
    if m:
        val = _parse_kz_number(m.group(1))
        if val: return val

    return None


def fetch_kase_quote(ticker_base: str) -> dict | None:
    """Получить текущую котировку с kase.kz."""
    from config.kase import kase_site_ticker
    site_ticker = kase_site_ticker(ticker_base)

    for lang in ("ru", "kk"):
        url = f"https://kase.kz/{lang}/shares/show/{site_ticker}/"
        raw = _fetch_url(url)
        if not raw:
            continue
        html = raw.decode("utf-8", errors="ignore")
        price = _extract_price(site_ticker, html)
        if price is not None:
            return {"price": price, "currency": "KZT", "source": "kase.kz", "source_url": url}

    return None


def enrich_with_kase(record: dict) -> dict:
    """Дополнить запись тикера ценой с kase.kz если Yahoo вернул пустой ответ."""
    if record.get("price") is not None:
        return record
    if not record.get("is_kase"):
        return record

    quote = fetch_kase_quote(record["ticker"])
    if quote and quote.get("price"):
        record["price"]       = quote["price"]
        record["currency"]    = quote.get("currency", "KZT")
        record["source_date"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        if record.get("error"):
            record["error"] = None
    return record


# ─────────────────────────────────────────────────────────────────────────────
#  Исторические котировки (chart)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_kase_csv(raw_bytes: bytes) -> list[dict] | None:
    """
    Парсим CSV экспорт kase.kz.
    Формат: Дата;Открытие;Максимум;Минимум;Закрытие;Объём
    или: Date;Open;High;Low;Close;Volume
    """
    try:
        text = raw_bytes.decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        rows = []
        for row in reader:
            # Находим колонку с датой и ценой закрытия
            date_col  = next((k for k in row if any(d in k.lower() for d in ("date","дат","data"))), None)
            close_col = next((k for k in row if any(c in k.lower() for c in ("close","закрыт","клоз","last","посл"))), None)
            if not date_col or not close_col:
                continue
            raw_date  = row[date_col].strip()
            raw_close = row[close_col].strip()
            if not raw_date or not raw_close:
                continue
            # Нормализуем дату DD.MM.YYYY или YYYY-MM-DD
            try:
                if "." in raw_date:
                    d = datetime.strptime(raw_date, "%d.%m.%Y")
                else:
                    d = datetime.strptime(raw_date[:10], "%Y-%m-%d")
                date_str = d.strftime("%Y-%m-%d")
            except ValueError:
                continue
            close = _parse_kz_number(raw_close)
            if close is None:
                continue
            rows.append({"date": date_str, "close": close})
        return rows if rows else None
    except Exception:
        return None


def _extract_chart_from_html(html: str) -> list[dict] | None:
    """
    Попытка извлечь исторические данные из JS-переменных в HTML kase.kz.
    Ищем массивы вида: [[timestamp, price], ...]  или {data:[...]}
    """
    # Вариант 1: highcharts series data
    m = re.search(r'series\s*:\s*\[.*?data\s*:\s*(\[\[[\d,\s.]+\]\])', html, re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group(1))
            rows = []
            for item in arr:
                if len(item) >= 2:
                    ts    = item[0] / 1000  # ms → s
                    close = float(item[1])
                    date  = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                    rows.append({"date": date, "close": close})
            if rows:
                return sorted(rows, key=lambda x: x["date"])
        except Exception:
            pass

    # Вариант 2: массив объектов {date:"...", close:...}
    m = re.search(r'\[\s*\{[^]]{0,50}"date"\s*:', html)
    if m:
        try:
            start = m.start()
            end   = html.find(']', start) + 1
            arr   = json.loads(html[start:end])
            rows  = []
            for item in arr:
                d = item.get("date") or item.get("d")
                c = item.get("close") or item.get("c") or item.get("price")
                if d and c:
                    rows.append({"date": str(d)[:10], "close": float(c)})
            if rows:
                return sorted(rows, key=lambda x: x["date"])
        except Exception:
            pass

    return None


def fetch_kase_chart(ticker_base: str) -> dict:
    """
    Получить годовые котировки для KASE тикера с kase.kz.

    Стратегия:
      1. CSV-экспорт /export/?period=year&format=csv
      2. Страница /history/ с парсингом JS-данных
      3. Главная страница тикера с парсингом JS-данных

    Возвращает dict совместимый с fetch_chart():
      {ticker, dates, closes, min_close, max_close}
      или {error: "no_data", ...}
    """
    from config.kase import kase_site_ticker
    site_ticker = kase_site_ticker(ticker_base)

    date_from = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
    date_to   = datetime.utcnow().strftime("%Y-%m-%d")

    rows = None

    # ── Попытка 1: CSV-экспорт ──────────────────────────────────────────────
    for lang in ("ru", "kk"):
        csv_url = (
            f"https://kase.kz/{lang}/shares/show/{site_ticker}/export/"
            f"?period=custom&date_from={date_from}&date_to={date_to}&format=csv"
        )
        raw = _fetch_url(csv_url, accept="text/csv,application/octet-stream,*/*")
        if raw and len(raw) > 50:
            parsed = _parse_kase_csv(raw)
            if parsed:
                rows = parsed
                break

    # ── Попытка 2: /history/ страница с JS-данными ──────────────────────────
    if not rows:
        for lang in ("ru", "kk"):
            url = f"https://kase.kz/{lang}/shares/show/{site_ticker}/history/"
            raw = _fetch_url(url)
            if raw:
                html = raw.decode("utf-8", errors="ignore")
                rows = _extract_chart_from_html(html)
                if rows:
                    break

    # ── Попытка 3: Главная страница тикера ──────────────────────────────────
    if not rows:
        for lang in ("ru", "kk"):
            url = f"https://kase.kz/{lang}/shares/show/{site_ticker}/"
            raw = _fetch_url(url)
            if raw:
                html = raw.decode("utf-8", errors="ignore")
                rows = _extract_chart_from_html(html)
                if rows:
                    break

    if not rows:
        return {"error": "no_data", "ticker": ticker_base, "dates": [], "closes": []}

    # Фильтруем последние 365 дней
    cutoff = (datetime.utcnow() - timedelta(days=370)).strftime("%Y-%m-%d")
    rows   = [r for r in rows if r["date"] >= cutoff]
    rows   = sorted(rows, key=lambda x: x["date"])

    dates  = [r["date"]  for r in rows]
    closes = [r["close"] for r in rows]

    return {
        "ticker":    ticker_base,
        "dates":     dates,
        "closes":    closes,
        "min_close": min(closes),
        "max_close": max(closes),
        "source":    "kase.kz",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Фундаментальные данные
# ─────────────────────────────────────────────────────────────────────────────

def _parse_fin_table(html: str, section_hint: str) -> dict:
    """
    Ищем финансовые таблицы в HTML kase.kz.
    kase.kz публикует отчётность в виде HTML-таблиц или JSON.
    Возвращает { "YYYY": { metric: value } }
    """
    out = {}

    # Вариант 1: JSON-объект с годовыми данными
    patterns = [
        r'"financials"\s*:\s*(\{[^;]{100,}?\})\s*[;,\n]',
        r'var\s+financialData\s*=\s*(\{[^;]+\})',
        r'reportData\s*=\s*(\{[^;]+\})',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                # Разворачиваем если есть годовые ключи
                for key, val in data.items():
                    if re.match(r'20\d\d', str(key)) and isinstance(val, dict):
                        out[str(key)] = {k: v for k, v in val.items() if isinstance(v, (int, float))}
                if out:
                    return out
            except Exception:
                pass

    # Вариант 2: HTML-таблица с годами в заголовках
    # <th>2023</th><th>2022</th>... и строки с метриками
    years = re.findall(r'<th[^>]*>\s*(20\d\d)\s*</th>', html)
    if years:
        rows = re.findall(
            r'<tr[^>]*>\s*<td[^>]*>([^<]{3,60})</td>((?:\s*<td[^>]*>[^<]*</td>)+)',
            html
        )
        for metric, cells_html in rows:
            vals = re.findall(r'<td[^>]*>\s*([\d\s,.()\-]+)\s*</td>', cells_html)
            for i, year in enumerate(years[:len(vals)]):
                v = _parse_kz_number(vals[i])
                if v is not None:
                    out.setdefault(year, {})[metric.strip()] = v

    return out


def fetch_kase_fundamentals(ticker_base: str) -> dict:
    """
    Получить финансовую отчётность KASE тикера с kase.kz.

    Стратегия:
      1. Страница /financials/ или /reporting/
      2. Главная страница тикера

    Возвращает dict совместимый с fetch_fundamentals():
      {ticker, income, balance, cashflow}
    """
    from config.kase import kase_site_ticker
    site_ticker = kase_site_ticker(ticker_base)

    income   = {}
    balance  = {}
    cashflow = {}

    url_variants = []
    for lang in ("ru", "kk"):
        url_variants += [
            f"https://kase.kz/{lang}/shares/show/{site_ticker}/financials/",
            f"https://kase.kz/{lang}/shares/show/{site_ticker}/reporting/",
            f"https://kase.kz/{lang}/shares/show/{site_ticker}/",
        ]

    for url in url_variants:
        raw = _fetch_url(url)
        if not raw:
            continue
        html = raw.decode("utf-8", errors="ignore")

        # Ищем JSON с финансовыми данными в любом формате
        # Паттерн 1: объект с ключами income_statement / balance_sheet / cash_flow
        for key_hint, target in [
            (["income", "profit", "revenue", "доход", "выруч"], "income"),
            (["balance", "assets", "актив", "баланс"],          "balance"),
            (["cash_flow", "cashflow", "денежн"],               "cashflow"),
        ]:
            data = _parse_fin_table(html, key_hint[0])
            if data:
                if target == "income":   income   = data
                elif target == "balance": balance  = data
                elif target == "cashflow": cashflow = data

        if income or balance or cashflow:
            break

    if not income and not balance and not cashflow:
        return {"error": "no_data", "ticker": ticker_base, "income": {}, "balance": {}, "cashflow": {}}

    return {
        "ticker":   ticker_base,
        "income":   income,
        "balance":  balance,
        "cashflow": cashflow,
        "source":   "kase.kz",
    }
