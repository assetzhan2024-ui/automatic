# Validation Report — v10

Validated on the packaged project tree.

## Passed

- Python `compileall`: PASS
- `node --check script/portfolio.js`: PASS
- `node --check script/research.js`: PASS
- Unit tests: 10/10 PASS

## Tested architecture invariants

- default/model horizon is 252 trading days;
- GBM and Bootstrap use buy-and-hold;
- forecast uses the existing Portfolio Snapshot rather than rerunning Markowitz;
- Minimum Variance does not overwrite the Maximum-Sharpe frontier reference;
- missing pairwise correlations are rejected rather than changed to zero;
- more than 12 assets are not rejected by an artificial count cap;
- both risk models return VaR and CVaR;
- Event Study core calculates from synthetic stock/market histories without calling
  the slow fundamentals/news context function.

## UI regression checks

- forecast horizon input removed;
- simulation-count input removed;
- Bootstrap block-size input removed;
- UI still states the fixed Bootstrap mean block length of 21 trading days;
- forecast requests use fixed 252 / 10,000 / 21 values;
- Event Study browser request has a 25-second abort/error path.

## Environment limitation

Live Yahoo/SEC/KASE network calls cannot be verified in this offline validation
environment. The event-study calculation and request flow were validated with
mocked market histories. External live-data availability remains dependent on the
user's internet connection and data providers.
