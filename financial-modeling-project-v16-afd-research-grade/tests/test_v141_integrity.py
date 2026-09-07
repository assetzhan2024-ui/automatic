import sys, types, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd

if "yfinance" not in sys.modules:
    yf = types.ModuleType("yfinance")
    class _DummyTicker:
        def __init__(self, *a, **k): pass
    yf.Ticker = _DummyTicker
    sys.modules["yfinance"] = yf

from portfolio.optimizer import summarize_terminal_distribution, _loss_tail_metrics
from portfolio.historical_validation import _forecast_only_summary
from fetcher.chart import _clean_history_close, _clean_pairs
from fetcher.official_events import sec_event_candidates

ROOT = Path(__file__).resolve().parents[1]

class V141IntegrityTests(unittest.TestCase):
    def test_hmv_var_cvar_uses_same_canonical_tail_math(self):
        terminal = np.array([40, 60, 80, 90, 95, 100, 105, 110, 120, 150], dtype=float)
        start = 100.0
        canonical = summarize_terminal_distribution(terminal, start)
        raw = _loss_tail_metrics(terminal, start)
        hmv = _forecast_only_summary({"scenarios": {"var95_kzt": 999999, "cvar95_kzt": 999999}}, terminal, start)
        self.assertAlmostEqual(hmv["var95_loss_usd"], canonical["var95"], places=2)
        self.assertAlmostEqual(hmv["cvar95_loss_usd"], canonical["cvar95"], places=2)
        self.assertAlmostEqual(canonical["var95"], raw["var95_kzt"], places=10)
        self.assertAlmostEqual(canonical["cvar95"], raw["cvar95_kzt"], places=10)
        self.assertAlmostEqual(hmv["var95_portfolio_value_usd"], start - hmv["var95_loss_usd"], places=2)
        self.assertAlmostEqual(hmv["cvar95_portfolio_value_usd"], start - hmv["cvar95_loss_usd"], places=2)

    def test_chart_cleaner_removes_zero_nan_inf_terminal_points(self):
        idx = pd.to_datetime(["2026-08-25","2026-08-26","2026-08-27","2026-08-28"])
        hist = pd.DataFrame({"Close":[100.0, np.nan, 0.0, 108.0]}, index=idx)
        clean = _clean_history_close(hist)
        self.assertEqual(clean.tolist(), [100.0, 108.0])
        pairs = _clean_pairs(["2026-08-25","2026-08-26","2026-08-27"],[100,None,0])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][1], 100.0)

    def test_sec_labels_are_distinguishable_and_deduplicated(self):
        tickers = {"KSPI":{"cik":"0000001234","name":"Kaspi"}}
        recent = {
            "filings":{"recent":{
                "form":["6-K","6-K","20-F"],
                "filingDate":["2026-08-20","2026-08-20","2026-04-01"],
                "accessionNumber":["a","a2","b"],
                "primaryDocument":["a.htm","a2.htm","b.htm"],
                "reportDate":["2026-06-30","2026-06-30","2025-12-31"],
            }}
        }
        with patch("fetcher.official_events._load_sec_tickers", return_value=tickers), patch("fetcher.official_events._http_json", return_value=recent):
            rows = sec_event_candidates("KSPI", limit=8)
        self.assertEqual(len(rows), 2)  # same date/form/report period deduped
        labels = [r["label"] for r in rows]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all("2026-" in x for x in labels))

    def test_ui_removes_manual_date_p_ar_p_car_and_portfolio_inline_event(self):
        research = (ROOT/"script/research.js").read_text(encoding="utf-8")
        portfolio = (ROOT/"script/portfolio.js").read_text(encoding="utf-8")
        self.assertNotIn("Дата вручную", research)
        self.assertNotIn("event-manual-date", research)
        self.assertNotIn("<th>p AR</th>", research)
        self.assertNotIn("<th>p CAR</th>", research)
        self.assertNotIn("event-inline-callout", portfolio)
        self.assertNotIn('onclick="openEventStudy()"', portfolio)

    def test_hmv_ui_auto_extends_completed_years_and_keeps_spaced_money_input(self):
        js=(ROOT/"script/historical_validation.js").read_text(encoding="utf-8")
        self.assertIn("const HVAL_FIRST_YEAR = 2017", js)
        self.assertIn("new Date().getFullYear() - 1", js)
        self.assertIn("HVAL_YEARS.map", js)
        self.assertIn("hvalFormatMoneyInput", js)
        self.assertIn("toLocaleString('ru-RU')", js)

if __name__ == "__main__":
    unittest.main()
