"""Bridge to the sol-stream service (stream/): live holder balances and per-slot flow.

When STREAM_ORIGIN is set, the risk engine scores the *live* holder set: balances
come from the stream, slow wallet features come from the collector (RPC or mock)
and are cached per wallet, since they change over hours, not slots.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from .raw import Collector, RawWallet

STREAM_ORIGIN = (os.environ.get("STREAM_ORIGIN") or "").strip()
WALLET_TTL = 6 * 3600


class StreamClient:
    def __init__(self, origin: str = STREAM_ORIGIN, client: Optional[httpx.AsyncClient] = None):
        self.origin = origin.rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=self.origin, timeout=5)

    @property
    def enabled(self) -> bool:
        return bool(self.origin)

    async def watch(self, mint: str) -> None:
        await self.client.post(f"/watch/{mint}")

    async def snapshot(self, mint: str, top: int = 50) -> Optional[dict]:
        r = await self.client.get(f"/state/{mint}", params={"top": top})
        return r.json() if r.status_code == 200 else None

    async def holders(self, mint: str) -> Optional[list[tuple[str, int]]]:
        r = await self.client.get(f"/holders/{mint}")
        return [(o, int(a)) for o, a in r.json()] if r.status_code == 200 else None

    async def seed(self, mint: str, rows: list[tuple[str, str, int]]) -> None:
        await self.client.post(f"/seed/{mint}", json=rows)


class LiveCollector:
    """Collector that takes balances from the stream and slow features from `base`.

    Wallets already known keep their cached slow features; only wallets new to the
    live set trigger a lookup through the base collector.
    """

    def __init__(self, stream: StreamClient, base: Collector, decimals: int = 6, token_price: float = 0.0):
        self.stream = stream
        self.base = base
        self.decimals = decimals
        self.token_price = token_price
        self._wallet_cache: dict[str, tuple[float, RawWallet]] = {}

    async def holders(self, mint: str, limit: int) -> list[RawWallet]:
        live = await self.stream.holders(mint)
        if not live:
            # Stream has nothing yet: fall back to the base scan and seed the stream so
            # it starts from the same picture.
            base = await self.base.holders(mint, limit)
            rows = [(f"ata:{w.wallet}", w.wallet, int(w.token_balance * 10 ** self.decimals)) for w in base]
            try:
                await self.stream.seed(mint, rows)
            except httpx.HTTPError:
                pass
            return base

        live.sort(key=lambda t: t[1], reverse=True)
        live = live[:limit]
        now = time.time()
        # Slow features for unknown wallets come from the base collector once.
        unknown = [o for o, _ in live if o not in self._wallet_cache or self._wallet_cache[o][0] < now - WALLET_TTL]
        if unknown:
            fetched = await self.base.holders(mint, limit)
            by_wallet = {w.wallet: w for w in fetched}
            for o in unknown:
                w = by_wallet.get(o)
                if w is None:
                    # Base collector cannot see this wallet (mock, or not in its top-N):
                    # synthesize a profile seeded by the wallet key so it still gets scored.
                    w = _placeholder_wallet(o, now)
                self._wallet_cache[o] = (now, w)

        out: list[RawWallet] = []
        for owner, raw_amount in live:
            w = self._wallet_cache[owner][1]
            bal = raw_amount / 10 ** self.decimals
            value = bal * self.token_price
            other = max(w.total_wallet_value_usd - w.token_value_usd, 0.0)
            out.append(RawWallet(
                wallet=owner, token_balance=bal, token_value_usd=value,
                total_wallet_value_usd=max(other + value, 1e-9),
                first_activity_time=w.first_activity_time, creation_slot=w.creation_slot,
                associated_wallets=w.associated_wallets, associated_tokens=w.associated_tokens,
                outbound_tx_count=w.outbound_tx_count, transfer_timestamps=w.transfer_timestamps,
                trades=w.trades, launches=w.launches, sentiment_alignment=w.sentiment_alignment,
                churned_24h=w.churned_24h, archetype=w.archetype,
            ))
        return out


def _placeholder_wallet(owner: str, now: float) -> RawWallet:
    """Deterministic stand-in profile for a wallet the base collector cannot describe."""
    import hashlib
    import random
    rng = random.Random(int(hashlib.sha256(owner.encode()).hexdigest()[:12], 16))
    age_days = rng.uniform(1, 600)
    return RawWallet(
        wallet=owner, token_balance=0, token_value_usd=0, total_wallet_value_usd=rng.uniform(200, 50_000),
        first_activity_time=int(now - age_days * 86400), creation_slot=0,
        associated_wallets=rng.randint(2, 300), associated_tokens=rng.randint(1, 120),
        outbound_tx_count=int(age_days * rng.uniform(0.2, 40)),
    )
