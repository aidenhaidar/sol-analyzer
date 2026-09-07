"""Risk and cascade endpoints wired onto the main FastAPI app."""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..cache import cached
from .engine import PredictiveEngine, TokenRisk
from .live import LiveCollector, StreamClient
from .raw import Collector, MockCollector, RpcCollector

router = APIRouter()
engine = PredictiveEngine()
stream = StreamClient()
TOP_HOLDERS_IN_RESPONSE = 60
_live_collectors: dict[str, LiveCollector] = {}


def base_collector(token_price: float, supply: Optional[float]) -> Collector:
    rpc = (os.environ.get("SOLANA_RPC_URL") or "").strip()
    return RpcCollector(rpc, token_price) if rpc else MockCollector(token_price, supply)


def make_collector(mint: str, token_price: float, supply: Optional[float]) -> Collector:
    base = base_collector(token_price, supply)
    if not stream.enabled:
        return base
    lc = _live_collectors.get(mint)
    if lc is None:
        lc = _live_collectors[mint] = LiveCollector(stream, base, token_price=token_price)
    lc.base, lc.token_price = base, token_price
    return lc


async def assess(mint: str, token_price: float, supply: Optional[float], limit: int) -> TokenRisk:
    # Live mode rescoring is cheap (balances are already in memory), so cache briefly.
    ttl = 2 if stream.enabled else 60
    return await cached(f"risk:{mint}:{limit}", ttl, lambda: engine.assess(mint, make_collector(mint, token_price, supply), limit))


def _supply(info) -> Optional[float]:
    if info.supply:
        return float(info.supply)
    return info.marketCap / info.priceUsd if info.priceUsd > 0 and info.marketCap > 0 else None


def risk_payload(r: TokenRisk) -> dict:
    d = asdict(r)
    d["sampled_holders"] = len(r.holders)
    d["holders"] = d["holders"][:TOP_HOLDERS_IN_RESPONSE]
    d["collector"] = "rpc" if os.environ.get("SOLANA_RPC_URL") else "mock"
    d["live"] = stream.enabled
    return d


def register(app, provider, mint_parser) -> None:
    @app.get("/api/live/{mint}")
    async def live(mint: str, top: int = Query(25, ge=1, le=500)) -> dict:
        """Snapshot of the live holder state (the WebSocket at /ws/{mint} carries deltas)."""
        mint = mint_parser(mint)
        if not stream.enabled:
            raise HTTPException(503, "live stream not configured (STREAM_ORIGIN)")
        await stream.watch(mint)
        snap = await stream.snapshot(mint, top)
        if snap is None:
            raise HTTPException(404, "not watched")
        return snap

    @app.get("/api/risk/{mint}")
    async def risk(mint: str, limit: int = Query(300, ge=10, le=2000)) -> dict:
        mint = mint_parser(mint)
        info = await provider.token_info(mint)
        return risk_payload(await assess(mint, info.priceUsd, _supply(info), limit))

    @app.get("/api/cascade/{mint}")
    async def cascade(mint: str, shock: float = Query(-15.0, ge=-95, le=95), sims: int = Query(4000, ge=100, le=50000),
                      limit: int = Query(300, ge=10, le=2000), sol_price: Optional[float] = None,
                      absorption: float = Query(0.5, ge=0, le=1)) -> dict:
        mint = mint_parser(mint)
        info = await provider.token_info(mint)
        if info.priceUsd <= 0 or info.liquidityUsd <= 0:
            raise HTTPException(422, "token has no price or liquidity to simulate against")
        sol = sol_price or float(os.environ.get("SOL_PRICE_USD", 150))
        # Constant-product pool: half the USD liquidity sits on each side.
        pool_quote = info.liquidityUsd / 2 / sol
        pool_token = info.liquidityUsd / 2 / info.priceUsd
        r = await assess(mint, info.priceUsd, _supply(info), limit)
        rep = engine.cascade(r, pool_token, pool_quote, shock, n_sims=sims, absorption=absorption)
        out = asdict(rep)
        out.update(pool_token_reserve=pool_token, pool_quote_reserve=pool_quote, sol_price=sol, sampled_holders=len(r.holders))
        return out
