/* tslint:disable */
/* eslint-disable */
/**
 * Pearson correlation of two equal-length series. NaN when undefined.
 */
export function pearson(a: Float64Array, b: Float64Array): number;
/**
 * Rolling Pearson correlation over a trailing `window`; NaN until the window fills.
 */
export function rolling_correlation(a: Float64Array, b: Float64Array, window: number): Float64Array;
/**
 * Lag (in bars) at which `|corr(a[t], b[t+lag])|` is maximised.
 */
export function best_lag(a: Float64Array, b: Float64Array, max_lag: number): LagResult;
/**
 * Correlation of `a[t]` with `b[t + lag]` for every lag in `-max_lag..=max_lag`.
 * Returns `2 * max_lag + 1` values, index `i` corresponding to lag `i - max_lag`.
 * A positive best lag means `b` moves *after* `a` (a leads b).
 */
export function cross_correlation(a: Float64Array, b: Float64Array, max_lag: number): Float64Array;
/**
 * Simple moving average; NaN until the window fills.
 */
export function sma(xs: Float64Array, window: number): Float64Array;
/**
 * Rescales a series to `0..=1` (min-max), used to overlay metrics on one axis.
 */
export function normalize(xs: Float64Array): Float64Array;
/**
 * Percentage change bar over bar (first element is 0).
 */
export function pct_change(xs: Float64Array): Float64Array;
/**
 * Result of a lead/lag scan.
 */
export class LagResult {
  private constructor();
  free(): void;
  lag: number;
  correlation: number;
}

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
  readonly memory: WebAssembly.Memory;
  readonly __wbg_get_lagresult_correlation: (a: number) => number;
  readonly __wbg_get_lagresult_lag: (a: number) => number;
  readonly __wbg_lagresult_free: (a: number, b: number) => void;
  readonly __wbg_set_lagresult_correlation: (a: number, b: number) => void;
  readonly __wbg_set_lagresult_lag: (a: number, b: number) => void;
  readonly best_lag: (a: number, b: number, c: number, d: number, e: number) => number;
  readonly cross_correlation: (a: number, b: number, c: number, d: number, e: number) => [number, number];
  readonly normalize: (a: number, b: number) => [number, number];
  readonly pct_change: (a: number, b: number) => [number, number];
  readonly pearson: (a: number, b: number, c: number, d: number) => number;
  readonly rolling_correlation: (a: number, b: number, c: number, d: number, e: number) => [number, number];
  readonly sma: (a: number, b: number, c: number) => [number, number];
  readonly __wbindgen_export_0: WebAssembly.Table;
  readonly __wbindgen_malloc: (a: number, b: number) => number;
  readonly __wbindgen_free: (a: number, b: number, c: number) => void;
  readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;
/**
* Instantiates the given `module`, which can either be bytes or
* a precompiled `WebAssembly.Module`.
*
* @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
*
* @returns {InitOutput}
*/
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
* If `module_or_path` is {RequestInfo} or {URL}, makes a request and
* for everything else, calls `WebAssembly.instantiate` directly.
*
* @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
*
* @returns {Promise<InitOutput>}
*/
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
