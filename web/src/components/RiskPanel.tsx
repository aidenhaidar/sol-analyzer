import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtNum, shortMint } from '../lib/format';
import { TIER_COLORS, type CascadeReport, type RiskTier, type TokenRisk } from '../types';

interface Props {
  mint: string;
}

const TIERS: RiskTier[] = ['stable', 'watch', 'elevated', 'critical'];
const FEATURE_LABELS: Record<string, string> = {
  wallet_age_days: 'Age (d)',
  ecosystem_footprint: 'Tokens held',
  associated_wallets: 'Counterparties',
  avg_hold_hours: 'Hold (h)',
  tx_per_day: 'Tx/day',
  token_velocity: 'Velocity',
  concentration_pct: 'Conc. %',
  paper_hand_ratio: 'Paper hands',
  sentiment_alignment: 'Sentiment',
  hours_since_first_buy: 'Since buy (h)',
  log_balance: 'log₁₀ bal',
};
const TABLE_FEATURES = ['wallet_age_days', 'concentration_pct', 'paper_hand_ratio', 'tx_per_day', 'avg_hold_hours', 'ecosystem_footprint'];

export function RiskPanel({ mint }: Props) {
  const [risk, setRisk] = useState<TokenRisk | null>(null);
  const [cascade, setCascade] = useState<CascadeReport | null>(null);
  const [shock, setShock] = useState(-15);
  const [absorption, setAbsorption] = useState(0.5);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    setRisk(null); setCascade(null); setError(null);
    api.risk(mint).then((r) => live && setRisk(r)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [mint]);

  useEffect(() => {
    if (!risk) return;
    let live = true;
    setBusy(true);
    const t = setTimeout(() => {
      api.cascade(mint, shock, absorption).then((c) => { if (live) { setCascade(c); setBusy(false); } })
        .catch((e) => { if (live) { setError(e.message); setBusy(false); } });
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [mint, shock, absorption, risk]);

  if (error) return <section className="risk"><div className="error-inline">Predictive engine: {error}</div></section>;
  if (!risk) return <section className="risk"><div className="muted">Scoring holders…</div></section>;

  const total = risk.sampled_holders || 1;
  const scoreColor = risk.risk_score >= 60 ? TIER_COLORS.critical : risk.risk_score >= 40 ? TIER_COLORS.elevated : risk.risk_score >= 25 ? TIER_COLORS.watch : TIER_COLORS.stable;
  const topFeatures = Object.entries(risk.feature_importance).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const histMax = cascade ? Math.max(...cascade.histogram, 1e-9) : 1;

  return (
    <section className="risk">
      <div className="risk-head">
        <div className="risk-score" style={{ borderColor: scoreColor }}>
          <div className="risk-score-num" style={{ color: scoreColor }}>{risk.risk_score.toFixed(0)}</div>
          <div className="risk-score-label">churn risk</div>
        </div>
        <div className="risk-summary">
          <div className="risk-title">Holder churn model <span className="badge">{risk.model.replace('_', ' ')}</span> <span className="badge">{risk.collector === 'rpc' ? 'RPC holders' : 'synthetic holders'}</span></div>
          <div className="risk-kv">
            <span>Sampled <b>{risk.sampled_holders}</b></span>
            <span>Mean p(churn) <b>{(risk.mean_probability * 100).toFixed(0)}%</b> ± {(risk.std_probability * 100).toFixed(0)}</span>
            <span>Supply in elevated/critical tiers <b>{risk.supply_at_risk_pct.toFixed(1)}%</b></span>
          </div>
          <div className="tier-bar" title="Holders by tier (z-score from the population mean)">
            {TIERS.map((t) => (
              <div key={t} style={{ width: `${(risk.tier_counts[t] / total) * 100}%`, background: TIER_COLORS[t] }} title={`${t}: ${risk.tier_counts[t]}`} />
            ))}
          </div>
          <div className="tier-legend">
            {TIERS.map((t) => <span key={t}><i style={{ background: TIER_COLORS[t] }} />{t} {risk.tier_counts[t]}</span>)}
          </div>
        </div>
        <div className="risk-importance">
          <div className="risk-sub">What drives the model</div>
          {topFeatures.map(([k, v]) => (
            <div key={k} className="imp-row">
              <span>{FEATURE_LABELS[k] ?? k}</span>
              <div className="imp-bar"><div style={{ width: `${v * 100 * 3}%` }} /></div>
              <span className="muted">{(v * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>

      <div className="risk-body">
        <div className="cascade">
          <div className="risk-sub">
            Liquidity cascade simulation
            <span className="muted"> · Monte Carlo, {cascade?.n_sims ?? 4000} paths, constant-product pool</span>
          </div>
          <label className="shock">
            SOL shock <b>{shock}%</b>
            <input type="range" min={-60} max={0} step={1} value={shock} onChange={(e) => setShock(Number(e.target.value))} />
          </label>
          <label className="shock" title="Share of each cascade round's outflow that dip buyers put back into the pool">
            Dip-buyer absorption <b>{Math.round(absorption * 100)}%</b>
            <input type="range" min={0} max={0.9} step={0.05} value={absorption} onChange={(e) => setAbsorption(Number(e.target.value))} className="absorb" />
          </label>
          {cascade && (
            <>
              <div className="cascade-stats" style={{ opacity: busy ? 0.5 : 1 }}>
                <div><b>{(cascade.drained_mean * 100).toFixed(0)}%</b><span>pool drained (mean)</span></div>
                <div><b>{(cascade.drained_p90 * 100).toFixed(0)}%</b><span>p90</span></div>
                <div><b>{(cascade.drained_p99 * 100).toFixed(0)}%</b><span>p99</span></div>
                <div><b>{(cascade.price_impact_mean * 100).toFixed(0)}%</b><span>extra price impact</span></div>
                <div><b>{cascade.sellers_mean.toFixed(0)}</b><span>sellers of {cascade.sampled_holders}</span></div>
                <div><b>{cascade.rounds_mean.toFixed(1)}</b><span>cascade rounds</span></div>
              </div>
              <div className="hist" title="Distribution of pool fraction drained across simulations">
                {cascade.histogram.map((h, i) => (
                  <div key={i} style={{ height: `${(h / histMax) * 100}%`, background: i / cascade.histogram.length > 0.4 ? TIER_COLORS.critical : i / cascade.histogram.length > 0.2 ? TIER_COLORS.elevated : TIER_COLORS.watch }} title={`${(i * 100) / cascade.histogram.length}–${((i + 1) * 100) / cascade.histogram.length}%: ${(h * 100).toFixed(1)}% of paths`} />
                ))}
              </div>
              <div className="hist-axis"><span>0%</span><span>pool drained</span><span>100%</span></div>
              <p className="narrative">{cascade.narrative}</p>
            </>
          )}
        </div>

        <div className="holders">
          <div className="risk-sub">Riskiest holders <span className="muted">· ranked by p(churn) × balance</span></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Wallet</th><th>Tier</th><th>p(churn)</th><th>z</th><th>Balance</th>
                  {TABLE_FEATURES.map((f) => <th key={f}>{FEATURE_LABELS[f]}</th>)}
                </tr>
              </thead>
              <tbody>
                {risk.holders.slice(0, 25).map((h) => (
                  <tr key={h.wallet}>
                    <td className="mono" title={h.wallet}>{shortMint(h.wallet)}{h.archetype && <span className="muted"> {h.archetype}</span>}</td>
                    <td><span className="tier" style={{ color: TIER_COLORS[h.tier], borderColor: TIER_COLORS[h.tier] }}>{h.tier}</span></td>
                    <td>{(h.churn_probability * 100).toFixed(0)}%</td>
                    <td className={h.z_score >= 0 ? 'down' : 'up'}>{h.z_score >= 0 ? '+' : ''}{h.z_score.toFixed(1)}σ</td>
                    <td>{fmtNum(h.token_balance)}</td>
                    {TABLE_FEATURES.map((f) => <td key={f}>{fmtNum(h.features[f])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
