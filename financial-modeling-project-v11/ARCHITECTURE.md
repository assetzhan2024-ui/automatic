# Financial Research App — current architecture

```text
                    FINANCIAL RESEARCH APP
                             │
          ┌──────────────────┴──────────────────┐
          │                                     │
          ↓                                     ↓
   PORTFOLIO ENGINE                        EVENT STUDY
          │                                     │
          │                                     └→ separate research module
          ↓
     MARKET DATA
          ↓
 Historical prices + historical FX
          ↓
 All foreign prices normalized to USD
          ↓
 Daily returns in USD
          ↓
 Expected returns μ + covariance Σ
          ↓
       MARKOWITZ
          │
          ├─ objective: Maximum Sharpe / Minimum Variance
          ├─ U.S. risk-free rate: automatic 13-week Treasury bill proxy
          └─ concentration mode:
               constrained: 2=60%, 3=45%, 4=35%, 5+=25%
               unconstrained benchmark: 0..100%
          ↓
 ┌─────────────────────────────┐
 │ PORTFOLIO SNAPSHOT          │
 │ tickers                     │
 │ exact weights               │
 │ objective                   │
 │ expected returns            │
 │ covariance                  │
 │ input amount                │
 │ historical returns          │
 │ USD risk-free rate + date   │
 │ concentration policy        │
 └──────────┬──────────────────┘
            │
       FROZEN portfolio
            │
      ┌─────┴─────┐
      ↓           ↓
     GBM       Bootstrap
      │           │
      │           └─ stationary blocks, expected block = 21 trading days
      ↓           ↓
10,000 paths   10,000 paths
      │           │
252 trading   252 trading
    days          days
      │           │
 buy-and-hold  buy-and-hold
      └─────┬─────┘
            ↓
        RISK ENGINE
            ↓
     P05 / P50 / P95
            ↓
        VaR / CVaR
            ↓
      Model Comparison
            ↓
        UI / Excel
```

## Invariants

1. Markowitz runs once per portfolio calculation.
2. GBM, Bootstrap and Excel consume the same immutable snapshot; they never rerun Markowitz.
3. Both risk models use the same exact starting weights, 252-trading-day horizon and buy-and-hold policy.
4. Bootstrap UI block length is fixed at 21 trading days.
5. Missing pairwise history is an error; missing correlation is never silently replaced by zero.
6. Portfolio returns are USD-based. Foreign assets include historical FX effects before μ/Σ are estimated.
7. Maximum-Sharpe uses an automatically refreshed U.S. 13-week Treasury bill yield. The live value is cached; a stale fallback is visibly marked.
8. Event Study is independent of the portfolio risk pipeline and does not alter GBM drift or Markowitz expected returns.
