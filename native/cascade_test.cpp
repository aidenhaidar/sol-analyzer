#include "cascade.h"
#include <cassert>
#include <cstdio>
#include <vector>

int main() {
    // 100 holders, half paper hands (high churn, low threshold), half diamond hands.
    std::vector<double> bal(100, 10'000), churn(100), thr(100);
    for (int i = 0; i < 100; ++i) { churn[i] = i < 50 ? 0.9 : 0.05; thr[i] = i < 50 ? 0.05 : 0.6; }
    CascadeParams p{5'000'000, 1'000, -15, 2000, 8, 0.3, 42};
    CascadeResult r{};
    double hist[10];
    assert(sa_cascade_simulate(bal.data(), churn.data(), thr.data(), 100, &p, &r, hist, 10) == 0);
    assert(r.drained_mean > 0.05 && r.drained_mean < 0.5);
    assert(r.drained_p50 <= r.drained_p90 && r.drained_p90 <= r.drained_p99);
    assert(r.sellers_mean > 30 && r.sellers_mean < 60);   // mostly the paper hands
    assert(r.price_impact_mean < 0);
    double total = 0; for (double h : hist) total += h;
    assert(total > 0.999 && total < 1.001);

    // No shock, high thresholds -> nothing happens.
    CascadeParams calm{5'000'000, 1'000, 0, 500, 8, 0.3, 1};
    std::vector<double> hi(100, 0.5);
    assert(sa_cascade_simulate(bal.data(), churn.data(), hi.data(), 100, &calm, &r, nullptr, 0) == 0);
    assert(r.drained_mean == 0 && r.sellers_mean == 0);

    // Determinism.
    CascadeResult a{}, b{};
    sa_cascade_simulate(bal.data(), churn.data(), thr.data(), 100, &p, &a, nullptr, 0);
    sa_cascade_simulate(bal.data(), churn.data(), thr.data(), 100, &p, &b, nullptr, 0);
    assert(a.drained_mean == b.drained_mean);

    // More absorption means less net drain.
    CascadeParams wet = p; wet.absorption = 0.8;
    CascadeResult dry{}, damp{};
    sa_cascade_simulate(bal.data(), churn.data(), thr.data(), 100, &p, &dry, nullptr, 0);
    sa_cascade_simulate(bal.data(), churn.data(), thr.data(), 100, &wet, &damp, nullptr, 0);
    assert(damp.drained_mean < dry.drained_mean);

    std::puts("cascade tests passed");
    return 0;
}
