import { fmtNum, fmtPct, fmtPrice, fmtUsd } from '../lib/format';
import { METRIC_BY_KEY, type CandleMode, type MetricKey, type TokenInfo } from '../types';
import type { HoverState } from './Chart';

export interface MetricStat {
  key: MetricKey;
  correlation: number;
  lag: number;
  lagCorrelation: number;
  approximated?: boolean;
}

interface Props {
  token: TokenInfo | null;
  mode: CandleMode;
  hover: HoverState;
  stats: MetricStat[];
  analyticsBackend: string;
}

function describeLag(s: MetricStat): string {
  const label = METRIC_BY_KEY[s.key].label.toLowerCase();
  if (!Number.isFinite(s.lagCorrelation)) return '';
  if (s.lag > 0) return `${label} trails price by ${s.lag} bar${s.lag === 1 ? '' : 's'}`;
  if (s.lag < 0) return `${label} leads price by ${-s.lag} bar${s.lag === -1 ? '' : 's'}`;
  return `${label} moves with price`;
}

export function StatsBar({ token, mode, hover, stats, analyticsBackend }: Props) {
  const c = hover.candle;
  const change = c ? (c.close - c.open) / c.open : NaN;
  return (
    <div className="stats">
      <div className="stats-token">
        {token?.image && <img src={token.image} alt="" />}
        <div>
          <div className="stats-title">
            <span className="sym">{token?.symbol ?? '—'}</span>
            <span className="name">{token?.name ?? 'Select a token'}</span>
          </div>
          <div className="stats-sub">
            <span>Price <b>{token ? fmtPrice(token.priceUsd) : '–'}</b></span>
            <span>MC <b>{fmtUsd(token?.marketCap)}</b></span>
            <span>Liq <b>{fmtUsd(token?.liquidityUsd)}</b></span>
            <span>Holders <b>{fmtNum(token?.holders)}</b></span>
          </div>
        </div>
      </div>

      <div className="stats-ohlc">
        {c ? (
          <>
            <span>O <b>{mode === 'marketCap' ? fmtUsd(c.open) : fmtPrice(c.open)}</b></span>
            <span>H <b>{mode === 'marketCap' ? fmtUsd(c.high) : fmtPrice(c.high)}</b></span>
            <span>L <b>{mode === 'marketCap' ? fmtUsd(c.low) : fmtPrice(c.low)}</b></span>
            <span>C <b>{mode === 'marketCap' ? fmtUsd(c.close) : fmtPrice(c.close)}</b></span>
            <span className={change >= 0 ? 'up' : 'down'}>{fmtPct(change)}</span>
            <span>Vol <b>{fmtUsd(c.volume)}</b></span>
            {Object.entries(hover.metrics).map(([k, v]) => {
              const meta = METRIC_BY_KEY[k as MetricKey];
              return (
                <span key={k} style={{ color: meta.color }}>
                  {meta.label} <b>{meta.unit === 'usd' ? fmtUsd(v) : fmtNum(v)}</b>
                </span>
              );
            })}
          </>
        ) : (
          <span className="muted">Hover the chart for per-candle values</span>
        )}
      </div>

      <div className="stats-corr" title={`Computed in ${analyticsBackend}`}>
        {stats.map((s) => {
          const meta = METRIC_BY_KEY[s.key];
          const r = s.correlation;
          const strength = !Number.isFinite(r) ? '' : Math.abs(r) > 0.7 ? 'strong' : Math.abs(r) > 0.4 ? 'moderate' : 'weak';
          return (
            <div key={s.key} className="corr" style={{ borderColor: meta.color }}>
              <span className="corr-label" style={{ color: meta.color }}>{meta.label}{s.approximated ? ' ~' : ''}</span>
              <span className="corr-r">r = {Number.isFinite(r) ? r.toFixed(2) : '–'}</span>
              <span className="corr-note">{strength}{strength && ' · '}{describeLag(s)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
