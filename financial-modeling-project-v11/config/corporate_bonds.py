"""Curated corporate-bond reference universe for the five supported markets.

These records intentionally use verified public issue/reference data instead of
pretending that a corporate bond is a Yahoo Finance equity ticker.  Live trade
price/yield is populated only where a reliable public snapshot is available.
Missing yield/price remains ``None`` and is displayed as N/A by the UI.

The dictionary key is the project symbol used by the screener.  Exchange codes
are preserved where an exchange supplies one (LSE/ASX/KASE); otherwise a clear
issuer+maturity project symbol is used.
"""

CORPORATE_BONDS: dict[str, dict] = {
    # ------------------------------------------------------------------ US --
    # Apple Inc. 2025 notes — SEC prospectus / 2025 Form 10-K.
    "AAPL-2028-4.000": {
        "name": "Apple 4.000% Notes due 2028", "issuer": "Apple Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.000, "maturity": "2028-05-12", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Apple prospectus / 2025 Form 10-K", "source_date": "2025-05-12",
    },
    "AAPL-2030-4.200": {
        "name": "Apple 4.200% Notes due 2030", "issuer": "Apple Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.200, "maturity": "2030-05-12", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Apple prospectus / 2025 Form 10-K", "source_date": "2025-05-12",
    },
    "AAPL-2032-4.500": {
        "name": "Apple 4.500% Notes due 2032", "issuer": "Apple Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.500, "maturity": "2032-05-12", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Apple prospectus / 2025 Form 10-K", "source_date": "2025-05-12",
    },
    "AAPL-2035-4.750": {
        "name": "Apple 4.750% Notes due 2035", "issuer": "Apple Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.750, "maturity": "2035-05-12", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Apple prospectus / 2025 Form 10-K", "source_date": "2025-05-12",
    },
    # Amazon.com Inc. 2025 senior-note offering — SEC prospectus supplement.
    "AMZN-2028-3.900": {
        "name": "Amazon 3.900% Notes due 2028", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 3.900, "maturity": "2028-11-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    "AMZN-2030-4.100": {
        "name": "Amazon 4.100% Notes due 2030", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.100, "maturity": "2030-11-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    "AMZN-2033-4.350": {
        "name": "Amazon 4.350% Notes due 2033", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.350, "maturity": "2033-03-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    "AMZN-2035-4.650": {
        "name": "Amazon 4.650% Notes due 2035", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 4.650, "maturity": "2035-11-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    "AMZN-2055-5.450": {
        "name": "Amazon 5.450% Notes due 2055", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 5.450, "maturity": "2055-11-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    "AMZN-2065-5.550": {
        "name": "Amazon 5.550% Notes due 2065", "issuer": "Amazon.com, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 5.550, "maturity": "2065-11-20", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Amazon prospectus supplement", "source_date": "2025",
    },
    # Dominion Energy 2025 senior notes — SEC prospectus supplement.
    "D-2030-5.000": {
        "name": "Dominion Energy 5.000% Senior Notes due 2030", "issuer": "Dominion Energy, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 5.000, "maturity": "2030-06-15", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Dominion Energy prospectus supplement", "source_date": "2025-03-06",
    },
    "D-2035-5.450": {
        "name": "Dominion Energy 5.450% Senior Notes due 2035", "issuer": "Dominion Energy, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 5.450, "maturity": "2035-03-15", "currency": "USD",
        "market": "US", "venue": "U.S. corporate bond market", "isin": None,
        "price": None, "yield_pct": None,
        "source": "SEC · Dominion Energy prospectus supplement", "source_date": "2025-03-06",
    },

    # -------------------------------------------------------------- London --
    # Official London Stock Exchange International Securities Market reference list.
    "BX60": {
        "name": "BAE Systems 5.125% Notes due 2029", "issuer": "BAE Systems plc",
        "bond_type": "Corporate · Senior Notes · Reg S", "bond_class": "Corporate",
        "coupon_pct": 5.125, "maturity": "2029-03-26", "currency": "USD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "USG07540AC42", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "BX62": {
        "name": "BAE Systems 5.250% Notes due 2031", "issuer": "BAE Systems plc",
        "bond_type": "Corporate · Senior Notes · Reg S", "bond_class": "Corporate",
        "coupon_pct": 5.250, "maturity": "2031-03-26", "currency": "USD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "USG07540AD25", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "BX90": {
        "name": "BAE Systems 5.300% Notes due 2034", "issuer": "BAE Systems plc",
        "bond_type": "Corporate · Senior Notes · Reg S", "bond_class": "Corporate",
        "coupon_pct": 5.300, "maturity": "2034-03-26", "currency": "USD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "USG07540AE08", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "70WN": {
        "name": "Barclays 4.000% Debt Instruments due 2029", "issuer": "Barclays plc",
        "bond_type": "Corporate Bond", "bond_class": "Corporate",
        "coupon_pct": 4.000, "maturity": "2029-06-26", "currency": "AUD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "AU3CB0264521", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "ZJ37": {
        "name": "Barclays 1.125% Callable Subordinated Notes due 2031", "issuer": "Barclays plc",
        "bond_type": "Corporate · Subordinated Callable", "bond_class": "Corporate",
        "coupon_pct": 1.125, "maturity": "2031-03-22", "currency": "EUR",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "XS2321466133", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "AD02": {
        "name": "Lloyds Banking Group 5.25% Subordinated Notes due 2033", "issuer": "Lloyds Banking Group plc",
        "bond_type": "Corporate · Subordinated", "bond_class": "Corporate",
        "coupon_pct": 5.250, "maturity": "2033-08-22", "currency": "SGD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "XS2668240844", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },
    "15NJ": {
        "name": "NatWest Group 6.000% Perpetual Tier 1 Notes", "issuer": "NatWest Group plc",
        "bond_type": "Corporate · Perpetual Tier 1", "bond_class": "Corporate",
        "coupon_pct": 6.000, "maturity": "Perpetual", "currency": "USD",
        "market": "London", "venue": "LSE International Securities Market",
        "isin": "US780097BQ34", "price": None, "yield_pct": None,
        "source": "London Stock Exchange · ISM instrument list", "source_date": "2025-01-31",
    },

    # ---------------------------------------------------------------- Japan --
    "JP394390ANE8": {
        "name": "Yanmar Holdings Series 3 Unsecured Bonds", "issuer": "Yanmar Holdings Co., Ltd.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 0.480, "maturity": "2027-02-19", "currency": "JPY",
        "market": "Japan", "venue": "JPX TOKYO PRO-BOND Market / JASDEC",
        "isin": "JP394390ANE8", "price": None, "yield_pct": None,
        "source": "JPX / JASDEC issue information", "source_date": "2026-08-17",
    },
    "JP318320AHF7": {
        "name": "Japan Exchange Group Series 1 Unsecured Bonds", "issuer": "Japan Exchange Group, Inc.",
        "bond_type": "Corporate · Senior Unsecured", "bond_class": "Corporate",
        "coupon_pct": 0.355, "maturity": "2027-03-16", "currency": "JPY",
        "market": "Japan", "venue": "JPX TOKYO PRO-BOND Market / JASDEC",
        "isin": "JP318320AHF7", "price": None, "yield_pct": None,
        "source": "JPX / JASDEC issue information", "source_date": "2026-08-17",
    },

    # ------------------------------------------------------------ Australia --
    # ASX Bonds Monthly Report, June 2026. Price and yield are report snapshots.
    "AYUHD": {
        "name": "Australian Unity Simple Bond due 2026", "issuer": "Australian Unity Limited",
        "bond_type": "Corporate · Senior Unsecured · Floating Rate", "bond_class": "Corporate",
        "coupon_pct": 6.49, "coupon_text": "3M BBSW + 2.15% (6.49% at report date)",
        "maturity": "2026-12-15", "currency": "AUD", "market": "Australia",
        "venue": "ASX", "isin": None, "price": 100.00, "yield_pct": 9.44,
        "source": "ASX Bonds Monthly Report · June 2026", "source_date": "2026-06-30",
        "price_date": "2026-06-30",
    },
    "AYUHE": {
        "name": "Australian Unity Simple Bond due 2028", "issuer": "Australian Unity Limited",
        "bond_type": "Corporate · Senior Unsecured · Floating Rate", "bond_class": "Corporate",
        "coupon_pct": 6.84, "coupon_text": "3M BBSW + 2.50% (6.84% at report date)",
        "maturity": "2028-12-15", "currency": "AUD", "market": "Australia",
        "venue": "ASX", "isin": None, "price": 99.75, "yield_pct": 8.63,
        "source": "ASX Bonds Monthly Report · June 2026", "source_date": "2026-06-30",
        "price_date": "2026-06-30",
    },
    "CVCHB": {
        "name": "CVC Limited Bond due 2028", "issuer": "CVC Limited",
        "bond_type": "Corporate · Senior Unsecured · Floating Rate", "bond_class": "Corporate",
        "coupon_pct": 8.79, "coupon_text": "3M BBSW + 4.50% (8.79% at report date)",
        "maturity": "2028-12-11", "currency": "AUD", "market": "Australia",
        "venue": "ASX", "isin": None, "price": 99.77, "yield_pct": 9.39,
        "source": "ASX Bonds Monthly Report · June 2026", "source_date": "2026-06-30",
        "price_date": "2026-06-30",
    },

    # ----------------------------------------------------------- Kazakhstan --
    # KASE pages are current issue/trading snapshots as at 17 Aug 2026.
    "HSBKb21": {
        "name": "Halyk Bank indexed coupon bonds HSBKb21", "issuer": "Halyk Bank of Kazakhstan JSC",
        "bond_type": "Corporate · Indexed Coupon", "bond_class": "Corporate",
        "coupon_pct": 14.85, "maturity": "2031-07-25", "currency": "KZT",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "KZ2C00011468", "price": None, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
    },
    "BIGDb7": {
        "name": "BI Development coupon bonds BIGDb7", "issuer": "BI Development Ltd.",
        "bond_type": "Corporate · Coupon Bond", "bond_class": "Corporate",
        "coupon_pct": 20.00, "maturity": "2028-05-21", "currency": "KZT",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "KZ2D00015336", "price": 102.0698, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
        "price_date": "2026-08-14",
    },
    "BIGDb11": {
        "name": "BI Development coupon bonds BIGDb11", "issuer": "BI Development Ltd.",
        "bond_type": "Corporate · Coupon Bond", "bond_class": "Corporate",
        "coupon_pct": 20.00, "maturity": "2028-05-21", "currency": "KZT",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "KZ2D00015419", "price": 102.0000, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
        "price_date": "2026-08-17",
    },
    "KZIKb41": {
        "name": "Kazakhstan Housing Company social bonds KZIKb41", "issuer": "Kazakhstan Housing Company JSC",
        "bond_type": "Corporate · Social Bond", "bond_class": "Corporate",
        "coupon_pct": 18.70, "maturity": "2028-08-27", "currency": "KZT",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "KZ2C00014751", "price": 105.2317, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
        "price_date": "2026-07-30",
    },
    "KZIKb42": {
        "name": "Kazakhstan Housing Company social bonds KZIKb42", "issuer": "Kazakhstan Housing Company JSC",
        "bond_type": "Corporate · Social Bond", "bond_class": "Corporate",
        "coupon_pct": 18.85, "maturity": "2028-09-24", "currency": "KZT",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "KZ2C00014769", "price": 105.5358, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
        "price_date": "2026-08-11",
    },
    "TMJLe8": {
        "name": "Kazakhstan Temir Zholy 5.250% international bonds", "issuer": "NC Kazakhstan Temir Zholy JSC",
        "bond_type": "Corporate · Guaranteed International Bond", "bond_class": "Corporate",
        "coupon_pct": 5.25, "maturity": "2036-04-29", "currency": "USD",
        "market": "Kazakhstan", "venue": "KASE Main Market",
        "isin": "XS3353982385 / US48669DAD49", "price": None, "yield_pct": None,
        "source": "Kazakhstan Stock Exchange (KASE)", "source_date": "2026-08-17",
    },
}

# Normalise lookup keys because API input is upper-cased. Preserve the official
# exchange/project spelling for display (important for KASE codes such as BIGDb11).
CORPORATE_BONDS = {
    key.upper(): {**value, "exchange_symbol": value.get("exchange_symbol", key)}
    for key, value in CORPORATE_BONDS.items()
}
