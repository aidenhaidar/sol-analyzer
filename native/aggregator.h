#pragma once
#include <cstdint>

// C ABI consumed by the Python API through ctypes. All arrays are caller-owned.
extern "C" {

// Resamples a series of fine-grained candles into coarser buckets of `step` seconds.
// Inputs are parallel arrays of length n, sorted by time ascending.
// Outputs are written to parallel arrays of capacity `cap`; returns the number of
// buckets written (or the required capacity if cap is too small).
int64_t sa_resample_candles(
    const int64_t* time, const double* open, const double* high, const double* low,
    const double* close, const double* volume, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, double* out_open, double* out_high, double* out_low,
    double* out_close, double* out_volume, int64_t cap);

// Buckets a raw trade feed into per-interval activity metrics.
// `side` is 1 for buy, 0 for sell; `wallet` is an integer id per distinct wallet.
// Trades may be in any order. Returns bucket count (or required capacity).
int64_t sa_bucket_trades(
    const int64_t* time, const uint8_t* side, const double* volume,
    const int64_t* wallet, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, int64_t* out_buys, int64_t* out_sells,
    double* out_buy_volume, double* out_sell_volume, int64_t* out_traders,
    int64_t cap);

// Takes the last value of a level series (e.g. holders) within each bucket.
int64_t sa_bucket_last(
    const int64_t* time, const double* value, int64_t n,
    int64_t step, int64_t from, int64_t to,
    int64_t* out_time, double* out_value, int64_t cap);

// Pearson correlation between two equal-length arrays. Returns NaN if undefined.
double sa_pearson(const double* a, const double* b, int64_t n);

const char* sa_version();
}
