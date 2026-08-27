"""
regions/detector.py
===================
Определяет географический регион тикера по:
  1. Суффиксу символа (.L → Europe, .T → Asia …)
  2. Полю exchange из yfinance info
  3. Полю country из yfinance info

Регион используется для выбора регионального бенчмарка при оценке метрик.
"""

from config.kase import KZ_SPECIAL

# ── Суффикс → регион ──────────────────────────────────────────────────────────
SUFFIX_REGION: dict[str, str] = {
    ".L":  "Europe", ".PA": "Europe", ".DE": "Europe", ".AS": "Europe",
    ".MI": "Europe", ".MC": "Europe", ".BR": "Europe", ".VI": "Europe",
    ".SW": "Europe", ".ST": "Europe", ".OL": "Europe", ".CO": "Europe",
    ".HE": "Europe", ".LS": "Europe", ".IR": "Europe", ".AT": "Europe",
    ".T":  "Asia",   ".HK": "Asia",   ".SS": "Asia",   ".SZ": "Asia",
    ".KS": "Asia",   ".KQ": "Asia",   ".SI": "Asia",   ".AX": "Asia",
    ".NZ": "Asia",   ".TW": "Asia",
    ".SA": "Emerging", ".MX": "Emerging", ".ME": "Emerging",
    ".KZ": "KZ",
    ".IS": "Emerging", ".JK": "Emerging",
}

# ── Биржа → регион ────────────────────────────────────────────────────────────
EXCHANGE_REGION: dict[str, str] = {
    "NMS": "US", "NGM": "US", "NCM": "US", "NYQ": "US", "ASE": "US", "PCX": "US",
    "LSE": "Europe", "FRA": "Europe", "PAR": "Europe", "AMS": "Europe",
    "MIL": "Europe", "MCE": "Europe", "VIE": "Europe", "SWX": "Europe",
    "TKS": "Asia", "HKG": "Asia", "SHH": "Asia", "SHZ": "Asia", "KSC": "Asia", "ASX": "Asia",
    "NSI": "Emerging", "BSE": "Emerging", "SAO": "Emerging", "KAZ": "KZ",
}

# ── Страна → регион ───────────────────────────────────────────────────────────
COUNTRY_REGION: dict[str, str] = {
    "united states": "US", "usa": "US",
    "united kingdom": "Europe", "germany": "Europe", "france": "Europe",
    "netherlands": "Europe", "italy": "Europe", "spain": "Europe",
    "sweden": "Europe", "norway": "Europe", "denmark": "Europe",
    "finland": "Europe", "switzerland": "Europe", "belgium": "Europe",
    "austria": "Europe", "ireland": "Europe", "portugal": "Europe",
    "china": "Asia", "japan": "Asia", "south korea": "Asia", "hong kong": "Asia",
    "taiwan": "Asia", "singapore": "Asia", "australia": "Asia", "new zealand": "Asia",
    "india": "Emerging", "brazil": "Emerging", "russia": "Emerging",
    "mexico": "Emerging", "kazakhstan": "KZ", "turkey": "Emerging",
    "indonesia": "Emerging", "thailand": "Emerging", "malaysia": "Emerging",
    "south africa": "Emerging", "egypt": "Emerging", "argentina": "Emerging",
    "philippines": "Emerging", "vietnam": "Emerging", "nigeria": "Emerging",
}


def detect_region(symbol: str, info: dict) -> str:
    """
    Определить регион тикера.

    Порядок приоритета:
      1. KZ_SPECIAL — ADR/GDR казахстанских компаний без суффикса .KZ
      2. Суффикс символа
      3. Код биржи из info["exchange"]
      4. Страна из info["country"]
      5. Fallback → "Other"
    """
    sym = symbol.upper()

    if sym in KZ_SPECIAL:
        return "KZ"

    for suffix, region in SUFFIX_REGION.items():
        if sym.endswith(suffix.upper()):
            return region

    exchange = info.get("exchange", "")
    if exchange in EXCHANGE_REGION:
        return EXCHANGE_REGION[exchange]

    country = (info.get("country") or "").lower()
    if country in COUNTRY_REGION:
        return COUNTRY_REGION[country]

    return "Other"


# ── Exchange/market detection for UI filtering ───────────────────────────────
MARKET_SUFFIX: dict[str, str] = {
    ".L": "London", ".T": "Japan", ".AX": "Australia", ".KZ": "Kazakhstan",
}

MARKET_EXCHANGE: dict[str, str] = {
    "LSE": "London", "LON": "London",
    "JPX": "Japan", "TKS": "Japan", "TYO": "Japan",
    "ASX": "Australia",
    "NMS": "US", "NGM": "US", "NCM": "US", "NYQ": "US", "ASE": "US", "PCX": "US",
    "KAZ": "Kazakhstan",
}

MARKET_COUNTRY: dict[str, str] = {
    "united states": "US", "usa": "US",
    "united kingdom": "London",
    "japan": "Japan",
    "australia": "Australia",
    "kazakhstan": "Kazakhstan",
}


def detect_market(symbol: str, info: dict) -> str:
    """Return a UI market label more specific than the broad region."""
    sym = symbol.upper()
    for suffix, market in MARKET_SUFFIX.items():
        if sym.endswith(suffix):
            return market

    exchange = str(info.get("exchange") or "").upper()
    if exchange in MARKET_EXCHANGE:
        return MARKET_EXCHANGE[exchange]

    country = str(info.get("country") or "").lower()
    if country in MARKET_COUNTRY:
        return MARKET_COUNTRY[country]

    region = detect_region(symbol, info)
    if region == "Europe":
        return "Europe Other"
    if region == "Asia":
        return "Asia Other"
    if region == "Emerging":
        return "Emerging"
    if region == "KZ":
        return "Kazakhstan"
    if region == "US":
        return "US"
    return "Other"
