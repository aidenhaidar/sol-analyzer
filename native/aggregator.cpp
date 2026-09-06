// High-throughput resampling of candles and trade feeds for the sol-analyzer API.
// Trade feeds for a busy token can run to hundreds of thousands of rows per day,
// so bucketing lives here rather than in Python.
#include "aggregator.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <unordered_set>
#include <vector>

namespace {

inline int64_t bucket_of(int64_t t, int64_t step) {
    // Floor division that behaves for negative timestamps too.
    return (t >= 0 ? t / step : -((-t + step - 1) / step)) * step;
}

}  // namespace

extern "C" {

int64_t sa_resample_candles(
    const int64_t* time, const double* open, const double* high, const double* low,
    const double* close, const double* volume, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, double* out_open, double* out_high, double* out_low,
    double* out_close, double* out_volume, int64_t cap) {
    if (step <= 0) return 0;
    int64_t count = 0;
    int64_t current = INT64_MIN;
    for (int64_t i = 0; i < n; ++i) {
        const int64_t t = time[i];
        if (t < from || t > to) continue;
        const int64_t b = bucket_of(t, step);
        if (b != current) {
            current = b;
            if (count < cap) {
                out_time[count] = b;
                out_open[count] = open[i];
                out_high[count] = high[i];
                out_low[count] = low[i];
                out_close[count] = close[i];
                out_volume[count] = volume[i];
            }
            ++count;
        } else if (count - 1 < cap) {
            const int64_t k = count - 1;
            out_high[k] = std::max(out_high[k], high[i]);
            out_low[k] = std::min(out_low[k], low[i]);
            out_close[k] = close[i];
            out_volume[k] += volume[i];
        }
    }
    return count;
}

int64_t sa_bucket_trades(
    const int64_t* time, const uint8_t* side, const double* volume,
    const int64_t* wallet, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, int64_t* out_buys, int64_t* out_sells,
    double* out_buy_volume, double* out_sell_volume, int64_t* out_traders,
    int64_t cap) {
    if (step <= 0) return 0;
    struct Acc {
        int64_t buys = 0, sells = 0;
        double buy_volume = 0, sell_volume = 0;
        std::unordered_set<int64_t> wallets;
    };
    std::map<int64_t, Acc> buckets;  // ordered by bucket time
    for (int64_t i = 0; i < n; ++i) {
        const int64_t t = time[i];
        if (t < from || t > to) continue;
        Acc& a = buckets[bucket_of(t, step)];
        if (side[i]) {
            ++a.buys;
            a.buy_volume += volume[i];
        } else {
            ++a.sells;
            a.sell_volume += volume[i];
        }
        a.wallets.insert(wallet[i]);
    }
    int64_t k = 0;
    for (const auto& [bt, a] : buckets) {
        if (k < cap) {
            out_time[k] = bt;
            out_buys[k] = a.buys;
            out_sells[k] = a.sells;
            out_buy_volume[k] = a.buy_volume;
            out_sell_volume[k] = a.sell_volume;
            out_traders[k] = static_cast<int64_t>(a.wallets.size());
        }
        ++k;
    }
    return k;
}

int64_t sa_bucket_last(
    const int64_t* time, const double* value, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, double* out_value, int64_t cap) {
    if (step <= 0) return 0;
    std::map<int64_t, std::pair<int64_t, double>> last;  // bucket -> (time, value)
    for (int64_t i = 0; i < n; ++i) {
        const int64_t t = time[i];
        if (t < from || t > to) continue;
        auto& slot = last[bucket_of(t, step)];
        if (slot.first == 0 || t >= slot.first) slot = {t, value[i]};
    }
    int64_t k = 0;
    for (const auto& [bt, tv] : last) {
        if (k < cap) {
            out_time[k] = bt;
            out_value[k] = tv.second;
        }
        ++k;
    }
    return k;
}

double sa_pearson(const double* a, const double* b, int64_t n) {
    if (n < 2) return NAN;
    double ma = 0, mb = 0;
    for (int64_t i = 0; i < n; ++i) { ma += a[i]; mb += b[i]; }
    ma /= static_cast<double>(n);
    mb /= static_cast<double>(n);
    double cov = 0, va = 0, vb = 0;
    for (int64_t i = 0; i < n; ++i) {
        const double da = a[i] - ma, db = b[i] - mb;
        cov += da * db;
        va += da * da;
        vb += db * db;
    }
    if (va == 0 || vb == 0) return NAN;
    return cov / std::sqrt(va * vb);
}

const char* sa_version() { return "sol-analyzer native 0.1.0"; }

}  // extern "C"
