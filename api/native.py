"""Bridge to the C++ aggregation library (native/), with a pure-Python fallback.

The fallback keeps the service usable when the shared library has not been built,
but it is roughly 50x slower on large trade feeds.
"""
from __future__ import annotations

import ctypes
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .models import Candle, Point

_LIB_CANDIDATES = [
    os.environ.get("SOLAGG_LIB", ""),
    str(Path(__file__).resolve().parent.parent / "native" / "build" / "libsolagg.so"),
    str(Path(__file__).resolve().parent.parent / "native" / "build" / "libsolagg.dylib"),
]

_lib: Optional[ctypes.CDLL] = None
for candidate in _LIB_CANDIDATES:
    if candidate and Path(candidate).exists():
        try:
            _lib = ctypes.CDLL(candidate)
            break
        except OSError:
            _lib = None

if _lib is not None:
    I64P = ctypes.POINTER(ctypes.c_int64)
    F64P = ctypes.POINTER(ctypes.c_double)
    U8P = ctypes.POINTER(ctypes.c_uint8)
    _lib.sa_resample_candles.restype = ctypes.c_int64
    _lib.sa_resample_candles.argtypes = [I64P, F64P, F64P, F64P, F64P, F64P, ctypes.c_int64,
                                         ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                                         I64P, F64P, F64P, F64P, F64P, F64P, ctypes.c_int64]
    _lib.sa_bucket_trades.restype = ctypes.c_int64
    _lib.sa_bucket_trades.argtypes = [I64P, U8P, F64P, I64P, ctypes.c_int64,
                                      ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                                      I64P, I64P, I64P, F64P, F64P, I64P, ctypes.c_int64]
    _lib.sa_bucket_last.restype = ctypes.c_int64
    _lib.sa_bucket_last.argtypes = [I64P, F64P, ctypes.c_int64, ctypes.c_int64, ctypes.c_int64,
                                    ctypes.c_int64, I64P, F64P, ctypes.c_int64]
    _lib.sa_pearson.restype = ctypes.c_double
    _lib.sa_pearson.argtypes = [F64P, F64P, ctypes.c_int64]
    _lib.sa_version.restype = ctypes.c_char_p


def backend() -> str:
    return _lib.sa_version().decode() if _lib is not None else "python fallback"


def _i64(xs: Iterable[int]) -> ctypes.Array:
    xs = list(xs)
    return (ctypes.c_int64 * len(xs))(*xs)


def _f64(xs: Iterable[float]) -> ctypes.Array:
    xs = list(xs)
    return (ctypes.c_double * len(xs))(*xs)


def _bucket(t: int, step: int) -> int:
    return (t // step) * step


# --------------------------------------------------------------------------- candles

def resample_candles(rows: Sequence[Candle], step: int, start: int, end: int) -> list[Candle]:
    """Resample fine candles (sorted by time) into `step`-second buckets."""
    if _lib is None:
        return _resample_py(rows, step, start, end)
    n = len(rows)
    if n == 0:
        return []
    t, o, h, l, c, v = (_i64(r.time for r in rows), _f64(r.open for r in rows), _f64(r.high for r in rows),
                        _f64(r.low for r in rows), _f64(r.close for r in rows), _f64(r.volume for r in rows))
    cap = n
    ot, oo, oh, ol, oc, ov = ((ctypes.c_int64 * cap)(), *[(ctypes.c_double * cap)() for _ in range(5)])
    k = _lib.sa_resample_candles(t, o, h, l, c, v, n, step, start, end, ot, oo, oh, ol, oc, ov, cap)
    return [Candle(time=ot[i], open=oo[i], high=oh[i], low=ol[i], close=oc[i], volume=ov[i]) for i in range(min(k, cap))]


def _resample_py(rows: Sequence[Candle], step: int, start: int, end: int) -> list[Candle]:
    out: list[Candle] = []
    for r in rows:
        if r.time < start or r.time > end:
            continue
        b = _bucket(r.time, step)
        if not out or out[-1].time != b:
            out.append(Candle(time=b, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume))
        else:
            cur = out[-1]
            cur.high = max(cur.high, r.high)
            cur.low = min(cur.low, r.low)
            cur.close = r.close
            cur.volume += r.volume
    return out


# ---------------------------------------------------------------------------- trades

class TradeBucket:
    __slots__ = ("time", "buys", "sells", "buy_volume", "sell_volume", "traders")

    def __init__(self, time: int, buys: int, sells: int, buy_volume: float, sell_volume: float, traders: int):
        self.time, self.buys, self.sells = time, buys, sells
        self.buy_volume, self.sell_volume, self.traders = buy_volume, sell_volume, traders


def bucket_trades(times: Sequence[int], is_buy: Sequence[bool], volumes: Sequence[float],
                  wallets: Sequence[str], step: int, start: int, end: int) -> list[TradeBucket]:
    """Aggregate a raw trade feed into per-interval buy/sell counts, volumes and unique traders."""
    n = len(times)
    if n == 0:
        return []
    wallet_ids: dict[str, int] = {}
    wid = [wallet_ids.setdefault(w, len(wallet_ids)) for w in wallets]
    if _lib is None:
        return _bucket_trades_py(times, is_buy, volumes, wid, step, start, end)
    t, s, v, w = _i64(times), (ctypes.c_uint8 * n)(*[1 if b else 0 for b in is_buy]), _f64(volumes), _i64(wid)
    cap = _lib.sa_bucket_trades(t, s, v, w, n, step, start, end, None, None, None, None, None, None, 0)
    if cap == 0:
        return []
    ot, ob, os_, otr = ((ctypes.c_int64 * cap)() for _ in range(4))
    obv, osv = (ctypes.c_double * cap)(), (ctypes.c_double * cap)()
    k = _lib.sa_bucket_trades(t, s, v, w, n, step, start, end, ot, ob, os_, obv, osv, otr, cap)
    return [TradeBucket(ot[i], ob[i], os_[i], obv[i], osv[i], otr[i]) for i in range(min(k, cap))]


def _bucket_trades_py(times, is_buy, volumes, wid, step, start, end) -> list[TradeBucket]:
    acc: dict[int, list] = defaultdict(lambda: [0, 0, 0.0, 0.0, set()])
    for t, b, v, w in zip(times, is_buy, volumes, wid):
        if t < start or t > end:
            continue
        a = acc[_bucket(t, step)]
        if b:
            a[0] += 1
            a[2] += v
        else:
            a[1] += 1
            a[3] += v
        a[4].add(w)
    return [TradeBucket(k, a[0], a[1], a[2], a[3], len(a[4])) for k, a in sorted(acc.items())]


# ----------------------------------------------------------------------------- levels

def bucket_last(points: Sequence[Point], step: int, start: int, end: int) -> list[Point]:
    """Take the last observation of a level series (holders, liquidity) per bucket."""
    n = len(points)
    if n == 0:
        return []
    if _lib is None:
        last: dict[int, Point] = {}
        for p in points:
            if start <= p.time <= end:
                b = _bucket(p.time, step)
                if b not in last or p.time >= last[b].time:
                    last[b] = p
        return [Point(time=b, value=p.value) for b, p in sorted(last.items())]
    t, v = _i64(p.time for p in points), _f64(p.value for p in points)
    ot, ov = (ctypes.c_int64 * n)(), (ctypes.c_double * n)()
    k = _lib.sa_bucket_last(t, v, n, step, start, end, ot, ov, n)
    return [Point(time=ot[i], value=ov[i]) for i in range(min(k, n))]


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return math.nan
    if _lib is not None:
        return _lib.sa_pearson(_f64(a[:n]), _f64(b[:n]), n)
    ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a[:n])
    vb = sum((y - mb) ** 2 for y in b[:n])
    return math.nan if va == 0 or vb == 0 else cov / math.sqrt(va * vb)
