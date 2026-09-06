import { METRICS, type MetricKey } from '../types';

interface Props {
  selected: MetricKey[];
  onToggle: (k: MetricKey) => void;
}

export function MetricPicker({ selected, onToggle }: Props) {
  return (
    <div className="metric-picker">
      {METRICS.map((m) => {
        const on = selected.includes(m.key);
        return (
          <button
            key={m.key}
            className={`chip ${on ? 'on' : ''}`}
            style={on ? { borderColor: m.color, color: m.color } : undefined}
            onClick={() => onToggle(m.key)}
            title={m.cumulative ? 'Level metric: last value per candle' : 'Flow metric: total per candle'}
          >
            <span className="dot" style={{ background: m.color }} />
            {m.label}
          </button>
        );
      })}
    </div>
  );
}
