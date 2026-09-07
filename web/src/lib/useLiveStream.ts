/**
 * Subscribes to sol-stream's per-slot deltas for a mint over WebSocket, keeps the last
 * `keep` slots, and exposes derived rolling numbers for the live strip. Reconnects with
 * backoff. `status` tells the UI whether live data is actually flowing.
 */
import { useEffect, useRef, useState } from 'react';
import type { LiveSnapshot, SlotDelta } from '../types';

export type LiveStatus = 'connecting' | 'live' | 'stale' | 'off';

export interface LiveState {
  status: LiveStatus;
  snapshot: LiveSnapshot | null;
  deltas: SlotDelta[];
  latest: SlotDelta | null;
  /** ms between the slot being seen by the stream and arriving here. */
  latencyMs: number;
}

const STALE_AFTER_MS = 3000;

export function useLiveStream(mint: string, keep = 300): LiveState {
  const [state, setState] = useState<LiveState>({ status: 'connecting', snapshot: null, deltas: [], latest: null, latencyMs: 0 });
  const deltasRef = useRef<SlotDelta[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 500;
    let staleTimer: number | undefined;
    deltasRef.current = [];
    setState({ status: 'connecting', snapshot: null, deltas: [], latest: null, latencyMs: 0 });

    const armStale = () => {
      window.clearTimeout(staleTimer);
      staleTimer = window.setTimeout(() => setState((s) => (s.status === 'live' ? { ...s, status: 'stale' } : s)), STALE_AFTER_MS);
    };

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${window.location.host}/ws/${mint}`);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as { type: 'snapshot'; data: LiveSnapshot } | { type: 'delta'; data: SlotDelta };
        if (msg.type === 'snapshot') {
          deltasRef.current = msg.data.history.slice(-keep);
          setState({ status: 'live', snapshot: msg.data, deltas: deltasRef.current, latest: deltasRef.current.at(-1) ?? null, latencyMs: 0 });
        } else {
          const d = msg.data;
          deltasRef.current = [...deltasRef.current.slice(-(keep - 1)), d];
          setState((s) => ({ ...s, status: 'live', deltas: deltasRef.current, latest: d, latencyMs: Math.max(0, Date.now() - d.ts_ms) }));
        }
        retry = 500;
        armStale();
      };
      ws.onclose = () => {
        if (closed) return;
        setState((s) => ({ ...s, status: s.snapshot ? 'stale' : 'off' }));
        window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 10_000);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(staleTimer);
      ws?.close();
    };
  }, [mint, keep]);

  return state;
}

/** Sum a numeric field over the last `n` deltas. */
export function sumLast(deltas: SlotDelta[], n: number, pick: (d: SlotDelta) => number): number {
  let s = 0;
  for (let i = Math.max(0, deltas.length - n); i < deltas.length; i++) s += pick(deltas[i]);
  return s;
}
