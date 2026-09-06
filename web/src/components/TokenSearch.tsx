import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { fmtUsd, shortMint } from '../lib/format';
import type { SearchResult } from '../types';

interface Props {
  onSelect: (r: SearchResult) => void;
}

export function TokenSearch({ onSelect }: Props) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const t = setTimeout(() => {
      api.search(q).then((r) => { if (!cancelled) { setResults(r); setLoading(false); } })
        .catch(() => { if (!cancelled) setLoading(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (!boxRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const pick = (r: SearchResult) => { onSelect(r); setOpen(false); setQ(''); };

  return (
    <div className="search" ref={boxRef}>
      <input
        value={q}
        placeholder="Search token name, symbol or paste a mint address"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            const direct = q.trim();
            if (results[0]) pick(results[0]);
            else if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(direct)) pick({ mint: direct, name: shortMint(direct), symbol: '' });
          }
          if (e.key === 'Escape') setOpen(false);
        }}
      />
      {open && (
        <div className="search-results">
          {loading && results.length === 0 && <div className="search-empty">Searching…</div>}
          {!loading && results.length === 0 && <div className="search-empty">No tokens found</div>}
          {results.map((r) => (
            <button key={r.mint} className="search-row" onClick={() => pick(r)}>
              {r.image ? <img src={r.image} alt="" /> : <span className="avatar">{r.symbol.slice(0, 2)}</span>}
              <span className="sym">{r.symbol}</span>
              <span className="name">{r.name}</span>
              <span className="mint">{shortMint(r.mint)}</span>
              <span className="mcap">{r.marketCap ? fmtUsd(r.marketCap) : ''}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
