"""Deterministic synthetic data so the app runs with no API key.

Holder count is generated to track price with lag and noise, which is exactly the
relationship the app exists to visualise.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass

from .. import native
from ..models import INTERVAL_SECONDS, Candle, MetricSeries, Point, SearchResult, TokenInfo

SUPPLY = 1_000_000_000.0
MINUTES = 60 * 24 * 14  # two weeks of minute data

DEMO_TOKENS = [
    SearchResult(mint="DemoBONK1111111111111111111111111111111111111", name="Demo Bonk", symbol="DBONK", marketCap=42_000_000),
    SearchResult(mint="DemoWIF11111111111111111111111111111111111111", name="Demo Dogwifhat", symbol="DWIF", marketCap=310_000_000),
    SearchResult(mint="DemoPUMP1111111111111111111111111111111111111", name="Demo Pump", symbol="DPUMP", marketCap=1_200_000),
]


def _seed(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


class _Rand:
    """mulberry32, so the same mint always renders the same history."""

    def __init__(self, seed: int):
        self.s = seed & 0xFFFFFFFF

    def __call__(self) -> float:
        self.s = (self.s + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.s
        t = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296


@dataclass(slots=True)
class Minute:
    time: int
    open: float
    high: float
    low: float
    close: float
    buys: int
    sells: int
    buy_volume: float
    sell_volume: float
    traders: int
    holders: int
    liquidity: float


def _generate(mint: str) -> list[Minute]:
    rand = _Rand(_seed(mint))
    meta = next((t for t in DEMO_TOKENS if t.mint == mint), None)
    start_mcap = (meta.marketCap if meta and meta.marketCap else 5_000_000) / 3
    now = int(_time.time() // 60) * 60
    start = now - MINUTES * 60

    out: list[Minute] = []
    price = start_mcap / SUPPLY
    holders = 800 + int(rand() * 400)
    liquidity = start_mcap * 0.08
    momentum = 0.0
    for i in range(MINUTES):
        if rand() < 0.004:
            momentum += (rand() - 0.4) * 0.004
        momentum *= 0.95
        ret = momentum + (rand() - 0.5) * 0.008
        o = price
        c = max(o * (1 + ret), 1e-9)
        wick = abs(ret) * (0.5 + rand())
        h = max(o, c) * (1 + wick * 0.5)
        l = min(o, c) * (1 - wick * 0.5)
        price = c

        activity = 1 + abs(ret) * 120 + max(momentum, 0) * 300
        buys = round(rand() * 6 * activity * (1.4 if ret > 0 else 0.8))
        sells = round(rand() * 6 * activity * (1.4 if ret < 0 else 0.8))
        buy_volume = buys * (50 + rand() * 900)
        sell_volume = sells * (50 + rand() * 900)
        traders = max(1, round((buys + sells) * (0.5 + rand() * 0.4)))

        holders = max(50, holders + round(buys * 0.35 - sells * 0.25 + (rand() - 0.5) * 3))
        # Pool value tracks market cap (memecoin pools hold a few % of supply) plus net flow.
        liquidity = max(1000.0, 0.9 * liquidity + 0.1 * (c * SUPPLY * 0.06) + (buy_volume - sell_volume) * 0.05)
        out.append(Minute(start + i * 60, o, h, l, c, buys, sells, buy_volume, sell_volume, traders, holders, liquidity))
    return out


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._cache: dict[str, list[Minute]] = {}

    def _series(self, mint: str) -> list[Minute]:
        if mint not in self._cache:
            self._cache[mint] = _generate(mint)
        return self._cache[mint]

    async def search(self, query: str) -> list[SearchResult]:
        q = query.strip().lower()
        if not q:
            return DEMO_TOKENS
        return [t for t in DEMO_TOKENS if q in t.name.lower() or q in t.symbol.lower() or t.mint.lower().startswith(q)]

    async def token_info(self, mint: str) -> TokenInfo:
        meta = next((t for t in DEMO_TOKENS if t.mint == mint), None)
        last = self._series(mint)[-1]
        return TokenInfo(
            mint=mint,
            name=meta.name if meta else "Demo Token",
            symbol=meta.symbol if meta else "DEMO",
            priceUsd=last.close,
            marketCap=last.close * SUPPLY,
            liquidityUsd=last.liquidity,
            holders=last.holders,
            supply=SUPPLY,
            source="mock",
        )

    async def candles(self, mint: str, interval: str, mode: str, start: int, end: int) -> list[Candle]:
        mult = SUPPLY if mode == "marketCap" else 1.0
        rows = [Candle(time=m.time, open=m.open * mult, high=m.high * mult, low=m.low * mult,
                       close=m.close * mult, volume=m.buy_volume + m.sell_volume) for m in self._series(mint)]
        return native.resample_candles(rows, INTERVAL_SECONDS[interval], start, end)

    async def metric(self, mint: str, metric: str, interval: str, start: int, end: int) -> MetricSeries:
        step = INTERVAL_SECONDS[interval]
        rows = self._series(mint)
        if metric in ("holders", "liquidity"):
            pts = [Point(time=m.time, value=m.holders if metric == "holders" else m.liquidity) for m in rows]
            return MetricSeries(points=native.bucket_last(pts, step, start, end))

        # Flow metrics: expand minute aggregates into a pseudo trade feed and bucket it
        # through the same native path the live provider uses.
        times: list[int] = []
        is_buy: list[bool] = []
        volumes: list[float] = []
        wallets: list[str] = []
        for m in rows:
            if m.time < start or m.time > end:
                continue
            n = m.buys + m.sells
            if n == 0:
                continue
            for j in range(m.buys):
                times.append(m.time); is_buy.append(True); volumes.append(m.buy_volume / m.buys)
                wallets.append(f"w{(m.time // 60 + j) % max(m.traders, 1)}")
            for j in range(m.sells):
                times.append(m.time); is_buy.append(False); volumes.append(m.sell_volume / m.sells)
                wallets.append(f"w{(m.time // 60 + m.buys + j) % max(m.traders, 1)}")
        buckets = native.bucket_trades(times, is_buy, volumes, wallets, step, start, end)
        pick = {
            "volume": lambda b: b.buy_volume + b.sell_volume,
            "buyVolume": lambda b: b.buy_volume,
            "sellVolume": lambda b: b.sell_volume,
            "txns": lambda b: b.buys + b.sells,
            "buys": lambda b: b.buys,
            "sells": lambda b: b.sells,
            "traders": lambda b: b.traders,
        }[metric]
        return MetricSeries(points=[Point(time=b.time, value=float(pick(b))) for b in buckets])
