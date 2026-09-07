import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import sys, types

if "yfinance" not in sys.modules:
    yf = types.ModuleType("yfinance")
    class _DummyTicker:
        def __init__(self, *a, **k): pass
    yf.Ticker = _DummyTicker
    sys.modules["yfinance"] = yf

from portfolio.historical_validation import run_historical_model_validation, AssetMeta


class HistoricalValidationTests(unittest.TestCase):
    def test_nine_rolling_out_of_sample_windows_and_no_lookahead(self):
        dates = pd.bdate_range("2013-12-02", "2025-12-31")
        rng = np.random.default_rng(123)
        market = rng.normal(0.00035, 0.009, len(dates))
        prices = {}
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        for i, t in enumerate(tickers):
            r = 0.00005 * i + (0.75 + i * 0.1) * market + rng.normal(0, 0.005 + i * 0.0005, len(dates))
            prices[t] = pd.Series(100.0 * np.cumprod(1.0 + r), index=dates)
        metas = {t: AssetMeta(t, "stock", "US", "USD") for t in tickers}
        irx = pd.Series(2.0, index=dates)

        with patch("portfolio.historical_validation._preload_prices", return_value=(prices, metas, {"price_source":"test"})), \
             patch("portfolio.historical_validation._fetch_historical_rf", return_value=irx), \
             patch("portfolio.historical_validation.SIMULATIONS", 500):
            out = run_historical_model_validation(tickers, 100_000.0)

        self.assertEqual(len(out["windows"]), 9)
        self.assertEqual([w["test_period"]["year"] for w in out["windows"]], list(range(2017, 2026)))
        self.assertTrue(all(w["status"] == "ok" for w in out["windows"]))
        self.assertTrue(all(w["integrity"]["no_lookahead_verified"] for w in out["windows"]))
        self.assertTrue(all(abs(sum(x["weight_pct"] for x in w["portfolio"]["allocation"]) - 100.0) < 1e-4 for w in out["windows"]))
        self.assertTrue(all("actual_return_pct" in w["actual"] for w in out["windows"]))
        self.assertEqual(out["summary"]["successful_windows"], 9)


if __name__ == "__main__":
    unittest.main()
