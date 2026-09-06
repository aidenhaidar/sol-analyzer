#include "aggregator.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>

int main() {
    // Resample 6 one-minute candles into 5-minute buckets.
    std::vector<int64_t> t = {0, 60, 120, 180, 240, 300};
    std::vector<double> o = {1, 2, 3, 4, 5, 6}, h = {2, 3, 4, 5, 9, 7}, l = {0.5, 1, 2, 3, 4, 5},
                        c = {2, 3, 4, 5, 6, 7}, v = {1, 1, 1, 1, 1, 10};
    int64_t ot[4]; double oo[4], oh[4], ol[4], oc[4], ov[4];
    int64_t n = sa_resample_candles(t.data(), o.data(), h.data(), l.data(), c.data(), v.data(), 6, 300, 0, 1000,
                                    ot, oo, oh, ol, oc, ov, 4);
    assert(n == 2);
    assert(ot[0] == 0 && oo[0] == 1 && oh[0] == 9 && ol[0] == 0.5 && oc[0] == 6 && ov[0] == 5);
    assert(ot[1] == 300 && ov[1] == 10);

    // Bucket trades: 3 trades in bucket 0 from 2 wallets, 1 trade in bucket 300.
    std::vector<int64_t> tt = {10, 20, 30, 310};
    std::vector<uint8_t> side = {1, 0, 1, 1};
    std::vector<double> vol = {100, 50, 25, 5};
    std::vector<int64_t> w = {1, 1, 2, 3};
    int64_t bt[4], buys[4], sells[4], traders[4]; double bv[4], sv[4];
    n = sa_bucket_trades(tt.data(), side.data(), vol.data(), w.data(), 4, 300, 0, 1000, bt, buys, sells, bv, sv, traders, 4);
    assert(n == 2);
    assert(buys[0] == 2 && sells[0] == 1 && bv[0] == 125 && sv[0] == 50 && traders[0] == 2);
    assert(bt[1] == 300 && buys[1] == 1 && traders[1] == 1);

    // Capacity probing returns the required size without writing past cap.
    assert(sa_bucket_trades(tt.data(), side.data(), vol.data(), w.data(), 4, 300, 0, 1000, bt, buys, sells, bv, sv, traders, 0) == 2);

    double a[] = {1, 2, 3, 4}, b[] = {2, 4, 6, 8}, cc[] = {4, 3, 2, 1};
    assert(std::fabs(sa_pearson(a, b, 4) - 1.0) < 1e-12);
    assert(std::fabs(sa_pearson(a, cc, 4) + 1.0) < 1e-12);
    assert(std::isnan(sa_pearson(a, b, 1)));

    std::puts("native tests passed");
    return 0;
}
