"""
Market universes and asset-type metadata used by the UI/API.

Supported exchange markets are deliberately limited to:
US, London, Japan, Australia and Kazakhstan.

Asset types are separated into stocks, ETFs and bonds. Bond ETFs belong to
ETF_TICKERS. BOND_TICKERS contain U.S. Treasury constant-maturity benchmarks
plus curated corporate-bond issues for the five supported markets.
"""

from config.tickers import DEFAULT_TICKERS as LEGACY_TICKERS
from config.corporate_bonds import CORPORATE_BONDS


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(t.upper() for t in items if t))


# Additional London names: large-cap + liquid mid-cap names.
LONDON_ADDITIONAL: list[str] = [
    "ANTO.L","BAE.L","BAB.L","BNZL.L","CCH.L","CNA.L","CRDA.L","FRES.L",
    "HLMA.L","IHG.L","IMI.L","ITRK.L","JD.L","MRO.L","PRU.L","SBRY.L",
    "SNG.L","STJ.L","SVT.L","UU.L","UTG.L","SMIN.L","SN.L","RS1.L",
    "SGRO.L","BLND.L","MTLN.L","HWDN.L","DCC.L","IAG.L","EZJ.L","WIZZ.L",
    "ITV.L","PSON.L","RTO.L","TW.L","BKG.L","BBOX.L","BYG.L","PHNX.L",
    "AV.L","LGEN.L","BEZ.L","TATE.L","BME.L","GNC.L","HBR.L","DEC.L",
]

# Additional Tokyo names: large/core companies + liquid mid-cap names.
JAPAN_ADDITIONAL: list[str] = [
    "8035.T","6861.T","6098.T","9983.T","4063.T","8031.T","8053.T","8001.T",
    "8002.T","9434.T","8766.T","8725.T","8630.T","7741.T","7974.T","6594.T",
    "6367.T","6273.T","6902.T","6981.T","6762.T","6723.T","7751.T","7733.T",
    "4901.T","4452.T","2802.T","2502.T","2503.T","9020.T","9022.T","9201.T",
    "9202.T","9101.T","9104.T","9107.T","1925.T","8801.T","8802.T","1801.T",
    "1802.T","1803.T","7011.T","7012.T","7013.T","7261.T","7270.T","7272.T",
    "8308.T","7182.T",
]

# Additional ASX names: large-cap + liquid mid-cap names.
AUSTRALIA_ADDITIONAL: list[str] = [
    "WDS.AX","GMG.AX","TCL.AX","ALL.AX","QBE.AX","IAG.AX","SUN.AX","AMP.AX",
    "REA.AX","SCG.AX","VCX.AX","GPT.AX","MGR.AX","COL.AX","EDV.AX","TWE.AX",
    "RHC.AX","COH.AX","SHL.AX","XRO.AX","WTC.AX","REH.AX","CAR.AX","SEK.AX",
    "CPU.AX","ASX.AX","S32.AX","MIN.AX","PLS.AX","NST.AX","EVN.AX","ORG.AX",
    "AGL.AX","APA.AX","ALD.AX","TLS.AX","TPG.AX","JBH.AX","HVN.AX","DMP.AX",
    "QAN.AX","FLT.AX","IEL.AX","JHX.AX","BXB.AX","AMC.AX","RMD.AX","SIG.AX",
    "GYG.AX","PME.AX",
]

# ETFs are kept separate from operating companies. This includes equity,
# commodity and fixed-income ETFs; the latter are still ETFs, not bonds.
ETF_TICKERS: list[str] = _unique([
    # US broad/sector/equity ETFs
    "SPY","QQQ","IWM","DIA","VTI","VOO","EFA","EEM","VEA","VWO","ARKK",
    "XLK","XLF","XLV","XLE","XLI","XLY","XLP","XLU","XLRE","XLB",
    # Commodities
    "GLD","SLV",
    # US fixed-income ETFs
    "BND","AGG","TLT","IEF","SHY","GOVT","VGIT","VGLT","VGSH","TIP","SCHP",
    "LQD","VCIT","VCSH","HYG","JNK","EMB","BNDX","IGIB","IGSB","MUB","VTEB",
    "FLOT","SGOV","BIL","JPST",
    # London-listed ETFs
    "VUSA.L","CSP1.L","IUSA.L","ISF.L","VMID.L","INRG.L","IGLT.L",
    # Japan-listed ETFs
    "1306.T","1321.T","1330.T","1343.T","1475.T","2558.T","2559.T","2631.T",
    # Australia-listed ETFs
    "VAS.AX","A200.AX","STW.AX","IVV.AX","VGS.AX","NDQ.AX","IOZ.AX","VHY.AX",
])

# U.S. Treasury constant-maturity benchmark points. These are not ETFs and are
# served from the official Treasury par-yield feed by fetcher/bonds.py.
TREASURY_BOND_TICKERS: list[str] = [
    "UST-1M","UST-1.5M","UST-2M","UST-3M","UST-4M","UST-6M",
    "UST-1Y","UST-2Y","UST-3Y","UST-5Y","UST-7Y","UST-10Y","UST-20Y","UST-30Y",
]

# Corporate-bond project symbols come from verified public exchange/issuer
# reference data in config/corporate_bonds.py.
BOND_TICKERS: list[str] = _unique(TREASURY_BOND_TICKERS + list(CORPORATE_BONDS.keys()))

_ALLOWED_MARKETS = {"US", "London", "Japan", "Australia", "Kazakhstan"}
_DISALLOWED_SUFFIXES = (
    ".DE", ".PA", ".AS", ".MI", ".MC", ".SW", ".ST", ".HE", ".OL", ".CO", ".BR", ".VI", ".LS", ".IR", ".AT",
    ".HK", ".SS", ".SZ", ".KS", ".KQ", ".SI", ".TW", ".NZ",
    ".SA", ".MX", ".IS", ".JK", ".NS", ".BO", ".JO", ".TO",
)


def _market_from_symbol(symbol: str) -> str | None:
    s = symbol.upper()
    if s.startswith("UST-"):
        return "US"
    if s in CORPORATE_BONDS:
        return CORPORATE_BONDS[s].get("market")
    if s.endswith(".L"):
        return "London"
    if s.endswith(".T"):
        return "Japan"
    if s.endswith(".AX"):
        return "Australia"
    if s.endswith(".KZ"):
        return "Kazakhstan"
    if s.endswith(_DISALLOWED_SUFFIXES):
        return None
    return "US"


_ETF_SET = set(ETF_TICKERS)
_BOND_SET = set(BOND_TICKERS)
SUPPLEMENTAL_STOCKS = _unique(LONDON_ADDITIONAL + JAPAN_ADDITIONAL + AUSTRALIA_ADDITIONAL)

# Remove ETFs and all exchange listings outside the five supported markets.
STOCK_TICKERS: list[str] = _unique([
    t for t in LEGACY_TICKERS + SUPPLEMENTAL_STOCKS
    if t.upper() not in _ETF_SET
    and t.upper() not in _BOND_SET
    and _market_from_symbol(t) in _ALLOWED_MARKETS
])

ALL_FETCHABLE_TICKERS: list[str] = _unique(STOCK_TICKERS + ETF_TICKERS + BOND_TICKERS)


def _groups(items: list[str]) -> dict[str, list[str]]:
    groups = {m: [] for m in ["US", "London", "Japan", "Australia", "Kazakhstan"]}
    for t in items:
        m = _market_from_symbol(t)
        if m in groups:
            groups[m].append(t)
    groups["All"] = list(items)
    return groups


MARKET_TICKERS: dict[str, list[str]] = _groups(STOCK_TICKERS)
ETF_MARKET_TICKERS: dict[str, list[str]] = _groups(ETF_TICKERS)
BOND_MARKET_TICKERS: dict[str, list[str]] = _groups(BOND_TICKERS)


def market_tickers(market: str, asset_type: str = "stock") -> list[str]:
    """Return curated tickers for a market / asset-type selection."""
    mk = market if market in {"All", "US", "London", "Japan", "Australia", "Kazakhstan"} else "All"
    at = (asset_type or "stock").lower()
    if at == "etf":
        return ETF_MARKET_TICKERS.get(mk, ETF_TICKERS)
    if at == "bond":
        return BOND_MARKET_TICKERS.get(mk, BOND_TICKERS)
    return MARKET_TICKERS.get(mk, STOCK_TICKERS)


def asset_type_for_ticker(symbol: str) -> str:
    s = symbol.upper()
    if s in _BOND_SET or s.startswith("UST-"):
        return "bond"
    if s in _ETF_SET:
        return "etf"
    return "stock"


def symbol_market(symbol: str) -> str:
    return _market_from_symbol(symbol) or "US"
