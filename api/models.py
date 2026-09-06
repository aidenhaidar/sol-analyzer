"""Pydantic models and constants shared across the API. Mirrors web/src/types.ts."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Interval = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}
CandleMode = Literal["price", "marketCap"]
MetricKey = Literal[
    "holders", "volume", "buyVolume", "sellVolume",
    "txns", "buys", "sells", "traders", "liquidity",
]
METRIC_KEYS: tuple[str, ...] = MetricKey.__args__  # type: ignore[attr-defined]
Source = Literal["mock", "solanatracker", "dexscreener"]


class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Point(BaseModel):
    time: int
    value: float


class TokenInfo(BaseModel):
    mint: str
    name: str
    symbol: str
    image: Optional[str] = None
    priceUsd: float
    marketCap: float
    liquidityUsd: float
    holders: Optional[int] = None
    supply: Optional[float] = None
    source: Source


class SearchResult(BaseModel):
    mint: str
    name: str
    symbol: str
    image: Optional[str] = None
    marketCap: Optional[float] = None
    priceUsd: Optional[float] = None
    liquidityUsd: Optional[float] = None


class MetricSeries(BaseModel):
    points: list[Point]
    approximated: bool = False


class ChartResponse(BaseModel):
    mint: str
    interval: str
    mode: str
    candles: list[Candle]
    source: Source


class MetricResponse(MetricSeries):
    mint: str
    interval: str
    metric: str
    source: Source


class Status(BaseModel):
    provider: Source
    demo: bool
    native: str
