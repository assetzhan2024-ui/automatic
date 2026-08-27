import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import sys, types

# The CI sandbox used for validation has no external yfinance package.
# Stub it so the pure event-study math can be tested with mocked histories.
if "yfinance" not in sys.modules:
    yf = types.ModuleType("yfinance")
    class _DummyTicker:
        def __init__(self, *a, **k): pass
    yf.Ticker = _DummyTicker
    sys.modules["yfinance"] = yf

from portfolio.event_study import run_event_study, _event_cache


def _history_from_returns(ticker, dates, returns):
    prices = 100.0 * np.cumprod(np.r_[1.0, 1.0 + np.asarray(returns, dtype=float)])
    return {
        "ticker": ticker,
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "closes": prices.tolist(),
    }


class EventStudyCoreTests(unittest.TestCase):
    def setUp(self):
        _event_cache.clear()

    def test_core_event_study_does_not_wait_for_report_context(self):
        dates = pd.bdate_range("2024-01-02", periods=420)
        rng = np.random.default_rng(7)
        market_r = rng.normal(0.0003, 0.009, len(dates) - 1)
        stock_r = 0.0001 + 1.15 * market_r + rng.normal(0, 0.006, len(market_r))
        # Add a visible event-day shock.
        event_pos = 300
        stock_r[event_pos - 1] += 0.035
        stock_h = _history_from_returns("TEST", dates, stock_r)
        market_h = _history_from_returns("^GSPC", dates, market_r)

        def fake_fetch(symbol, period="2y"):
            return market_h if symbol == "^GSPC" else stock_h

        with patch("portfolio.event_study.fetch_history", side_effect=fake_fetch), \
             patch("portfolio.event_study._report_context", side_effect=AssertionError("must not be called")):
            out = run_event_study("TEST", dates[event_pos].strftime("%Y-%m-%d"), market="US")

        self.assertEqual(out["ticker"], "TEST")
        self.assertEqual(out["estimation_window"]["observations"], 100)
        self.assertGreaterEqual(len(out["observations"]), 11)
        self.assertIn("car_event_window_pct", out)
        self.assertFalse(out["report_context"]["available"])


if __name__ == "__main__":
    unittest.main()
