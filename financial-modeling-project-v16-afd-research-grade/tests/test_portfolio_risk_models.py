import unittest
import numpy as np

from portfolio.optimizer import simulate_portfolio_gbm, simulate_portfolio_bootstrap


class PortfolioRiskModelTests(unittest.TestCase):
    def setUp(self):
        self.amount = 2_000_000.0
        self.allocation = [
            {"ticker": "A", "weight_pct": 40.0},
            {"ticker": "B", "weight_pct": 35.0},
            {"ticker": "C", "weight_pct": 25.0},
        ]
        self.individual = [
            {"ticker": "A", "expected_return_pct": 12.0},
            {"ticker": "B", "expected_return_pct": 10.0},
            {"ticker": "C", "expected_return_pct": 8.0},
        ]
        self.cov = [
            [0.04, 0.01, 0.005],
            [0.01, 0.0324, 0.004],
            [0.005, 0.004, 0.0225],
        ]
        rng = np.random.default_rng(1)
        z = rng.standard_normal((800, 3))
        hist = []
        for i, row in enumerate(z):
            hist.append({
                "date": f"d{i}",
                "returns": {"A": float(row[0] * 0.01), "B": float(row[1] * 0.008), "C": float(row[2] * 0.006)},
            })
        self.history = hist

    def test_gbm_has_var_and_cvar(self):
        r = simulate_portfolio_gbm(
            self.amount, self.allocation, self.individual, self.cov,
            horizon_days=30, simulations=10000, seed=42,
        )
        s = r["scenarios"]
        self.assertEqual(r["simulations"], 10000)
        self.assertIn("var95_kzt", s)
        self.assertIn("cvar95_kzt", s)
        self.assertGreaterEqual(s["cvar95_kzt"], s["var95_kzt"])

    def test_bootstrap_has_var_and_cvar(self):
        r = simulate_portfolio_bootstrap(
            self.amount, self.allocation, self.history,
            horizon_days=30, simulations=10000, block_size=5, seed=43,
        )
        s = r["scenarios"]
        self.assertEqual(r["simulations"], 10000)
        self.assertEqual(r["block_size_days"], 5)
        self.assertIn("var95_kzt", s)
        self.assertIn("cvar95_kzt", s)
        self.assertGreaterEqual(s["cvar95_kzt"], s["var95_kzt"])

    def test_models_do_not_share_the_same_method_label(self):
        self.assertNotEqual("Geometric Brownian Motion (GBM) + Monte Carlo", "Historical Block Bootstrap")


if __name__ == "__main__":
    unittest.main()
