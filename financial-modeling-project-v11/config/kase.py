"""
config/kase.py
==============
Статические метаданные для казахстанских тикеров (KASE).

Yahoo Finance часто возвращает пустой info для .KZ символов.
Этот модуль обеспечивает резервные данные (название, сектор, индустрия),
чтобы строка в таблице была информативной даже без ответа от API.
"""

# Тикеры KZ, которые торгуются под не-.KZ символами (ADR/GDR),
# но всё равно принадлежат Казахстану.
KZ_SPECIAL: set[str] = {"KSPI", "KASB", "HSBK"}

# Статический fallback для KASE-листинга.
# Ключи — верхний регистр с суффиксом .KZ.
KASE_META: dict[str, dict] = {
    "HSBK.KZ":  {"name": "Halyk Bank",            "sector": "Financials",             "industry": "Banks"},
    "KCEL.KZ":  {"name": "Kcell",                  "sector": "Communication Services", "industry": "Telecom Services"},
    "KZTK.KZ":  {"name": "Kazakhtelecom",          "sector": "Communication Services", "industry": "Telecom Services"},
    "BAST.KZ":  {"name": "Baspana Holding",        "sector": "Financials",             "industry": "Financial Services"},
    "KEGC.KZ":  {"name": "KEGOC",                  "sector": "Utilities",              "industry": "Electric Utilities"},
    "CSBN.KZ":  {"name": "Bank CenterCredit",      "sector": "Financials",             "industry": "Banks"},
    "FFIN.KZ":  {"name": "Freedom Finance Life",   "sector": "Financials",             "industry": "Insurance"},
    "HRDN.KZ":  {"name": "Horoz",                  "sector": "Industrials",            "industry": "Building Products"},
    "KKGB.KZ":  {"name": "KazakhGold",             "sector": "Materials",              "industry": "Gold"},
    "KZAP.KZ":  {"name": "KazMunaiGas AP",         "sector": "Energy",                 "industry": "Oil & Gas E&P"},
    "AIRA.KZ":  {"name": "Air Astana",             "sector": "Industrials",            "industry": "Airlines"},
    "KZTO.KZ":  {"name": "KazTransOil",            "sector": "Energy",                 "industry": "Oil & Gas Midstream"},
    "KMGZ.KZ":  {"name": "KMG EP",                "sector": "Energy",                 "industry": "Oil & Gas E&P"},
    "STKZ.KZ":  {"name": "Steppe Cement",          "sector": "Materials",              "industry": "Construction Materials"},
    "GLOTR.KZ": {"name": "Freedom Finance Global", "sector": "Financials",             "industry": "Capital Markets"},
}


# Маппинг: наш символ (.KZ) → реальный тикер на сайте kase.kz
# Некоторые символы отличаются от того что используем мы
KASE_SITE_TICKER: dict[str, str] = {
    "CSBN.KZ":  "CCBN",    # Bank CenterCredit — на KASE торгуется как CCBN
    "HSBK.KZ":  "HSBK",
    "KCEL.KZ":  "KCEL",
    "KZTK.KZ":  "KZTK",
    "BAST.KZ":  "BAST",
    "KEGC.KZ":  "KEGC",
    "FFIN.KZ":  "FFIN",
    "HRDN.KZ":  "HRDN",
    "KKGB.KZ":  "KKGB",
    "KZAP.KZ":  "KZAP",
    "AIRA.KZ":  "AIRA",
    "KZTO.KZ":  "KZTO",
    "KMGZ.KZ":  "KMGZ",
    "STKZ.KZ":  "STKZ",
    "GLOTR.KZ": "GLOTR",
}


def kase_site_ticker(symbol: str) -> str:
    """Вернуть реальный тикер для URL на kase.kz."""
    return KASE_SITE_TICKER.get(symbol.upper(), symbol.upper().replace(".KZ", ""))


def kase_candidates(symbol: str) -> list[str]:
    """
    Вернуть список вариантов символа для перебора при запросе к yfinance.
    Yahoo Finance нестабильно поддерживает .KZ — пробуем несколько вариантов.
    """
    base = symbol.upper().replace(".KZ", "")
    return [
        symbol,        # HSBK.KZ  — прямой (работает для части тикеров)
        base,          # HSBK     — GDR/ADR если торгуется на глобальной бирже
        f"{base}.IL",  # HSBK.IL  — нотация Interactive Brokers
        f"{base}.ME",  # HSBK.ME  — кросс-листинг на Московской бирже
    ]
