# Architecture and code audit — v11

## Verdict

The core architecture is internally consistent after the v11 changes. Markowitz is the only allocation engine; GBM and Bootstrap are downstream scenario engines; VaR/CVaR are risk outputs. Event Study remains a separate research module.

## Fixed in v11

- Removed manual risk-free-rate input from UI.
- Added automatic USD risk-free proxy: 13-week U.S. Treasury bill (`^IRX` live), with timestamped cache and stale fallback.
- Standardized portfolio return measurement to USD before Markowitz by including historical FX effects for non-USD assets.
- Added constrained Markowitz policy: 2 assets 60%, 3 45%, 4 35%, 5+ 25%; retained unconstrained long-only benchmark.
- Snapshot stores the chosen concentration policy and USD risk-free rate metadata.
- Kept 252 trading days, 10,000 paths, buy-and-hold and Bootstrap expected block length 21.
- Preserved strict pairwise-history validation; NaN correlation is never treated as zero.

## Remaining model limitations (not code bugs)

1. Expected equity returns still use historical arithmetic means; this is estimation-sensitive and is the next major research weakness.
2. Covariance is historical/static; it does not yet model regime-dependent correlation or stochastic volatility.
3. Bond returns use a duration/carry proxy when traded daily prices are unavailable; corporate-spread dynamics are simplified.
4. The U.S. risk-free proxy is a short Treasury-bill rate. This is a defensible Sharpe baseline for a USD-based project, but horizon-matched term-structure modeling is a future enhancement.
5. Absolute scenario values are displayed against the user-entered KZT amount, while portfolio return dynamics are USD-based. This is a display scaling convention, not a KZT FX forecast. A future currency-reporting layer can show both USD terminal wealth and live KZT equivalents explicitly.

## No incompatibility found between

- Markowitz and GBM: Markowitz supplies weights/μ/Σ; GBM simulates those frozen positions.
- Markowitz and Bootstrap: Markowitz supplies weights; Bootstrap resamples the same USD historical return matrix.
- GBM and Bootstrap: they intentionally produce different distributions but share horizon, weights and rebalancing policy.
- Event Study and Portfolio Engine: they answer different research questions and are intentionally independent.
