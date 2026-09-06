from __future__ import annotations

from typing import Protocol

from ..models import Candle, MetricSeries, SearchResult, Source, TokenInfo


class DataProvider(Protocol):
    name: Source

    async def search(self, query: str) -> list[SearchResult]: ...
    async def token_info(self, mint: str) -> TokenInfo: ...
    async def candles(self, mint: str, interval: str, mode: str, start: int, end: int) -> list[Candle]: ...
    async def metric(self, mint: str, metric: str, interval: str, start: int, end: int) -> MetricSeries: ...
