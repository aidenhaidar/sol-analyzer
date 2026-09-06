export function fmtUsd(v: number | undefined | null, digits = 2): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '–';
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  if (Math.abs(v) < 0.001 && v !== 0) return `$${v.toPrecision(3)}`;
  return `$${v.toFixed(digits)}`;
}

export function fmtNum(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '–';
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
  return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
}

export function fmtPrice(v: number): string {
  if (!Number.isFinite(v)) return '–';
  if (v >= 1) return v.toFixed(4);
  if (v >= 0.0001) return v.toFixed(6);
  // Subscript-zero notation used by Solana terminals: 0.0₅123
  const s = v.toFixed(20).replace(/0+$/, '');
  const m = s.match(/^0\.(0*)(\d+)$/);
  if (!m) return v.toPrecision(4);
  const zeros = m[1].length;
  const sub = String(zeros).replace(/\d/g, (d) => '₀₁₂₃₄₅₆₇₈₉'[Number(d)]);
  return `0.0${sub}${m[2].slice(0, 4)}`;
}

export function fmtPct(v: number): string {
  if (!Number.isFinite(v)) return '–';
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
}

export function shortMint(mint: string): string {
  return mint.length > 12 ? `${mint.slice(0, 4)}…${mint.slice(-4)}` : mint;
}
