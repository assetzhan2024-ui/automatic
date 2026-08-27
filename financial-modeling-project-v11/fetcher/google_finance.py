"""
fetcher/google_finance.py
=========================
Google Finance scraper — дополнительный источник данных.

Google Finance не имеет официального API, поэтому парсим HTML
страниц вида: https://www.google.com/finance/quote/AAPL:NASDAQ

Публичный API:
    fetch_google_finance(symbol: str) -> dict | None
        Возвращает частичный record для обогащения основного,
        или None при любой ошибке.
    enrich_with_google(record: dict) -> dict
        Дополняет record полями из Google Finance если они отсутствуют.

Поля которые может вернуть Google Finance:
    price, price_change, price_change_p, market_cap,
    pe_ratio, eps_trailing, week52_low, week52_high,
    revenue (P/S базис), name
"""

import json
import re
from datetime import datetime

try:
    from fetcher.session import SESSION as _SESSION
except ImportError:
    _SESSION = None

_TIMEOUT = 15
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.google.com/finance/",
}

# Маппинг суффиксов тикеров → биржи для Google Finance URL
# Google Finance использует формат TICKER:EXCHANGE
_EXCHANGE_MAP = {
    ".KZ":  "KASE",
    ".KZ":  "KASE",
    ".T":   "TYO",
    ".L":   "LON",
    ".HK":  "HKG",
    ".SS":  "SHA",
    ".SZ":  "SHE",
    ".KS":  "KRX",
    ".NS":  "NSE",
    ".BO":  "BOM",
    ".SA":  "BVMF",
    ".JO":  "JSE",
    ".IS":  "IST",
    ".ME":  "MCX",
    ".DE":  "FRA",
    ".PA":  "EPA",
    ".AX":  "ASX",
    ".TO":  "TSE",
    ".SI":  "SGX",
}


def _symbol_to_google_url(symbol: str) -> str:
    """Превратить тикер в URL Google Finance."""
    sym = symbol.upper()
    for suffix, exchange in _EXCHANGE_MAP.items():
        if sym.endswith(suffix.upper()):
            base = sym[:-len(suffix)]
            return f"https://www.google.com/finance/quote/{base}:{exchange}"
    # US тикеры — пробуем NASDAQ, потом NYSE
    return f"https://www.google.com/finance/quote/{sym}:NASDAQ"


def _fetch_html(url: str) -> str | None:
    # Попытка 1: curl_cffi (browser impersonation)
    if _SESSION is not None:
        try:
            r = _SESSION.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
    # Попытка 2: urllib
    import urllib.request
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        import urllib.error
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _parse_number(s: str) -> float | None:
    """Парсим число из Google Finance: '1.23T', '456.78B', '1,234.56'"""
    if not s:
        return None
    s = s.strip().replace(",", "").replace("\xa0", "")
    mult = 1.0
    if s.endswith("T"):   mult = 1e12;  s = s[:-1]
    elif s.endswith("B"): mult = 1e9;   s = s[:-1]
    elif s.endswith("M"): mult = 1e6;   s = s[:-1]
    elif s.endswith("K"): mult = 1e3;   s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _extract_json_data(html: str) -> dict:
    """
    Google Finance встраивает данные в JSON внутри <script>.
    Ищем основные паттерны.
    """
    result = {}

    # Паттерн 1: window.google.finance.data = {...}
    m = re.search(r'window\.google\.finance\.data\s*=\s*(\{.+?\});', html, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            result.update(d)
        except Exception:
            pass

    # Паттерн 2: AF_initDataCallback с финансовыми данными
    for m in re.finditer(r'AF_initDataCallback\(\{[^}]*data:(.*?)\}\)', html, re.DOTALL):
        try:
            d = json.loads(m.group(1))
            if isinstance(d, dict) and any(k in d for k in ("price", "pe", "marketCap")):
                result.update(d)
        except Exception:
            pass

    return result


def _parse_from_html(html: str) -> dict:
    """Парсим данные прямо из HTML разметки Google Finance."""
    data = {}

    # Цена — div с классом YMlKec fxKbKc или похожим
    price_patterns = [
        r'class="[^"]*YMlKec[^"]*fxKbKc[^"]*"[^>]*>\s*([\d,. ]+)',
        r'class="[^"]*fxKbKc[^"]*"[^>]*>\s*([\d,. ]+)',
        r'"price"\s*:\s*"([\d.]+)"',
        r'data-last-price="([\d.]+)"',
    ]
    for pat in price_patterns:
        m = re.search(pat, html)
        if m:
            v = _parse_number(m.group(1))
            if v and v > 0:
                data["price"] = v
                break

    # Изменение цены
    change_m = re.search(r'([-+][\d.]+)\s*\(([-+][\d.]+)%\)', html)
    if change_m:
        try:
            data["price_change"]   = float(change_m.group(1))
            data["price_change_p"] = float(change_m.group(2))
        except Exception:
            pass

    # Название компании
    name_m = re.search(r'<title>\s*([^(|<]+?)(?:\s*[-|·])', html)
    if name_m:
        data["name"] = name_m.group(1).strip()

    # Key stats — парсим таблицу статистики
    # Google Finance показывает метрики в парах label/value
    stat_patterns = {
        "market_cap":  [r"Market cap[^<]*</div>\s*<div[^>]*>\s*([\d.,TBMK]+)"],
        "pe_ratio":    [r"P/E ratio[^<]*</div>\s*<div[^>]*>\s*([\d.,]+)"],
        "eps_trailing":[r"EPS[^<]*</div>\s*<div[^>]*>\s*([-\d.,]+)"],
        "week52_low":  [r"52-week low[^<]*</div>\s*<div[^>]*>\s*([\d.,]+)"],
        "week52_high": [r"52-week high[^<]*</div>\s*<div[^>]*>\s*([\d.,]+)"],
        "revenue":     [r"Revenue[^<]*</div>\s*<div[^>]*>\s*([\d.,TBMK]+)"],
        "net_income":  [r"Net income[^<]*</div>\s*<div[^>]*>\s*([\d.,TBMK]+)"],
    }
    for field, pats in stat_patterns.items():
        for pat in pats:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                v = _parse_number(m.group(1))
                if v is not None:
                    data[field] = v
                    break

    # Валюта
    cur_m = re.search(r'\b(USD|EUR|GBP|KZT|JPY|HKD|CNY|KRW|INR|BRL|ZAR)\b', html[:2000])
    if cur_m:
        data["currency"] = cur_m.group(1)

    return data


def fetch_google_finance(symbol: str) -> dict | None:
    """
    Получить данные по тикеру с Google Finance.
    Возвращает частичный dict или None если ничего не удалось.
    """
    url = _symbol_to_google_url(symbol)
    html = _fetch_html(url)

    # Если NASDAQ не сработал для US — пробуем NYSE
    if (html is None or len(html) < 1000) and ":" not in symbol:
        url2 = f"https://www.google.com/finance/quote/{symbol.upper()}:NYSE"
        html2 = _fetch_html(url2)
        if html2 and len(html2) > len(html or ""):
            html = html2
            url  = url2

    if not html or len(html) < 500:
        return None

    data = _parse_from_html(html)
    json_data = _extract_json_data(html)
    # Приоритет — HTML парсинг, JSON как дополнение
    for k, v in json_data.items():
        if k not in data and v is not None:
            data[k] = v

    if not data.get("price"):
        return None

    data["source_google"] = url
    data["fetched_google_at"] = datetime.utcnow().isoformat()
    return data


def enrich_with_google(record: dict) -> dict:
    """
    Дополнить record данными из Google Finance.
    Перезаписывает только None-поля (Yahoo приоритетнее).
    """
    gdata = fetch_google_finance(record.get("ticker", ""))
    if not gdata:
        return record

    # Поля которые берём из Google если нет от Yahoo
    _fillable = [
        "price", "price_change", "price_change_p",
        "market_cap", "pe_ratio", "eps_trailing", "eps_forward",
        "week52_low", "week52_high", "net_income", "name",
    ]
    for field in _fillable:
        if record.get(field) is None and gdata.get(field) is not None:
            record[field] = gdata[field]

    record["source_google"] = gdata.get("source_google")
    return record
