"""U.S. Treasury benchmark yield loader.

The Bonds section represents actual fixed-income benchmark points rather than
bond ETFs. Data comes from the official U.S. Treasury Daily Treasury Par Yield
Curve XML feed. Each row is a constant-maturity benchmark (for example 10Y).
"""

from datetime import datetime, timedelta
import threading
import urllib.request
import xml.etree.ElementTree as ET

MATURITIES: dict[str, tuple[str, str]] = {
    "UST-1M":   ("1 Month",  "BC_1MONTH"),
    "UST-1.5M": ("1.5 Month","BC_1_5MONTH"),
    "UST-2M":   ("2 Month",  "BC_2MONTH"),
    "UST-3M":   ("3 Month",  "BC_3MONTH"),
    "UST-4M":   ("4 Month",  "BC_4MONTH"),
    "UST-6M":   ("6 Month",  "BC_6MONTH"),
    "UST-1Y":   ("1 Year",   "BC_1YEAR"),
    "UST-2Y":   ("2 Year",   "BC_2YEAR"),
    "UST-3Y":   ("3 Year",   "BC_3YEAR"),
    "UST-5Y":   ("5 Year",   "BC_5YEAR"),
    "UST-7Y":   ("7 Year",   "BC_7YEAR"),
    "UST-10Y":  ("10 Year",  "BC_10YEAR"),
    "UST-20Y":  ("20 Year",  "BC_20YEAR"),
    "UST-30Y":  ("30 Year",  "BC_30YEAR"),
}

_CACHE: dict | None = None
_CACHE_AT: datetime | None = None
_LOCK = threading.Lock()
_CACHE_TTL = timedelta(minutes=30)


def _url() -> str:
    year = datetime.utcnow().year
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
        f"?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
    )


def _download() -> bytes:
    req = urllib.request.Request(
        _url(),
        headers={"User-Agent": "Mozilla/5.0 FinancialModelingProject/1.0"},
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        return response.read()


def parse_latest_curve(xml_bytes: bytes) -> dict:
    """Parse the latest available date from a Treasury Atom/XML feed."""
    root = ET.fromstring(xml_bytes)
    latest: tuple[str, dict] | None = None

    for entry in root.iter():
        if not entry.tag.endswith("entry"):
            continue
        props = None
        for node in entry.iter():
            if node.tag.endswith("properties"):
                props = node
                break
        if props is None:
            continue

        values: dict[str, str] = {}
        for child in list(props):
            key = child.tag.split("}")[-1]
            if child.text is not None and child.text.strip():
                values[key] = child.text.strip()

        date = values.get("NEW_DATE") or values.get("QUOTE_DATE") or ""
        if not date:
            continue
        if latest is None or date > latest[0]:
            latest = (date, values)

    if latest is None:
        raise ValueError("Treasury XML contains no yield-curve records")

    date, values = latest
    curve = {"source_date": date[:10]}
    for symbol, (_label, xml_key) in MATURITIES.items():
        raw = values.get(xml_key)
        try:
            curve[symbol] = float(raw) if raw not in (None, "") else None
        except Exception:
            curve[symbol] = None
    return curve


def get_latest_curve(force: bool = False) -> dict:
    global _CACHE, _CACHE_AT
    now = datetime.utcnow()
    with _LOCK:
        if not force and _CACHE is not None and _CACHE_AT and now - _CACHE_AT < _CACHE_TTL:
            return dict(_CACHE)

    curve = parse_latest_curve(_download())
    with _LOCK:
        _CACHE, _CACHE_AT = dict(curve), now
    return curve


def fetch_bond(symbol: str) -> dict:
    symbol = symbol.upper()
    if symbol not in MATURITIES:
        return {
            "ticker": symbol, "name": symbol, "asset_type": "bond", "market": "US",
            "region": "US", "currency": "USD", "error": "unknown bond benchmark",
        }

    label, _ = MATURITIES[symbol]
    try:
        curve = get_latest_curve()
        yld = curve.get(symbol)
        return {
            "ticker": symbol,
            "name": f"U.S. Treasury {label}",
            "issuer": "U.S. Department of the Treasury",
            "bond_type": "Government · Constant Maturity",
            "maturity": label,
            "yield_pct": yld,
            "currency": "USD",
            "region": "US",
            "market": "US",
            "asset_type": "bond",
            "source": "U.S. Treasury Daily Par Yield Curve",
            "source_date": curve.get("source_date"),
            "fetched_at": datetime.utcnow().isoformat(),
            "price": None,
            "score_pct": None,
            "ratings": {},
            "error": None if yld is not None else "yield unavailable for latest date",
        }
    except Exception as exc:
        return {
            "ticker": symbol,
            "name": f"U.S. Treasury {label}",
            "issuer": "U.S. Department of the Treasury",
            "bond_type": "Government · Constant Maturity",
            "maturity": label,
            "yield_pct": None,
            "currency": "USD",
            "region": "US",
            "market": "US",
            "asset_type": "bond",
            "source_date": None,
            "fetched_at": datetime.utcnow().isoformat(),
            "score_pct": None,
            "ratings": {},
            "error": str(exc),
        }


def has_bond_data(record: dict) -> bool:
    return record.get("yield_pct") is not None
