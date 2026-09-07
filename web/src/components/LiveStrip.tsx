import { useMemo } from 'react';
import { fmtNum, shortMint } from '../lib/format';
import { sumLast, type LiveState } from '../lib/useLiveStream';
import type { SlotDelta } from '../types';

interface Props {
  live: LiveState;
}

const WINDOW = 25; // ~10 s of slots

function Spark({ values, color, baseline }: { values: number[]; color: string; baseline?: boolean }) {
  const w = 220, h = 36;
  if (values.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / span) * (h - 4) - 2}`).join(' ');
  const zeroY = baseline ? h - ((0 - min) / span) * (h - 4) - 2 : null;
  return (
    <svg width={w} height={h} className="spark">
      {zeroY !== null && zeroY >= 0 && zeroY <= h && <line x1={0} x2={w} y1={zeroY} y2={zeroY} stroke="#2a3140" />}
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

export function LiveStrip({ live }: Props) {
  const { deltas, latest, status, latencyMs } = live;
  const rolling = useMemo(() => {
    const buys = sumLast(deltas, WINDOW, (d) => d.buy_amount);
    const sells = sumLast(deltas, WINDOW, (d) => d.sell_amount);
    const imb = buys + sells > 0 ? (buys - sells) / (buys + sells) : 0;
    return {
      holderDelta: sumLast(deltas, WINDOW, (d) => d.holder_delta),
      buys: sumLast(deltas, WINDOW, (d) => d.buys),
      sells: sumLast(deltas, WINDOW, (d) => d.sells),
      traders: sumLast(deltas, WINDOW, (d) => d.traders),
      imbalance: imb,
      // Flow vs. holder divergence: price-moving volume with no holder growth is the
      // "imbalance" this tool exists to surface.
      holdersSeries: deltas.map((d) => d.holders),
      imbSeries: deltas.map((d: SlotDelta) => d.imbalance),
      priceSeries: deltas.map((d) => d.price_lamports_per_token ?? 0),
    };
  }, [deltas]);

  if (status === 'off' && !latest) {
    return <section className="live off"><span className="muted">Live stream unavailable (start the stream service or set STREAM_ORIGIN)</span></section>;
  }

  const imbPct = Math.round(rolling.imbalance * 100);
  const changes = latest?.top_changes.slice(0, 4) ?? [];
  return (
    <section className={`live ${status}`}>
      <div className="live-head">
        <span className={`pulse ${status}`} />
        <b>LIVE</b>
        <span className="muted">slot {latest?.slot ?? '–'} · {status === 'live' ? `${latencyMs} ms` : status}</span>
      </div>

      <div className="live-cell">
        <div className="live-label">Holders</div>
        <div className="live-val">{fmtNum(latest?.holders)} <span className={rolling.holderDelta >= 0 ? 'up' : 'down'}>{rolling.holderDelta >= 0 ? '+' : ''}{rolling.holderDelta}</span><span className="muted"> /10s</span></div>
        <Spark values={rolling.holdersSeries} color="#f7b731" />
      </div>

      <div className="live-cell">
        <div className="live-label">Buy / sell imbalance <span className="muted">10 s</span></div>
        <div className="imb-bar" title="buy volume minus sell volume over total, last ~10 s">
          <div className="imb-fill" style={{ left: imbPct < 0 ? `${50 + imbPct / 2}%` : '50%', width: `${Math.abs(imbPct) / 2}%`, background: imbPct >= 0 ? '#22c55e' : '#ef4444' }} />
        </div>
        <div className="live-val small"><span className="up">{rolling.buys} buys</span> · <span className="down">{rolling.sells} sells</span> · {rolling.traders} traders · <b className={imbPct >= 0 ? 'up' : 'down'}>{imbPct > 0 ? '+' : ''}{imbPct}%</b></div>
        <Spark values={rolling.imbSeries} color="#5b8def" baseline />
      </div>

      <div className="live-cell">
        <div className="live-label">Pool price <span className="muted">lamports / token</span></div>
        <div className="live-val">{latest?.price_lamports_per_token ? latest.price_lamports_per_token.toFixed(3) : '–'}</div>
        <Spark values={rolling.priceSeries} color="#a78bfa" />
      </div>

      <div className="live-cell changes">
        <div className="live-label">Largest balance changes this slot</div>
        {changes.length === 0 && <div className="muted small">quiet slot</div>}
        {changes.map((c) => (
          <div key={c.owner} className={`chg ${c.after >= c.before ? 'up' : 'down'}`}>
            <span className="mono">{shortMint(c.owner)}</span>
            <span>{fmtNum(c.before)} → {fmtNum(c.after)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
