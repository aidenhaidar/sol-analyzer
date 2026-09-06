"""Solana Tracker Data API (https://docs.solanatracker.io).

Supplies OHLCV (price or market cap), holder-count history, and a trade feed that
is bucketed natively into per-candle transaction metrics.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .. import native
from ..models import INTERVAL_SECONDS, Candle, MetricSeries, Point, SearchResult, TokenInfo

BASE = "https://data.solanatracker.io"
MAX_TRADE_PAGES = 40


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


class SolanaTrackerProvider:
    name = "solanatracker"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(base_url=BASE, headers={"x-api-key": api_key}, timeout=30)

    async def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        r = await self._client.get(path, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"solanatracker {path} -> {r.status_code} {r.text[:200]}")
        return r.json()

    async def search(self, query: str) -> list[SearchResult]:
        data = await self._get("/search", query=query, limit=15)
        return [
            SearchResult(
                mint=str(t.get("mint")), name=str(t.get("name", "")), symbol=str(t.get("symbol", "")),
                image=t.get("image"), marketCap=_num(t.get("marketCapUsd")),
                priceUsd=_num(t.get("priceUsd")), liquidityUsd=_num(t.get("liquidityUsd")),
            )
            for t in data.get("data", [])
        ]

    async def token_info(self, mint: str) -> TokenInfo:
        data = await self._get(f"/tokens/{mint}")
        tok = data.get("token", {})
        pool = (data.get("pools") or [{}])[0]
        return TokenInfo(
            mint=mint, name=tok.get("name", ""), symbol=tok.get("symbol", ""), image=tok.get("image"),
            priceUsd=_num((pool.get("price") or {}).get("usd")) or 0.0,
            marketCap=_num((pool.get("marketCap") or {}).get("usd")) or 0.0,
            liquidityUsd=_num((pool.get("liquidity") or {}).get("usd")) or 0.0,
            holders=data.get("holders"), supply=_num(pool.get("tokenSupply")), source="solanatracker",
        )

    async def candles(self, mint: str, interval: str, mode: str, start: int, end: int) -> list[Candle]:
        data = await self._get(f"/chart/{mint}", type=interval, time_from=start, time_to=end,
                               marketCap="true" if mode == "marketCap" else None)
        return [
            Candle(time=int(c["time"]), open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                   volume=c.get("volume") or 0.0)
            for c in data.get("oclhv", [])
        ]

    async def _trades(self, mint: str, start: int, end: int) -> list[dict]:
        out: list[dict] = []
        cursor = None
        for _ in range(MAX_TRADE_PAGES):
            data = await self._get(f"/trades/{mint}", cursor=cursor, showMeta="false")
            reached_start = False
            for t in data.get("trades", []):
                sec = t["time"] / 1000
                if sec > end:
                    continue
                if sec < start:
                    reached_start = True
                    break
                out.append(t)
            if reached_start or not data.get("hasNextPage") or not data.get("nextCursor"):
                break
            cursor = data["nextCursor"]
        return out

    async def metric(self, mint: str, metric: str, interval: str, start: int, end: int) -> MetricSeries:
        step = INTERVAL_SECONDS[interval]
        if metric == "holders":
            data = await self._get(f"/holders/chart/{mint}", type=interval, time_from=start, time_to=end)
            pts = [Point(time=int(h["time"]), value=float(h["holders"])) for h in data.get("holders", [])]
            return MetricSeries(points=native.bucket_last(pts, step, start, end))
        if metric == "volume":
            cs = await self.candles(mint, interval, "price", start, end)
            return MetricSeries(points=[Point(time=c.time, value=c.volume) for c in cs])
        if metric == "liquidity":
            # No liquidity history endpoint: draw current liquidity as a flat reference.
            info = await self.token_info(mint)
            pts = [Point(time=t, value=info.liquidityUsd) for t in range((start // step) * step, end + 1, step)]
            return MetricSeries(points=pts, approximated=True)

        trades = await self._trades(mint, start, end)
        buckets = native.bucket_trades(
            [int(t["time"] // 1000) for t in trades],
            [t.get("type") == "buy" for t in trades],
            [float(t.get("volume") or 0.0) for t in trades],
            [str(t.get("wallet", "")) for t in trades],
            step, start, end,
        )
        pick = {
            "buyVolume": lambda b: b.buy_volume, "sellVolume": lambda b: b.sell_volume,
            "txns": lambda b: b.buys + b.sells, "buys": lambda b: b.buys,
            "sells": lambda b: b.sells, "traders": lambda b: b.traders,
        }[metric]
        oldest = trades[-1]["time"] / 1000 if trades else end
        return MetricSeries(points=[Point(time=b.time, value=float(pick(b))) for b in buckets],
                            approximated=oldest > start + step)
