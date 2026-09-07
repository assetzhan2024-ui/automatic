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

        def fake_fetch(symbol, start=None, end=None, timeout=7):
            return market_h if symbol == "^GSPC" else stock_h

        with patch("portfolio.event_study.fetch_history_range", side_effect=fake_fetch), \
             patch("portfolio.event_study._report_context", side_effect=AssertionError("must not be called")):
            out = run_event_study("TEST", dates[event_pos].strftime("%Y-%m-%d"), market="US")

        self.assertEqual(out["ticker"], "TEST")
        self.assertEqual(out["estimation_window"]["observations"], 100)
        self.assertEqual(len(out["observations"]), 11)
        self.assertEqual(out["event_window"]["start"], -5)
        self.assertEqual(out["event_window"]["end_requested"], 5)
        self.assertIn("car_event_window_pct", out)
        self.assertIn("regression", out)
        self.assertEqual(out["regression"]["degrees_of_freedom"], 98)
        self.assertIn("r_squared", out["regression"])
        event_row = next(r for r in out["observations"] if r["relative_day"] == 0)
        self.assertIn("se_ar_pct", event_row)
        self.assertIn("p_value", event_row)
        self.assertIn("car_p_value", event_row)
        self.assertFalse(out["report_context"]["available"])
        self.assertTrue(out["verification"]["passed"])
        self.assertTrue(out["verification"]["regression_recomputed"])
        self.assertFalse(out["data_provenance"]["synthetic_prices_used"])

    def test_future_event_date_is_rejected_before_market_fetch(self):
        with patch("portfolio.event_study.fetch_history_range", side_effect=AssertionError("market fetch must not run")):
            with self.assertRaisesRegex(ValueError, "только по уже произошедшим"):
                run_event_study("TEST", "2099-01-01", market="US")


if __name__ == "__main__":
    unittest.main()
