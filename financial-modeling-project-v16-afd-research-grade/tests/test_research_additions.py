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

from research.fundamental_trends import build_fundamental_trends
from research.capm import analyze_capm, _download_country_erp
from research import peers


def hist_from_returns(ticker, start, returns):
    idx = pd.bdate_range(start, periods=len(returns)+1)
    prices = 100*np.cumprod(np.r_[1.0,1.0+np.asarray(returns)])
    return {"ticker":ticker,"dates":[d.strftime('%Y-%m-%d') for d in idx],"closes":prices.tolist()}


class ResearchAdditionTests(unittest.TestCase):
    def test_fundamental_trend_engine_calculates_growth_margins_cash_conversion(self):
        fd={
            "ticker":"TEST",
            "income":{
                "2023":{"Total Revenue":100,"Gross Profit":50,"Operating Income":20,"Net Income":10,"Diluted EPS":1.0},
                "2024":{"Total Revenue":120,"Gross Profit":63,"Operating Income":27,"Net Income":12,"Diluted EPS":1.2},
                "2025":{"Total Revenue":150,"Gross Profit":84,"Operating Income":36,"Net Income":15,"Diluted EPS":1.5},
            },
            "balance":{"2023":{"Total Debt":40},"2024":{"Total Debt":38},"2025":{"Total Debt":35}},
            "cashflow":{
                "2023":{"Operating Cash Flow":12,"Free Cash Flow":8},
                "2024":{"Operating Cash Flow":15,"Free Cash Flow":10},
                "2025":{"Operating Cash Flow":20,"Free Cash Flow":13},
            },
        }
        out=build_fundamental_trends(fd)
        self.assertAlmostEqual(out["metrics"]["revenue"]["latest_yoy_pct"],25.0)
        self.assertAlmostEqual(out["margins"]["operating_margin_pct"]["2025"],24.0)
        self.assertAlmostEqual(out["cash_conversion"]["ocf_to_net_income_pct"]["2025"],133.3333333333,places=5)
        self.assertLess(out["metrics"]["total_debt"]["latest_yoy_pct"],0)

    def test_capm_uses_local_beta_and_country_adjustment_for_kazakhstan(self):
        rng=np.random.default_rng(7)
        m=rng.normal(0.001,0.02,260)
        s=1.4*m+rng.normal(0,0.005,260)
        stock=hist_from_returns("AAA.KZ","2021-01-01",s)
        bench=hist_from_returns("^KZKAK","2021-01-01",m)
        def fake_history(ticker,period="5y"):
            return stock if ticker=="AAA.KZ" else bench
        with patch("research.capm.fetch_history",side_effect=fake_history), \
             patch("research.capm.get_market_risk_free",return_value={"rate_pct":14.0,"as_of":"2026-09-04","source":"KASE","stale":False}), \
             patch("research.capm.get_country_erp",return_value={"total_erp_pct":10.0,"country_risk_premium_pct":4.0,"default_spread_pct":2.0,"as_of":"2026-07-01","source":"test","stale":False}):
            out=analyze_capm("AAA.KZ",market="Kazakhstan")
        self.assertEqual(out["method"],"country_risk_consistent_local_capm")
        self.assertIsNotNone(out["beta"])
        expected=(14.0-2.0)+out["beta"]*6.0+4.0
        self.assertAlmostEqual(out["required_return_pct"],expected,places=3)
        self.assertAlmostEqual(out["risk_free"]["rate_pct"],12.0,places=6)
        self.assertAlmostEqual(out["risk_free"]["sovereign_yield_pct"],14.0,places=6)
        self.assertTrue(out["beta_history"])

    def test_kazakhstan_capm_refuses_to_double_count_without_default_spread(self):
        rng=np.random.default_rng(9)
        m=rng.normal(0.001,0.02,260)
        s=1.1*m+rng.normal(0,0.005,260)
        stock=hist_from_returns("AAA.KZ","2021-01-01",s)
        bench=hist_from_returns("^KZKAK","2021-01-01",m)
        with patch("research.capm.fetch_history",side_effect=lambda ticker,period="5y": stock if ticker=="AAA.KZ" else bench), \
             patch("research.capm.get_market_risk_free",return_value={"rate_pct":14.0,"as_of":"2026-09-04","source":"KASE","stale":False}), \
             patch("research.capm.get_country_erp",return_value={"total_erp_pct":10.0,"country_risk_premium_pct":4.0,"default_spread_pct":None,"as_of":"2026-07-01","source":"test","stale":False}):
            out=analyze_capm("AAA.KZ",market="Kazakhstan")
        self.assertIsNone(out["required_return_pct"])
        self.assertIsNone(out["risk_free"]["rate_pct"])



    def test_damodaran_parser_reads_default_spread_crp_and_erp(self):
        from io import BytesIO
        df=pd.DataFrame({
            "Country":["Kazakhstan","Australia"],
            "Adj. Default Spread":[0.025,0.0],
            "Country Risk Premium":[0.038,0.0],
            "Equity Risk Premium":[0.081,0.043],
        })
        bio=BytesIO()
        with pd.ExcelWriter(bio,engine="openpyxl") as writer:
            df.to_excel(writer,index=False,sheet_name="Country Risk Premiums")
        raw=bio.getvalue()
        with patch("research.capm._http_bytes",return_value=raw):
            rows=_download_country_erp()
        kz=rows["kazakhstan"]
        self.assertAlmostEqual(kz["default_spread_pct"],2.5,places=6)
        self.assertAlmostEqual(kz["country_risk_premium_pct"],3.8,places=6)
        self.assertAlmostEqual(kz["total_erp_pct"],8.1,places=6)

    def test_france_uses_eur_and_local_event_benchmark(self):
        from portfolio.historical_validation import _currency_for_ticker
        from portfolio.event_study import benchmark_for_market
        self.assertEqual(_currency_for_ticker("MC.PA"), "EUR")
        self.assertEqual(benchmark_for_market("France"), "^FCHI")

    def test_peer_scoring_rewards_same_industry_market_and_similar_cap(self):
        target={"industry":"Software—Infrastructure","sector":"Technology","market":"US","region":"US","market_cap":100.0}
        good={"industry":"Software—Infrastructure","sector":"Technology","market":"US","region":"US","market_cap":120.0,"price":1,"pe_ratio":20,"ev_ebitda":10,"roe_pct":15,"fcf":5,"net_income":4,"total_debt":2}
        weak={"industry":"Oil & Gas","sector":"Energy","market":"US","region":"US","market_cap":900.0,"price":1,"pe_ratio":20,"ev_ebitda":10,"roe_pct":15,"fcf":5,"net_income":4,"total_debt":2}
        a,_=peers._score_peer(target,good)
        b,_=peers._score_peer(target,weak)
        self.assertGreater(a,b)


if __name__ == "__main__":
    unittest.main()
