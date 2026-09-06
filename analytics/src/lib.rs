//! Series analytics that run in the browser via WebAssembly.
//!
//! The client feeds aligned candle closes and metric values (e.g. holder counts)
//! into these functions to quantify how tightly a metric tracks price and whether
//! it leads or lags it.

use wasm_bindgen::prelude::*;

/// Pearson correlation of two equal-length series. NaN when undefined.
#[wasm_bindgen]
pub fn pearson(a: &[f64], b: &[f64]) -> f64 {
    let n = a.len().min(b.len());
    if n < 2 {
        return f64::NAN;
    }
    let (a, b) = (&a[..n], &b[..n]);
    let ma = a.iter().sum::<f64>() / n as f64;
    let mb = b.iter().sum::<f64>() / n as f64;
    let (mut cov, mut va, mut vb) = (0.0, 0.0, 0.0);
    for i in 0..n {
        let da = a[i] - ma;
        let db = b[i] - mb;
        cov += da * db;
        va += da * da;
        vb += db * db;
    }
    if va == 0.0 || vb == 0.0 {
        f64::NAN
    } else {
        cov / (va * vb).sqrt()
    }
}

/// Correlation of `a[t]` with `b[t + lag]` for every lag in `-max_lag..=max_lag`.
/// Returns `2 * max_lag + 1` values, index `i` corresponding to lag `i - max_lag`.
/// A positive best lag means `b` moves *after* `a` (a leads b).
#[wasm_bindgen]
pub fn cross_correlation(a: &[f64], b: &[f64], max_lag: usize) -> Vec<f64> {
    let n = a.len().min(b.len());
    let mut out = Vec::with_capacity(2 * max_lag + 1);
    for k in 0..=(2 * max_lag) {
        let lag = k as i64 - max_lag as i64;
        let r = if lag.unsigned_abs() as usize >= n {
            f64::NAN
        } else if lag >= 0 {
            let l = lag as usize;
            pearson(&a[..n - l], &b[l..n])
        } else {
            let l = (-lag) as usize;
            pearson(&a[l..n], &b[..n - l])
        };
        out.push(r);
    }
    out
}

/// Result of a lead/lag scan.
#[wasm_bindgen]
pub struct LagResult {
    pub lag: i32,
    pub correlation: f64,
}

/// Lag (in bars) at which `|corr(a[t], b[t+lag])|` is maximised.
#[wasm_bindgen]
pub fn best_lag(a: &[f64], b: &[f64], max_lag: usize) -> LagResult {
    let xs = cross_correlation(a, b, max_lag);
    let mut best = LagResult { lag: 0, correlation: f64::NAN };
    for (i, &r) in xs.iter().enumerate() {
        if r.is_nan() {
            continue;
        }
        if best.correlation.is_nan() || r.abs() > best.correlation.abs() {
            best = LagResult { lag: i as i32 - max_lag as i32, correlation: r };
        }
    }
    best
}

/// Rolling Pearson correlation over a trailing `window`; NaN until the window fills.
#[wasm_bindgen]
pub fn rolling_correlation(a: &[f64], b: &[f64], window: usize) -> Vec<f64> {
    let n = a.len().min(b.len());
    let mut out = vec![f64::NAN; n];
    if window < 2 || n < window {
        return out;
    }
    // Running sums for O(n) evaluation.
    let (mut sa, mut sb, mut saa, mut sbb, mut sab) = (0.0, 0.0, 0.0, 0.0, 0.0);
    for i in 0..n {
        sa += a[i];
        sb += b[i];
        saa += a[i] * a[i];
        sbb += b[i] * b[i];
        sab += a[i] * b[i];
        if i >= window {
            let (x, y) = (a[i - window], b[i - window]);
            sa -= x;
            sb -= y;
            saa -= x * x;
            sbb -= y * y;
            sab -= x * y;
        }
        if i + 1 >= window {
            let w = window as f64;
            let cov = sab - sa * sb / w;
            let va = saa - sa * sa / w;
            let vb = sbb - sb * sb / w;
            out[i] = if va <= 0.0 || vb <= 0.0 { f64::NAN } else { cov / (va * vb).sqrt() };
        }
    }
    out
}

/// Percentage change bar over bar (first element is 0).
#[wasm_bindgen]
pub fn pct_change(xs: &[f64]) -> Vec<f64> {
    let mut out = Vec::with_capacity(xs.len());
    for i in 0..xs.len() {
        out.push(if i == 0 || xs[i - 1] == 0.0 { 0.0 } else { (xs[i] - xs[i - 1]) / xs[i - 1] });
    }
    out
}

/// Rescales a series to `0..=1` (min-max), used to overlay metrics on one axis.
#[wasm_bindgen]
pub fn normalize(xs: &[f64]) -> Vec<f64> {
    let finite = xs.iter().copied().filter(|v| v.is_finite());
    let min = finite.clone().fold(f64::INFINITY, f64::min);
    let max = finite.fold(f64::NEG_INFINITY, f64::max);
    if !(max > min) {
        return vec![0.5; xs.len()];
    }
    xs.iter().map(|v| (v - min) / (max - min)).collect()
}

/// Simple moving average; NaN until the window fills.
#[wasm_bindgen]
pub fn sma(xs: &[f64], window: usize) -> Vec<f64> {
    let mut out = vec![f64::NAN; xs.len()];
    if window == 0 {
        return out;
    }
    let mut sum = 0.0;
    for i in 0..xs.len() {
        sum += xs[i];
        if i >= window {
            sum -= xs[i - window];
        }
        if i + 1 >= window {
            out[i] = sum / window as f64;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pearson_basics() {
        assert!((pearson(&[1., 2., 3., 4.], &[2., 4., 6., 8.]) - 1.0).abs() < 1e-12);
        assert!((pearson(&[1., 2., 3., 4.], &[4., 3., 2., 1.]) + 1.0).abs() < 1e-12);
        assert!(pearson(&[1., 1., 1.], &[1., 2., 3.]).is_nan());
        assert!(pearson(&[1.], &[1.]).is_nan());
    }

    #[test]
    fn detects_lag() {
        // b is a copy of a shifted forward by 3 bars, so a leads b: best lag = +3.
        let a: Vec<f64> = (0..200).map(|i| ((i as f64) * 0.3).sin() + ((i as f64) * 0.07).cos()).collect();
        let b: Vec<f64> = (0..200).map(|i| if i >= 3 { a[i - 3] } else { 0.0 }).collect();
        let r = best_lag(&a, &b, 10);
        assert_eq!(r.lag, 3);
        assert!(r.correlation > 0.99);
    }

    #[test]
    fn rolling_matches_pointwise() {
        let a: Vec<f64> = (0..50).map(|i| (i as f64).sqrt()).collect();
        let b: Vec<f64> = (0..50).map(|i| ((i * 7) % 11) as f64).collect();
        let roll = rolling_correlation(&a, &b, 10);
        assert!(roll[8].is_nan());
        for i in 9..50 {
            let expect = pearson(&a[i + 1 - 10..=i], &b[i + 1 - 10..=i]);
            assert!((roll[i] - expect).abs() < 1e-9, "i={i}");
        }
    }

    #[test]
    fn helpers() {
        assert_eq!(normalize(&[2., 4., 6.]), vec![0., 0.5, 1.]);
        assert_eq!(normalize(&[3., 3.]), vec![0.5, 0.5]);
        assert_eq!(pct_change(&[100., 110., 99.]), vec![0., 0.1, -0.1]);
        let s = sma(&[1., 2., 3., 4.], 2);
        assert!(s[0].is_nan());
        assert_eq!(&s[1..], &[1.5, 2.5, 3.5]);
    }
}
