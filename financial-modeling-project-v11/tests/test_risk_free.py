import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fetcher.risk_free as rf


class RiskFreeTests(unittest.TestCase):
    def test_seed_fallback_is_automatic_and_dated(self):
        with tempfile.TemporaryDirectory() as td, patch.object(rf, "yf", None), patch.object(rf, "_CACHE_FILE", Path(td) / "rf.json"):
            out = rf.get_usd_risk_free_rate(force_refresh=True)
        self.assertGreater(float(out["rate_pct"]), 0.0)
        self.assertEqual(out["instrument"], "13-week U.S. Treasury bill")
        self.assertTrue(out["as_of"])
        self.assertTrue(out["stale"])


if __name__ == "__main__":
    unittest.main()
