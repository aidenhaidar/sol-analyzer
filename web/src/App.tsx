import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Chart, type HoverState, type Layout, type MetricData } from './components/Chart';
import { MetricPicker } from './components/MetricPicker';
import { StatsBar, type MetricStat } from './components/StatsBar';
import { TokenSearch } from './components/TokenSearch';
import { api, type Status } from './lib/api';
import { alignSeries, loadAnalytics, type Analytics } from './lib/analytics';
import { INTERVALS, type Candle, type CandleMode, type Interval, type MetricKey, type SearchResult, type TokenInfo } from './types';

const DEFAULT_MINT = 'DemoBONK1111111111111111111111111111111111111';
const REFRESH_MS = 20_000;
const MAX_LAG = 24;

function readHash(): { mint: string; metrics: MetricKey[] } {
  const p = new URLSearchParams(window.location.hash.slice(1));
  const metrics = (p.get('m')?.split(',').filter(Boolean) as MetricKey[] | undefined) ?? ['holders', 'txns'];
  return { mint: p.get('t') ?? DEFAULT_MINT, metrics };
}

export default function App() {
  const initial = useMemo(readHash, []);
  const [status, setStatus] = useState<Status | null>(null);
  const [mint, setMint] = useState(initial.mint);
  const [token, setToken] = useState<TokenInfo | null>(null);
  const [interval, setInterval_] = useState<Interval>('5m');
  const [mode, setMode] = useState<CandleMode>('marketCap');
  const [layout, setLayout] = useState<Layout>('overlay');
  const [showVolume, setShowVolume] = useState(true);
  const [selected, setSelected] = useState<MetricKey[]>(initial.metrics);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [metrics, setMetrics] = useState<MetricData[]>([]);
  const [hover, setHover] = useState<HoverState>({ time: null, candle: null, metrics: {} });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const reqId = useRef(0);

  useEffect(() => { api.status().then(setStatus).catch(() => setStatus(null)); }, []);
  useEffect(() => { loadAnalytics().then(setAnalytics); }, []);

  // Keep the URL shareable.
  useEffect(() => {
    const p = new URLSearchParams({ t: mint, m: selected.join(',') });
    history.replaceState(null, '', `#${p}`);
  }, [mint, selected]);

  const load = useCallback(async (quiet = false) => {
    const id = ++reqId.current;
    if (!quiet) setLoading(true);
    try {
      const [tok, chart, ...series] = await Promise.all([
        api.token(mint),
        api.chart(mint, interval, mode),
        ...selected.map((k) => api.metric(mint, k, interval)),
      ]);
      if (id !== reqId.current) return;
      setToken(tok);
      setCandles(chart.candles);
      setMetrics(series.map((s) => ({ key: s.metric, points: s.points, approximated: s.approximated })));
      setError(null);
    } catch (e) {
      if (id === reqId.current) setError((e as Error).message);
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [mint, interval, mode, selected]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const t = window.setInterval(() => void load(true), REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const stats: MetricStat[] = useMemo(() => {
    if (!analytics || candles.length < 3) return [];
    return metrics.map((m) => {
      const { closes, values } = alignSeries(candles, m.points);
      const best = analytics.bestLag(closes, values, Math.min(MAX_LAG, Math.floor(closes.length / 4)));
      return { key: m.key, correlation: analytics.pearson(closes, values), lag: best.lag, lagCorrelation: best.correlation, approximated: m.approximated };
    });
  }, [analytics, candles, metrics]);

  const toggleMetric = (k: MetricKey) =>
    setSelected((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));

  const selectToken = (r: SearchResult) => {
    setMint(r.mint);
    setToken(null);
    setCandles([]);
    setMetrics([]);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◎</span> sol-analyzer
        </div>
        <TokenSearch onSelect={selectToken} />
        <div className="status">
          {status?.demo && <span className="badge warn" title="Set SOLANATRACKER_API_KEY on the API to use live data">DEMO DATA</span>}
          {status && !status.demo && <span className="badge ok">LIVE · {status.provider}</span>}
          {analytics && <span className="badge" title={status?.native ?? ''}>{analytics.backend === 'wasm' ? 'rust/wasm' : 'js'}</span>}
        </div>
      </header>

      <StatsBar token={token} mode={mode} hover={hover} stats={stats} analyticsBackend={analytics?.backend ?? 'js'} />

      <div className="toolbar">
        <div className="seg">
          {INTERVALS.map((i) => (
            <button key={i} className={interval === i ? 'on' : ''} onClick={() => setInterval_(i)}>{i}</button>
          ))}
        </div>
        <div className="seg">
          <button className={mode === 'price' ? 'on' : ''} onClick={() => setMode('price')}>Price</button>
          <button className={mode === 'marketCap' ? 'on' : ''} onClick={() => setMode('marketCap')}>Market cap</button>
        </div>
        <div className="seg">
          <button className={layout === 'overlay' ? 'on' : ''} onClick={() => setLayout('overlay')} title="Draw metrics on top of the candles, each on its own scale">Overlay</button>
          <button className={layout === 'panes' ? 'on' : ''} onClick={() => setLayout('panes')} title="One synced pane per metric">Panes</button>
        </div>
        <label className="check">
          <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} /> Volume bars
        </label>
        <MetricPicker selected={selected} onToggle={toggleMetric} />
      </div>

      <main className="chart-wrap">
        {error && <div className="error">{error}</div>}
        {loading && candles.length === 0 && <div className="loading">Loading…</div>}
        <Chart candles={candles} mode={mode} metrics={metrics} layout={layout} showVolume={showVolume} onHover={setHover} />
      </main>

      <footer className="foot">
        <span>Candles: {mode === 'marketCap' ? 'market cap' : 'price'} · {interval} · {candles.length} bars</span>
        <span>r = Pearson correlation between candle close and metric; lag from cross-correlation (±{MAX_LAG} bars).</span>
        <span className="muted">~ approximated series (provider has no history for it)</span>
      </footer>
    </div>
  );
}
