import unittest
import numpy as np

from portfolio.optimizer import (
    TRADING_DAYS,
    analyze_portfolio,
    simulate_portfolio_gbm,
    simulate_portfolio_bootstrap,
)
from portfolio.snapshot import save_portfolio_snapshot, clear_portfolio_snapshots, get_portfolio_snapshot
from portfolio.forecast import run_snapshot_forecast


class PortfolioArchitectureTests(unittest.TestCase):
    def tearDown(self):
        clear_portfolio_snapshots()

    def test_default_horizon_is_252_trading_days(self):
        allocation = [
            {"ticker": "A", "weight": 0.6, "weight_pct": 60.0},
            {"ticker": "B", "weight": 0.4, "weight_pct": 40.0},
        ]
        metrics = [
            {"ticker": "A", "expected_return_pct": 8.0},
            {"ticker": "B", "expected_return_pct": 5.0},
        ]
        cov = [[0.04, 0.005], [0.005, 0.01]]
        gbm = simulate_portfolio_gbm(100_000, allocation, metrics, cov, simulations=200, seed=1)
        self.assertEqual(gbm["horizon_days"], TRADING_DAYS)
        self.assertEqual(gbm["time_basis"], "252 trading days = 1 year")
        self.assertEqual(gbm["rebalancing"], "buy_and_hold")

    def test_bootstrap_is_buy_and_hold_not_constant_weight(self):
        # Every sampled day is identical: asset A +10%, asset B 0%.
        # With 50/50 initial weights and 2 days, buy-and-hold terminal wealth is
        # 50*1.1^2 + 50 = 110.5. A daily rebalanced portfolio would be 110.25.
        allocation = [
            {"ticker": "A", "weight": 0.5, "weight_pct": 50.0},
            {"ticker": "B", "weight": 0.5, "weight_pct": 50.0},
        ]
        history = [
            {"date": f"d{i}", "returns": {"A": 0.10, "B": 0.0}}
            for i in range(100)
        ]
        out = simulate_portfolio_bootstrap(
            100.0, allocation, history,
            horizon_days=2, simulations=100, block_size=1, seed=7,
        )
        self.assertAlmostEqual(out["scenarios"]["median_case_kzt"], 110.5, places=6)
        self.assertEqual(out["rebalancing"], "buy_and_hold")

    def test_forecast_uses_snapshot_and_does_not_rerun_markowitz(self):
        result = {
            "amount_kzt": 100000.0,
            "selected": ["A", "B"],
            "portfolio": {"objective": "min_variance"},
            "allocation": [
                {"ticker": "A", "weight": 0.25, "weight_pct": 25.0},
                {"ticker": "B", "weight": 0.75, "weight_pct": 75.0},
            ],
            "individual_metrics": [
                {"ticker": "A", "expected_return_pct": 7.0},
                {"ticker": "B", "expected_return_pct": 4.0},
            ],
            "covariance": {"matrix": [[0.02, 0.002], [0.002, 0.01]]},
            "_engine": {
                "names": ["A", "B"],
                "weights": [0.25, 0.75],
                "expected_returns": [0.07, 0.04],
                "covariance": [[0.02, 0.002], [0.002, 0.01]],
                "risk_free_rate": 0.0,
                "time_basis_trading_days": 252,
                "rebalancing": "buy_and_hold",
            },
        }
        history = [
            {"date": f"d{i}", "returns": {"A": 0.001, "B": -0.0002}}
            for i in range(120)
        ]
        sid = save_portfolio_snapshot(result, history)
        snap = get_portfolio_snapshot(sid)
        f = run_snapshot_forecast(snap, model="gbm", horizon_days=10, simulations=200, seed=42)
        self.assertEqual(f["portfolio_objective"], "min_variance")
        self.assertEqual([round(x["weight"], 8) for x in f["portfolio_weights"]], [0.25, 0.75])


    def test_concentration_policy_caps(self):
        from portfolio.optimizer import _concentration_cap
        self.assertEqual(_concentration_cap(1, "constrained"), 1.0)
        self.assertEqual(_concentration_cap(2, "constrained"), 0.60)
        self.assertEqual(_concentration_cap(3, "constrained"), 0.45)
        self.assertEqual(_concentration_cap(4, "constrained"), 0.35)
        self.assertEqual(_concentration_cap(5, "constrained"), 0.25)
        self.assertEqual(_concentration_cap(20, "unconstrained"), 1.0)

    def test_more_than_12_assets_has_no_artificial_asset_count_cap(self):
        tickers = [f"T{i}" for i in range(13)]
        dates = np.arange("2024-01-01", "2025-06-01", dtype="datetime64[D]")[:300]

        def record_fetcher(t):
            return {"ticker": t, "name": t, "asset_type": "stock", "currency": "USD", "market": "TEST"}

        def chart_fetcher(t, period="5y"):
            k = int(t[1:]) + 1
            x = np.arange(len(dates), dtype=float)
            closes = 100.0 * np.exp((0.0002 + k * 1e-6) * x + 0.002 * np.sin(x / (5 + k)))
            return {"dates": [str(d) for d in dates], "closes": closes.tolist()}

        out = analyze_portfolio(
            tickers, 1_000_000,
            record_fetcher=record_fetcher,
            chart_fetcher=chart_fetcher,
            curve_history=np.array([]),
            objective="min_variance",
        )
        self.assertEqual(len(out["selected"]), 13)
        self.assertAlmostEqual(sum(x["weight"] for x in out["allocation"]), 1.0, places=8)

    def test_missing_pairwise_correlation_is_an_error_not_zero(self):
        a_dates = np.arange("2023-01-01", "2024-03-01", dtype="datetime64[D]")[:220]
        b_dates = np.arange("2025-01-01", "2026-03-01", dtype="datetime64[D]")[:220]

        def record_fetcher(t):
            return {"ticker": t, "name": t, "asset_type": "stock", "currency": "USD", "market": "TEST"}

        def chart_fetcher(t, period="5y"):
            dates = a_dates if t == "A" else b_dates
            x = np.arange(len(dates), dtype=float)
            closes = 100.0 * np.exp(0.0003 * x + 0.001 * np.sin(x / 7))
            return {"dates": [str(d) for d in dates], "closes": closes.tolist()}

        with self.assertRaisesRegex(ValueError, "Недостаточно совместных исторических наблюдений"):
            analyze_portfolio(
                ["A", "B"], 100000,
                record_fetcher=record_fetcher,
                chart_fetcher=chart_fetcher,
                curve_history=np.array([]),
                objective="min_variance",
            )

    def test_min_variance_does_not_overwrite_max_sharpe_frontier_point(self):
        dates = np.arange("2022-01-01", "2025-01-01", dtype="datetime64[D]")[:500]

        def record_fetcher(t):
            return {"ticker": t, "name": t, "asset_type": "stock", "currency": "USD", "market": "TEST"}

        def chart_fetcher(t, period="5y"):
            x = np.arange(len(dates), dtype=float)
            k = {"A": 1, "B": 2, "C": 3}[t]
            logp = (0.00012 * k) * x + (0.0025 * k) * np.sin(x / (7 + k)) + (0.001 * (4-k)) * np.cos(x / (11+k))
            return {"dates": [str(d) for d in dates], "closes": (100 * np.exp(logp)).tolist()}

        out = analyze_portfolio(
            ["A", "B", "C"], 100000,
            record_fetcher=record_fetcher, chart_fetcher=chart_fetcher,
            curve_history=np.array([]), objective="min_variance", risk_free_rate_pct=2.0,
        )
        chosen = out["portfolio"]
        ef_max = out["efficient_frontier"]["max_sharpe"]
        ef_min = out["efficient_frontier"]["minimum_variance"]
        self.assertEqual(chosen["objective"], "min_variance")
        self.assertAlmostEqual(chosen["historical_risk_pct"], ef_min["risk_pct"], places=3)
        self.assertNotAlmostEqual(ef_max["risk_pct"], ef_min["risk_pct"], places=4)
        self.assertGreaterEqual(ef_max["sharpe"], chosen["sharpe_ratio"] - 1e-4)


if __name__ == "__main__":
    unittest.main()
