"""Keyless Solana token search via DexScreener, used when no Solana Tracker key is set."""
from __future__ import annotations

import httpx

from ..models import SearchResult


async def search(query: str) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.dexscreener.com/latest/dex/search", params={"q": query})
    r.raise_for_status()
    seen: set[str] = set()
    out: list[SearchResult] = []
    for p in r.json().get("pairs") or []:
        base = p.get("baseToken") or {}
        addr = base.get("address")
        if p.get("chainId") != "solana" or not addr or addr in seen:
            continue
        seen.add(addr)
        price = p.get("priceUsd")
        out.append(SearchResult(
            mint=addr, name=base.get("name", ""), symbol=base.get("symbol", ""),
            image=(p.get("info") or {}).get("imageUrl"), marketCap=p.get("marketCap"),
            priceUsd=float(price) if price else None, liquidityUsd=(p.get("liquidity") or {}).get("usd"),
        ))
        if len(out) >= 15:
            break
    return out
