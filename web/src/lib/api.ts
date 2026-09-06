import type { CandleMode, ChartResponse, Interval, MetricKey, MetricResponse, SearchResult, TokenInfo } from '../types';

export interface Status {
  provider: TokenInfo['source'];
  demo: boolean;
  native: string;
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params)) if (v !== undefined) url.searchParams.set(k, String(v));
  const res = await fetch(url);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail ?? (await res.text()); } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const api = {
  status: () => get<Status>('/api/status'),
  search: (q: string) => get<SearchResult[]>('/api/search', { q }),
  token: (mint: string) => get<TokenInfo>(`/api/token/${mint}`),
  chart: (mint: string, interval: Interval, mode: CandleMode, from?: number, to?: number) =>
    get<ChartResponse>(`/api/chart/${mint}`, { interval, mode, from, to }),
  metric: (mint: string, metric: MetricKey, interval: Interval, from?: number, to?: number) =>
    get<MetricResponse>(`/api/metric/${mint}`, { metric, interval, from, to }),
};
