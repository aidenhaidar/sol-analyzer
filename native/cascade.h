#pragma once
#include <cstdint>

// Monte Carlo liquidity-cascade simulation over a constant-product pool.
extern "C" {

struct CascadeParams {
    double pool_token_reserve;   // tokens in the pool
    double pool_quote_reserve;   // quote (SOL) in the pool
    double quote_shock_pct;      // e.g. -15 for a 15% SOL drop
    int32_t n_sims;
    int32_t max_rounds;          // cascade rounds per simulation
    double absorption;           // fraction of each round's outflow bought back by dip buyers (0..1)
    uint64_t seed;
};

struct CascadeResult {
    double drained_mean;         // mean fraction of quote reserve removed (0..1)
    double drained_p50;
    double drained_p90;
    double drained_p99;
    double price_impact_mean;    // mean fractional token price change vs. pre-shock, in quote terms
    double sellers_mean;         // mean number of holders who sold
    double rounds_mean;          // mean cascade depth
};

// holders: parallel arrays of length n.
//   balance          tokens held
//   churn_prob       classifier probability of dumping (0..1); also sets the slice sold (40%..100%)
//   panic_threshold  fractional drawdown (0..1) at which the holder considers selling
// Writes `hist` (length hist_bins) with a histogram of drained fraction over sims.
// Returns 0 on success.
int32_t sa_cascade_simulate(
    const double* balance, const double* churn_prob, const double* panic_threshold, int64_t n,
    const CascadeParams* params, CascadeResult* out, double* hist, int32_t hist_bins);
}
