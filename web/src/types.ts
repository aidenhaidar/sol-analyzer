/** Types shared by the API server and the client. */

export type Interval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

export const INTERVALS: Interval[] = ['1m', '5m', '15m', '1h', '4h', '1d'];

export const INTERVAL_SECONDS: Record<Interval, number> = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '1h': 3600,
  '4h': 14400,
  '1d': 86400,
};

/** Which candlestick series is drawn in the primary pane. */
export type CandleMode = 'price' | 'marketCap';

/** Secondary metrics the user can overlay against the candles. */
export type MetricKey =
  | 'holders'
  | 'volume'
  | 'buyVolume'
  | 'sellVolume'
  | 'txns'
  | 'buys'
  | 'sells'
  | 'traders'
  | 'liquidity';

export interface MetricMeta {
  key: MetricKey;
  label: string;
  /** Preferred visual form. */
  kind: 'line' | 'histogram';
  /** Cumulative metrics (holders) are drawn as a level; flow metrics are per-candle totals. */
  cumulative: boolean;
  color: string;
  unit: 'count' | 'usd';
}

export const METRICS: MetricMeta[] = [
  { key: 'holders', label: 'Holders', kind: 'line', cumulative: true, color: '#f7b731', unit: 'count' },
  { key: 'volume', label: 'Volume', kind: 'histogram', cumulative: false, color: '#5b8def', unit: 'usd' },
  { key: 'buyVolume', label: 'Buy volume', kind: 'histogram', cumulative: false, color: '#22c55e', unit: 'usd' },
  { key: 'sellVolume', label: 'Sell volume', kind: 'histogram', cumulative: false, color: '#ef4444', unit: 'usd' },
  { key: 'txns', label: 'Transactions', kind: 'line', cumulative: false, color: '#a78bfa', unit: 'count' },
  { key: 'buys', label: 'Buys', kind: 'line', cumulative: false, color: '#34d399', unit: 'count' },
  { key: 'sells', label: 'Sells', kind: 'line', cumulative: false, color: '#fb7185', unit: 'count' },
  { key: 'traders', label: 'Unique traders', kind: 'line', cumulative: false, color: '#38bdf8', unit: 'count' },
  { key: 'liquidity', label: 'Liquidity', kind: 'line', cumulative: true, color: '#e879f9', unit: 'usd' },
];

export const METRIC_BY_KEY: Record<MetricKey, MetricMeta> = Object.fromEntries(
  METRICS.map((m) => [m.key, m]),
) as Record<MetricKey, MetricMeta>;

export interface Candle {
  /** Unix seconds, bucket open. */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** USD volume in the bucket. */
  volume: number;
}

export interface Point {
  time: number;
  value: number;
}

export interface TokenInfo {
  mint: string;
  name: string;
  symbol: string;
  image?: string;
  priceUsd: number;
  marketCap: number;
  liquidityUsd: number;
  holders?: number;
  supply?: number;
  /** Where the data came from. */
  source: 'mock' | 'solanatracker' | 'dexscreener';
}

export interface SearchResult {
  mint: string;
  name: string;
  symbol: string;
  image?: string;
  marketCap?: number;
  priceUsd?: number;
  liquidityUsd?: number;
}

export interface ChartResponse {
  mint: string;
  interval: Interval;
  mode: CandleMode;
  candles: Candle[];
  source: TokenInfo['source'];
}

export interface MetricResponse {
  mint: string;
  interval: Interval;
  metric: MetricKey;
  points: Point[];
  source: TokenInfo['source'];
  /** Set when the provider cannot supply the metric and it was approximated. */
  approximated?: boolean;
}

// ------------------------------------------------------------ predictive engine

export type RiskTier = 'stable' | 'watch' | 'elevated' | 'critical';

export interface HolderRisk {
  wallet: string;
  churn_probability: number;
  z_score: number;
  tier: RiskTier;
  token_balance: number;
  features: Record<string, number>;
  archetype: string | null;
}

export interface TokenRisk {
  mint: string;
  model: string;
  collector: 'rpc' | 'mock';
  holders: HolderRisk[];
  sampled_holders: number;
  mean_probability: number;
  std_probability: number;
  supply_at_risk_pct: number;
  tier_counts: Record<RiskTier, number>;
  risk_score: number;
  feature_importance: Record<string, number>;
  generated_at: number;
}

export interface CascadeReport {
  mint: string;
  quote_shock_pct: number;
  drained_mean: number;
  drained_p50: number;
  drained_p90: number;
  drained_p99: number;
  price_impact_mean: number;
  sellers_mean: number;
  rounds_mean: number;
  histogram: number[];
  n_sims: number;
  absorption: number;
  narrative: string;
  sampled_holders: number;
  sol_price: number;
}

export const TIER_COLORS: Record<RiskTier, string> = {
  stable: '#22c55e',
  watch: '#f7b731',
  elevated: '#fb923c',
  critical: '#ef4444',
};

// ------------------------------------------------------------------ live stream

export interface HolderChange {
  owner: string;
  before: number;
  after: number;
}

export interface SlotDelta {
  mint: string;
  slot: number;
  ts_ms: number;
  holders: number;
  holder_delta: number;
  new_holders: number;
  exited_holders: number;
  buys: number;
  sells: number;
  buy_amount: number;
  sell_amount: number;
  buy_lamports: number;
  sell_lamports: number;
  traders: number;
  price_lamports_per_token: number | null;
  imbalance: number;
  top_changes: HolderChange[];
}

export interface LiveSnapshot {
  mint: string;
  slot: number;
  holders: number;
  total_held: number;
  price_lamports_per_token: number | null;
  top_holders: [string, number][];
  history: SlotDelta[];
}
