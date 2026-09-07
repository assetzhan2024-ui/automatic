import sys, types, unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

if "yfinance" not in sys.modules:
    yf = types.ModuleType("yfinance")
    class _DummyTicker:
        def __init__(self, *a, **k): pass
    yf.Ticker = _DummyTicker
    sys.modules["yfinance"] = yf

from portfolio.historical_validation import (
    AssetMeta,
    build_historical_validation_forecast,
    reveal_historical_actual,
    _interactive_sessions,
)


class InteractiveHistoricalValidationTests(unittest.TestCase):
    def setUp(self):
        _interactive_sessions.clear()

    def _training_prices(self):
        dates = pd.bdate_range("2019-01-01", "2021-12-31")
        rng = np.random.default_rng(101)
        common = rng.normal(0.00035, 0.009, len(dates))
        out = {}
        for i, t in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            ret = (0.7 + 0.08*i) * common + rng.normal(0.0001*i, 0.0045 + i*0.0003, len(dates))
            out[t] = pd.Series(100*np.cumprod(1+ret), index=dates)
        return out

    def _test_prices(self, starts):
        dates = pd.bdate_range("2022-01-03", "2022-12-30")
        rng = np.random.default_rng(202)
        common = rng.normal(-0.00015, 0.012, len(dates))
        out = {}
        for i, t in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            ret = (0.75 + 0.05*i) * common + rng.normal(0, 0.005, len(dates))
            out[t] = pd.Series(float(starts[t]) * np.cumprod(1+ret), index=dates)
        return out

    def test_forecast_is_frozen_before_actual_market_is_opened(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        metas = {t: AssetMeta(t, "stock", "US", "USD") for t in tickers}
        train = self._training_prices()

        calls = []
        def bounded_forecast(tickers_arg, start, end, min_observations=2, allow_partial=False):
            calls.append((start, end))
            self.assertEqual(start, "2019-01-01")
            self.assertEqual(end, "2021-12-31")
            return train, metas, {"requested_range": {"start": start, "end": end}}

        with patch("portfolio.historical_validation._bounded_usd_prices", side_effect=bounded_forecast), \
             patch("portfolio.historical_validation._historical_rf_bounded", return_value=(1.5, "2021-12-31")), \
             patch("portfolio.historical_validation.SIMULATIONS", 250):
            forecast = build_historical_validation_forecast(tickers, 100000, 2022)

        self.assertEqual(calls, [("2019-01-01", "2021-12-31")])
        self.assertFalse(forecast["integrity"]["test_market_data_loaded"])
        self.assertEqual(forecast["test_period"]["year"], 2022)
        self.assertAlmostEqual(sum(x["weight_pct"] for x in forecast["portfolio"]["allocation"]), 100.0, places=3)
        self.assertIn(forecast["validation_id"], _interactive_sessions)
        for model in (forecast["gbm"], forecast["bootstrap"]):
            self.assertAlmostEqual(model["p50_portfolio_value_usd"], 100000 * (1 + model["p50_return_pct"] / 100), delta=2.0)
            self.assertAlmostEqual(model["p50_profit_loss_usd"], model["p50_portfolio_value_usd"] - 100000, places=2)
            self.assertEqual(len(model["asset_breakdown"]), 4)
            self.assertAlmostEqual(sum(x["start_amount_usd"] for x in model["asset_breakdown"]), 100000, delta=0.05)

        session = _interactive_sessions[forecast["validation_id"]][1]
        test = self._test_prices(session["start_prices_usd"])
        actual_calls = []
        def bounded_actual(tickers_arg, start, end, min_observations=2):
            actual_calls.append((start, end))
            self.assertEqual(start, "2022-01-01")
            self.assertEqual(end, "2022-12-31")
            return test, metas, {"requested_range": {"start": start, "end": end}}

        with patch("portfolio.historical_validation._bounded_usd_prices", side_effect=bounded_actual):
            actual = reveal_historical_actual(forecast["validation_id"])

        self.assertEqual(actual_calls, [("2022-01-01", "2022-12-31")])
        self.assertTrue(actual["integrity"]["forecast_was_frozen_before_actual"])
        self.assertTrue(actual["integrity"]["test_market_data_loaded_after_forecast"])
        self.assertIn("actual_return_pct", actual["actual"])
        self.assertIn("actual_percentile", actual["gbm"])
        self.assertIn("actual_percentile", actual["bootstrap"])
        self.assertEqual(len(actual["actual"]["asset_results"]), 4)
        self.assertAlmostEqual(
            sum(x["ending_amount_usd"] for x in actual["actual"]["asset_results"]),
            actual["actual"]["ending_wealth_usd"],
            delta=0.05,
        )
        self.assertAlmostEqual(
            sum(x["profit_loss_usd"] for x in actual["actual"]["asset_results"]),
            actual["actual"]["profit_loss_usd"],
            delta=0.05,
        )

    def test_window_mapping_extends_back_to_2017(self):
        from portfolio.historical_validation import VALIDATION_WINDOWS_BY_YEAR
        self.assertEqual(VALIDATION_WINDOWS_BY_YEAR[2017], ("2014-01-01", "2016-12-31", "2017-01-01", "2017-12-31"))
        self.assertEqual(VALIDATION_WINDOWS_BY_YEAR[2025], ("2022-01-01", "2024-12-31", "2025-01-01", "2025-12-31"))

    def test_only_supported_fixed_years(self):
        with self.assertRaisesRegex(ValueError, "2017–2025"):
            build_historical_validation_forecast(["AAA", "BBB"], 100000, 2026)


if __name__ == "__main__":
    unittest.main()
