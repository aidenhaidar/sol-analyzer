/**
 * Series analytics. Uses the Rust WebAssembly build (analytics/ -> src/wasm) when it
 * loads, and an equivalent TypeScript implementation otherwise.
 */
import type { Candle, Point } from '../types';

export interface Analytics {
  backend: 'wasm' | 'js';
  pearson(a: Float64Array, b: Float64Array): number;
  crossCorrelation(a: Float64Array, b: Float64Array, maxLag: number): Float64Array;
  bestLag(a: Float64Array, b: Float64Array, maxLag: number): { lag: number; correlation: number };
  rollingCorrelation(a: Float64Array, b: Float64Array, window: number): Float64Array;
  normalize(xs: Float64Array): Float64Array;
}

// ---------------------------------------------------------------- TypeScript fallback

function pearsonJs(a: Float64Array, b: Float64Array): number {
  const n = Math.min(a.length, b.length);
  if (n < 2) return NaN;
  let ma = 0, mb = 0;
  for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
  ma /= n; mb /= n;
  let cov = 0, va = 0, vb = 0;
  for (let i = 0; i < n; i++) {
    const da = a[i] - ma, db = b[i] - mb;
    cov += da * db; va += da * da; vb += db * db;
  }
  return va === 0 || vb === 0 ? NaN : cov / Math.sqrt(va * vb);
}

function crossCorrelationJs(a: Float64Array, b: Float64Array, maxLag: number): Float64Array {
  const n = Math.min(a.length, b.length);
  const out = new Float64Array(2 * maxLag + 1);
  for (let k = 0; k <= 2 * maxLag; k++) {
    const lag = k - maxLag;
    if (Math.abs(lag) >= n) { out[k] = NaN; continue; }
    out[k] = lag >= 0
      ? pearsonJs(a.subarray(0, n - lag), b.subarray(lag, n))
      : pearsonJs(a.subarray(-lag, n), b.subarray(0, n + lag));
  }
  return out;
}

function bestLagJs(a: Float64Array, b: Float64Array, maxLag: number) {
  const xs = crossCorrelationJs(a, b, maxLag);
  let best = { lag: 0, correlation: NaN };
  xs.forEach((r, i) => {
    if (Number.isNaN(r)) return;
    if (Number.isNaN(best.correlation) || Math.abs(r) > Math.abs(best.correlation)) best = { lag: i - maxLag, correlation: r };
  });
  return best;
}

function rollingCorrelationJs(a: Float64Array, b: Float64Array, window: number): Float64Array {
  const n = Math.min(a.length, b.length);
  const out = new Float64Array(n).fill(NaN);
  if (window < 2 || n < window) return out;
  let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0;
  for (let i = 0; i < n; i++) {
    sa += a[i]; sb += b[i]; saa += a[i] * a[i]; sbb += b[i] * b[i]; sab += a[i] * b[i];
    if (i >= window) {
      const x = a[i - window], y = b[i - window];
      sa -= x; sb -= y; saa -= x * x; sbb -= y * y; sab -= x * y;
    }
    if (i + 1 >= window) {
      const cov = sab - (sa * sb) / window;
      const va = saa - (sa * sa) / window;
      const vb = sbb - (sb * sb) / window;
      out[i] = va <= 0 || vb <= 0 ? NaN : cov / Math.sqrt(va * vb);
    }
  }
  return out;
}

function normalizeJs(xs: Float64Array): Float64Array {
  let min = Infinity, max = -Infinity;
  for (const v of xs) if (Number.isFinite(v)) { min = Math.min(min, v); max = Math.max(max, v); }
  if (!(max > min)) return new Float64Array(xs.length).fill(0.5);
  return xs.map((v) => (v - min) / (max - min));
}

export const jsAnalytics: Analytics = {
  backend: 'js',
  pearson: pearsonJs,
  crossCorrelation: crossCorrelationJs,
  bestLag: bestLagJs,
  rollingCorrelation: rollingCorrelationJs,
  normalize: normalizeJs,
};

// -------------------------------------------------------------------- WASM loader

let loaded: Promise<Analytics> | null = null;

export function loadAnalytics(): Promise<Analytics> {
  if (!loaded) {
    loaded = (async () => {
      try {
        const mod = await import('../wasm/sol_analytics.js');
        const wasmUrl = (await import('../wasm/sol_analytics_bg.wasm?url')).default;
        await mod.default({ module_or_path: wasmUrl });
        return {
          backend: 'wasm',
          pearson: mod.pearson,
          crossCorrelation: mod.cross_correlation,
          bestLag: (a, b, maxLag) => {
            const r = mod.best_lag(a, b, maxLag);
            const out = { lag: r.lag, correlation: r.correlation };
            r.free();
            return out;
          },
          rollingCorrelation: mod.rolling_correlation,
          normalize: mod.normalize,
        } satisfies Analytics;
      } catch (err) {
        console.warn('wasm analytics unavailable, using TypeScript fallback', err);
        return jsAnalytics;
      }
    })();
  }
  return loaded;
}

// ------------------------------------------------------------------ alignment

/** Pairs candle closes with metric values on matching bucket times. */
export function alignSeries(candles: Candle[], points: Point[]): { closes: Float64Array; values: Float64Array; times: number[] } {
  const byTime = new Map(points.map((p) => [p.time, p.value]));
  const times: number[] = [];
  const closes: number[] = [];
  const values: number[] = [];
  for (const c of candles) {
    const v = byTime.get(c.time);
    if (v === undefined) continue;
    times.push(c.time);
    closes.push(c.close);
    values.push(v);
  }
  return { closes: Float64Array.from(closes), values: Float64Array.from(values), times };
}
