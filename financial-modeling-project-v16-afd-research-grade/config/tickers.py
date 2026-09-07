"""
config/tickers.py
=================
Базовый (legacy) список тикеров.
Расширенные market-universe списки London/Japan/Australia и asset types
собираются в config/markets.py.
"""

DEFAULT_TICKERS: list[str] = [
    # ── US MEGA-CAP TECH ──────────────────────────────────────────────
    "AAPL","MSFT","NVDA","GOOGL","GOOG","META","AMZN","AVGO","ORCL","TSLA",
    "AMD","QCOM","TXN","MU","INTC","CRM","ADBE","NOW","PANW","NET",
    "CRWD","SNPS","CDNS","MRVL","KLAC","LRCX","AMAT","FTNT","ZS","OKTA",
    "DDOG","SNOW","PLTR","ABNB","UBER","LYFT","RBLX","RIVN","SMCI","TTD",
    "ROKU","TWLO","ZM","DOCN","MDB","GTLB","HUBS","VEEV","WDAY","ANSS",
    "PTC","EPAM","GLOB","CSGP","BILL","DOCU","CFLT","AFRM","COIN","APP",
    # ── US BANKS & FINANCE ────────────────────────────────────────────
    "JPM","BAC","WFC","C","GS","MS","USB","TFC","PNC","COF",
    "AXP","BK","STT","SCHW","CB","MET","PRU","AFL","ALL","PGR",
    "BLK","TROW","IVZ","AMP","HIG","WRB","RNR","CINF","RE","ACGL",
    "NDAQ","CME","ICE","CBOE","IBKR","LPLA","RJF",
    # ── US HEALTHCARE ─────────────────────────────────────────────────
    "JNJ","LLY","ABBV","MRK","PFE","TMO","ABT","AMGN","GILD","REGN",
    "VRTX","ISRG","BSX","EW","BDX","ZBH","SYK","MDT","DHR","A",
    "IQV","CRL","BIIB","BMRN","INCY","EXAS","ALNY","SRPT","CVS","WBA",
    "MCK","CAH","HUM","UNH","CI","ELV","MOH","CNC","HCA","THC",
    # ── US CONSUMER ───────────────────────────────────────────────────
    "COST","WMT","HD","MCD","SBUX","NKE","TGT","LOW","TJX","ROST",
    "BKNG","MAR","HLT","DRI","YUM","CMG","LVS","MGM","WYNN","CZR",
    "ETSY","EBAY","CPRT","ULTA","LULU","TPR","RL","PVH","KO","PEP",
    "PM","MO","STZ","TAP","MNST","KDP","PG","CL","CHD","KMB",
    "CLX","EL",
    # ── US ENERGY ─────────────────────────────────────────────────────
    "XOM","CVX","COP","EOG","SLB","HAL","BKR","PSX","VLO","MPC",
    "OXY","DVN","FANG","MRO","APA","HES","SM","CIVI","PR","KMI",
    "WMB","OKE","ET","EPD","TRGP",
    # ── US INDUSTRIALS ────────────────────────────────────────────────
    "HON","CAT","DE","GE","EMR","ETN","ITW","ROK","PH","FTV",
    "CARR","OTIS","LMT","RTX","NOC","GD","BA","HEI","TDG","CTAS",
    "NSC","UNP","CSX","ODFL","SAIA","JBHT","MMM","AME","ROP","IDEX",
    "IR","FAST","GWW","FDX","UPS","CHRW","EXPD","XPO","R","TRU",
    # ── US UTILITIES & REAL ESTATE ────────────────────────────────────
    "NEE","DUK","SO","D","AEP","SRE","EXC","ED","FE","WEC",
    "AMT","PLD","CCI","EQIX","DLR","PSA","EQR","AVB","ESS","MAA",
    "O","VICI","GLPI","KIM","WRE","NNN","STAG","COLD","TRNO","EGP",
    # ── US MEDIA & TELECOM ────────────────────────────────────────────
    "NFLX","DIS","CMCSA","PARA","WBD","T","VZ","TMUS","SIRI","SPOT",
    "TTWO","EA","MTCH","ZG","YELP","TRIP",
    # ── US MATERIALS ──────────────────────────────────────────────────
    "LIN","APD","SHW","PPG","ECL","NEM","FCX","NUE","STLD","RS",
    "CF","MOS","IFF","DOW","LYB","PKG","IP","WRK","SEE","BALL",
    "ALB","LAC","MP","NXPI","ON","WOLF","QRVO","SWKS",
    # ── EUROPE UK ─────────────────────────────────────────────────────
    "HSBA.L","LLOY.L","BARC.L","NWG.L","STAN.L","SHEL.L","BP.L","GSK.L","AZN.L","RIO.L",
    "GLEN.L","AAL.L","VOD.L","BT-A.L","REL.L","EXPN.L","LSEG.L","NG.L","SSE.L","SGE.L",
    "IMB.L","ULVR.L","BATS.L","DGE.L","RKT.L","CPG.L","MKS.L","TSCO.L","INF.L","AUTO.L",
    "PSN.L","WEIR.L","RR.L","III.L","SDR.L","AHT.L","HIK.L","LAND.L","MNDI.L","SMWH.L",
    "SPX.L","WPP.L",
    # ── EUROPE DACH BENELUX ───────────────────────────────────────────
    "SAP","SIE.DE","ALV.DE","BAS.DE","BAYN.DE","BMW.DE","MBG.DE","VOW3.DE","DBK.DE","DTE.DE",
    "EOAN.DE","RWE.DE","MUV2.DE","DHL.DE","ADS.DE","HEN3.DE","BNTX.DE","IFX.DE","ZAL.DE","SRT3.DE",
    "HEIA.AS","INGA.AS","PHIA.AS","UNA.AS","NN.AS","ASML","ADYEN.AS","LONN.SW","NOVN.SW","ROG.SW",
    "NESN.SW","ABBN.SW","ZURN.SW",
    # ── EUROPE FR NORDIC SPAIN ITALY ──────────────────────────────────
    "MC.PA","OR.PA","BNP.PA","SAN.PA","AI.PA","TTE","ENGI.PA","LR.PA","DG.PA","RI.PA",
    "CAP.PA","EL.PA","KER.PA","VIE.PA","ERIC-B.ST","VOLV-B.ST","SEB-A.ST","SHB-A.ST","HM-B.ST","ATCO-A.ST",
    "NOKIA.HE","SAMPO.HE","TEF.MC","BBVA.MC","ITX.MC","REP.MC","ENI.MI","ENEL.MI","ISP.MI","UCG.MI",
    "TIT.MI","LDO.MI","STLAM.MI",
    # ── EUROPE GLOBAL ADRs ────────────────────────────────────────────
    "HSBC","DB","ING","BNPQY","NVO","AZN","LVMUY","BCS","SMFG","NMR",
    "KB","SHG",
    # ── ASIA CHINA ────────────────────────────────────────────────────
    "BABA","PDD","BIDU","JD","NIO","XPEV","LI","NTES","BILI","TME",
    "TCEHY","VIPS","IQ","YUMC","TAL","RLX","GOTU","LAIX","9988.HK","0700.HK",
    "1398.HK","0941.HK","2318.HK","0005.HK","0883.HK","1299.HK","3690.HK","0175.HK","1177.HK","2382.HK",
    "0386.HK","1211.HK","2020.HK","9618.HK","9999.HK","9888.HK",
    # ── ASIA JAPAN ────────────────────────────────────────────────────
    "SONY","TM","HMC","TSM","8306.T","8316.T","8411.T","7203.T","6758.T","9984.T",
    "4519.T","7267.T","7269.T","6502.T","6701.T","6752.T","6954.T","9432.T","9433.T","4568.T",
    "4523.T","2914.T","3382.T","8058.T",
    # ── ASIA KOREA TAIWAN SEA AUSTRALIA ───────────────────────────────
    "005930.KS","000660.KS","035420.KS","051910.KS","207940.KS","000270.KS","005380.KS","066570.KS","2330.TW","2454.TW",
    "2317.TW","2303.TW","2308.TW","2882.TW","D05.SI","O39.SI","U11.SI","Z74.SI","C6L.SI","CBA.AX",
    "BHP.AX","CSL.AX","WBC.AX","NAB.AX","ANZ.AX","WES.AX","WOW.AX","MQG.AX","FMG.AX","RIO.AX",
    "STO.AX",
    # ── INDIA ─────────────────────────────────────────────────────────
    "WIT","INFY","HDB","IBN","RDY","MFG","RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","BAJFINANCE.NS","WIPRO.NS","HCLTECH.NS","AXISBANK.NS","KOTAKBANK.NS","LT.NS",
    "MARUTI.NS","TITAN.NS","ULTRACEMCO.NS","ASIANPAINT.NS","NESTLEIND.NS","SUNPHARMA.NS",
    # ── EMERGING BRAZIL LATAM ─────────────────────────────────────────
    "VALE","ITUB","MELI","PBR","SBS","ERJ","GGB","CIG","VIV","BRFS",
    "BBDC4.SA","PETR4.SA","ABEV3.SA","B3SA3.SA","LREN3.SA","VIVT3.SA","AMXL.MX","WALMEX.MX","GFNORTEO.MX","FEMSAUBD.MX",
    # ── EMERGING OTHER ────────────────────────────────────────────────
    "THYAO.IS","GARAN.IS","ISCTR.IS","EREGL.IS","NPN.JO","MTN.JO","SBK.JO","AGL.JO","KSPI",
    # ── KAZAKHSTAN KASE ───────────────────────────────────────────────
    "HSBK.KZ","KCEL.KZ","KZTK.KZ","BAST.KZ","KEGC.KZ","CSBN.KZ","FFIN.KZ","HRDN.KZ","KKGB.KZ","KZAP.KZ",
    "AIRA.KZ","KZTO.KZ","KMGZ.KZ","STKZ.KZ","GLOTR.KZ",
    # ── CANADA ────────────────────────────────────────────────────────
    "SHOP","CP","CNR","RY","TD","BNS","BMO","CM","ENB","TRP",
    "SU","CNQ","CVE","BCE","MFC","ABX","AEM","KGC","WPM","FNV",
    # ── US ETFs ───────────────────────────────────────────────────────
    "SPY","QQQ","IWM","DIA","EFA","EEM","GLD","SLV","TLT","HYG",
    "XLK","XLF","XLV","XLE","XLI","XLY","XLP","XLU","XLRE","XLB",
    "VTI","VOO","VEA","VWO","BND","AGG","LQD","IEF","TIP","ARKK",
    # ── ADDITIONAL WELL-KNOWN GLOBAL STOCKS ───────────────────────────
    "GAIA","BRK-B","V","MA","CSCO","IBM","ACN","ADP","ADI","MCHP",
    "MSI","DELL","HPE","HPQ","FICO","TEAM","U","MSTR","HOOD","SOFI",
    "XYZ","PYPL","INTU","SPGI","MCO","MMC","AON","AJG","TRV","AIG",
    "FITB","HBAN","CFG","KEY","RF","MTB","SYF","NTRS","CTRA","EQT",
    "LNG","NRG","CEG","VST","GEV","VRT","PWR","URI","AXON","WAB",
    "JCI","TT","PCAR","CMI","DAL","UAL","LUV","AAL","JBLU","ALK",
    "WELL","SPG","VTR","ARE","CBRE","DOC","CPT","INVH","REG","OHI",
    "HST","REXR","FOXA","FOX","NWSA","NWS","CHTR","RDDT","PINS","SNAP",
    "IAC","LYV","WMG","SCCO","CE","DD","EMN","MLM","VMC","EXP",
    "RPM","AVY","FMC","BMY","NVS","SNY","RMD","DXCM","IDXX","GEHC",
    "HOLX","COO","PODD","ILMN","MRNA","ZTS","COR","WST","STE","TECH",
    "DGX","LH","UHS","DVA","SOLV","KVUE","RACE","F","GM","STLA",
    "DECK","ONON","CAVA","DPZ","KHC","GIS","HSY","SYY","KR","DG",
    "DLTR","BBY","AZO","ORLY","TSCO","KMX","GPC","LKQ","CVNA","WSM",
    "RH","LEVI","CROX","ELF","CELH","CHWY","CART","DASH","DUOL","BROS",
    "WING","TXRH","DKS","FIVE","ANF","AEO","GAP","VSCO","HAS","MAT",
    "HRL","CPB","MKC","CAG","SJM","BG","ADM","TSN","PPC","CASY",
    "BJ","PTLO","TOST","ARM","GRAB","NU","BEKE","ZTO","CPNG","PKX",
    "MUFG","TRI","WCN","NTR","CNI","BAM","BN","BIP","BEP","TIXT",
    "CLS","GIL","ATD.TO","CSU.TO","DOL.TO","QSR.TO","WCN.TO","IFC.TO","SLF.TO","POW.TO",
    "GWO.TO",
]
