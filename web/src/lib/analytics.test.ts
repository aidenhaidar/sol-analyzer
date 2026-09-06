import { describe, expect, it } from 'vitest';
import { alignSeries, jsAnalytics as A } from './analytics';

describe('analytics fallback', () => {
  it('pearson', () => {
    expect(A.pearson(Float64Array.of(1, 2, 3, 4), Float64Array.of(2, 4, 6, 8))).toBeCloseTo(1);
    expect(A.pearson(Float64Array.of(1, 2, 3, 4), Float64Array.of(4, 3, 2, 1))).toBeCloseTo(-1);
    expect(A.pearson(Float64Array.of(1, 1, 1), Float64Array.of(1, 2, 3))).toBeNaN();
  });

  it('finds the lag at which a metric follows price', () => {
    const a = Float64Array.from({ length: 200 }, (_, i) => Math.sin(i * 0.3) + Math.cos(i * 0.07));
    const b = Float64Array.from({ length: 200 }, (_, i) => (i >= 3 ? a[i - 3] : 0));
    const r = A.bestLag(a, b, 10);
    expect(r.lag).toBe(3);
    expect(r.correlation).toBeGreaterThan(0.99);
  });

  it('rolling correlation matches pointwise', () => {
    const a = Float64Array.from({ length: 50 }, (_, i) => Math.sqrt(i));
    const b = Float64Array.from({ length: 50 }, (_, i) => (i * 7) % 11);
    const roll = A.rollingCorrelation(a, b, 10);
    expect(roll[8]).toBeNaN();
    for (let i = 9; i < 50; i++) expect(roll[i]).toBeCloseTo(A.pearson(a.subarray(i - 9, i + 1), b.subarray(i - 9, i + 1)), 9);
  });

  it('aligns on shared bucket times', () => {
    const candles = [1, 2, 3].map((t) => ({ time: t, open: 0, high: 0, low: 0, close: t * 10, volume: 0 }));
    const r = alignSeries(candles, [{ time: 1, value: 5 }, { time: 3, value: 7 }]);
    expect(r.times).toEqual([1, 3]);
    expect(Array.from(r.closes)).toEqual([10, 30]);
    expect(Array.from(r.values)).toEqual([5, 7]);
  });
});
