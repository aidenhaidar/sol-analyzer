"""sol-analyzer API: serves candles and overlay metrics for Solana tokens.

Run with:  uvicorn api.main:app --reload --port 8787
Set SOLANATRACKER_API_KEY for live data; otherwise the service runs in demo mode.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import native
from .cache import cached
from .models import (INTERVAL_SECONDS, METRIC_KEYS, CandleMode, ChartResponse, Interval, MetricKey,
                     MetricResponse, SearchResult, Status, TokenInfo)
from .providers import dexscreener
from .providers.base import DataProvider
from .providers.mock import MockProvider
from .providers.solanatracker import SolanaTrackerProvider
from .ml.routes import register as register_ml

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEFAULT_BARS = 300


def build_provider() -> DataProvider:
    key = (os.environ.get("SOLANATRACKER_API_KEY") or "").strip()
    return SolanaTrackerProvider(key) if key else MockProvider()


app = FastAPI(title="sol-analyzer", version="0.1.0")
provider: DataProvider = build_provider()


def _mint(raw: str) -> str:
    if not MINT_RE.match(raw) and not raw.startswith("Demo"):
        raise HTTPException(400, "invalid mint address")
    return raw


def _range(interval: str, start: Optional[int], end: Optional[int]) -> tuple[int, int]:
    end = end or int(time.time())
    start = start or end - DEFAULT_BARS * INTERVAL_SECONDS[interval]
    if start >= end:
        raise HTTPException(400, "invalid range")
    return start, end


@app.get("/api/status", response_model=Status)
async def status() -> Status:
    return Status(provider=provider.name, demo=provider.name == "mock", native=native.backend())


@app.get("/api/search", response_model=list[SearchResult])
async def search(q: str = "") -> list[SearchResult]:
    q = q.strip()

    async def run() -> list[SearchResult]:
        if provider.name != "mock":
            return await provider.search(q)
        demo = await provider.search(q)
        if not q:
            return demo
        try:
            live = await dexscreener.search(q)
        except Exception:  # noqa: BLE001 - live search is best effort in demo mode
            live = []
        return demo + live

    return await cached(f"search:{provider.name}:{q}", 30, run)


@app.get("/api/token/{mint}", response_model=TokenInfo)
async def token(mint: str) -> TokenInfo:
    mint = _mint(mint)
    return await cached(f"token:{mint}", 15, lambda: provider.token_info(mint))


@app.get("/api/chart/{mint}", response_model=ChartResponse)
async def chart(mint: str, interval: Interval = "5m", mode: CandleMode = "price",
                start: Optional[int] = Query(None, alias="from"), end: Optional[int] = Query(None, alias="to")) -> ChartResponse:
    mint = _mint(mint)
    s, e = _range(interval, start, end)
    candles = await cached(f"chart:{mint}:{interval}:{mode}:{s}:{e}", 10,
                           lambda: provider.candles(mint, interval, mode, s, e))
    return ChartResponse(mint=mint, interval=interval, mode=mode, candles=candles, source=provider.name)


@app.get("/api/metric/{mint}", response_model=MetricResponse)
async def metric(mint: str, metric: MetricKey, interval: Interval = "5m",
                 start: Optional[int] = Query(None, alias="from"), end: Optional[int] = Query(None, alias="to")) -> MetricResponse:
    mint = _mint(mint)
    if metric not in METRIC_KEYS:
        raise HTTPException(400, f"unknown metric {metric}")
    s, e = _range(interval, start, end)
    series = await cached(f"metric:{mint}:{metric}:{interval}:{s}:{e}", 10,
                          lambda: provider.metric(mint, metric, interval, s, e))
    return MetricResponse(mint=mint, interval=interval, metric=metric, source=provider.name, **series.model_dump())


register_ml(app, provider, _mint)

# Serve the built web client in production (web/dist).
_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        target = _dist / path
        return FileResponse(target if path and target.is_file() else _dist / "index.html")
