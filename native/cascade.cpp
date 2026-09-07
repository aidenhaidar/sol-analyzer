// Monte Carlo cascade: a quote-asset shock lowers every holder's USD mark; holders
// whose drawdown exceeds their panic threshold sell with probability equal to their
// classifier churn score. Each sell is routed through a constant-product pool, which
// pushes the token price further down and can trip the next tier of holders.
#include "cascade.h"

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

extern "C" int32_t sa_cascade_simulate(
    const double* balance, const double* churn_prob, const double* panic_threshold, int64_t n,
    const CascadeParams* p, CascadeResult* out, double* hist, int32_t hist_bins) {
    if (!p || !out || n < 0 || p->n_sims <= 0 || p->pool_token_reserve <= 0 || p->pool_quote_reserve <= 0) return -1;

    const double k = p->pool_token_reserve * p->pool_quote_reserve;
    const double p0 = p->pool_quote_reserve / p->pool_token_reserve;  // pre-shock token price in quote
    // A quote shock changes every holder's USD mark by the shock even before anyone sells.
    const double shock = p->quote_shock_pct / 100.0;

    std::vector<double> drained(p->n_sims);
    double impact_sum = 0, sellers_sum = 0, rounds_sum = 0;
    std::vector<char> sold(n);
    std::mt19937_64 rng(p->seed);
    std::uniform_real_distribution<double> u(0.0, 1.0);

    for (int32_t s = 0; s < p->n_sims; ++s) {
        double tok = p->pool_token_reserve, quote = p->pool_quote_reserve;
        std::fill(sold.begin(), sold.end(), 0);
        int64_t sellers = 0;
        int32_t rounds = 0;
        // Small per-simulation jitter on thresholds models heterogeneous nerves.
        std::normal_distribution<double> jitter(0.0, 0.015);
        for (int32_t r = 0; r < p->max_rounds; ++r) {
            const double quote_before = quote;
            const double price = quote / tok;
            // USD-equivalent drawdown = quote shock compounded with in-pool price move.
            const double drawdown = 1.0 - (1.0 + shock) * (price / p0);
            bool any = false;
            for (int64_t i = 0; i < n; ++i) {
                if (sold[i]) continue;
                const double thr = std::max(0.0, panic_threshold[i] + jitter(rng));
                if (drawdown < thr) continue;
                if (u(rng) > churn_prob[i]) { sold[i] = 2; continue; }  // decided to hold; decides once
                // Swap a churn-weighted slice of the bag into the pool (constant product, ignoring fees).
                tok += balance[i] * (0.4 + 0.6 * churn_prob[i]);
                quote = k / tok;
                sold[i] = 1;
                ++sellers;
                any = true;
            }
            ++rounds;
            if (!any) break;
            // Dip buyers absorb part of the round's outflow, restoring some quote and taking tokens out.
            const double absorb = std::clamp(p->absorption, 0.0, 1.0);
            quote += (quote_before - quote) * absorb;
            tok = k / quote;
        }
        const double d = 1.0 - quote / p->pool_quote_reserve;
        drained[s] = d;
        impact_sum += (quote / tok) / p0 - 1.0;
        sellers_sum += static_cast<double>(sellers);
        rounds_sum += rounds;
    }

    std::vector<double> sorted = drained;
    std::sort(sorted.begin(), sorted.end());
    auto pct = [&](double q) { return sorted[std::min<size_t>(sorted.size() - 1, static_cast<size_t>(q * sorted.size()))]; };
    double mean = 0;
    for (double d : drained) mean += d;
    mean /= p->n_sims;

    out->drained_mean = mean;
    out->drained_p50 = pct(0.5);
    out->drained_p90 = pct(0.9);
    out->drained_p99 = pct(0.99);
    out->price_impact_mean = impact_sum / p->n_sims;
    out->sellers_mean = sellers_sum / p->n_sims;
    out->rounds_mean = rounds_sum / p->n_sims;

    if (hist && hist_bins > 0) {
        std::fill(hist, hist + hist_bins, 0.0);
        for (double d : drained) {
            int32_t b = static_cast<int32_t>(std::clamp(d, 0.0, 0.999999) * hist_bins);
            hist[b] += 1.0 / p->n_sims;
        }
    }
    return 0;
}
