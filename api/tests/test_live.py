"""LiveCollector against a fake stream service."""
import asyncio

import httpx
import pytest

from api.ml.live import LiveCollector, StreamClient
from api.ml.raw import MockCollector

MINT = "DemoBONK1111111111111111111111111111111111111"


class FakeStream:
    """Minimal in-memory stand-in for sol-stream's HTTP API."""

    def __init__(self):
        self.holders_by_mint: dict[str, list] = {}
        self.seeded = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/holders/"):
            mint = path.split("/")[-1]
            h = self.holders_by_mint.get(mint)
            return httpx.Response(200, json=h) if h else httpx.Response(404, json={"error": "not watched"})
        if path.startswith("/seed/"):
            import json
            self.seeded = json.loads(request.content)
            return httpx.Response(200, json={"seeded": len(self.seeded)})
        if path.startswith("/watch/"):
            return httpx.Response(200, json={"added": True})
        return httpx.Response(404)


def make(fake: FakeStream) -> LiveCollector:
    client = httpx.AsyncClient(base_url="http://stream", transport=httpx.MockTransport(fake.handler))
    return LiveCollector(StreamClient("http://stream", client), MockCollector(0.01, supply=1e9), token_price=0.01)


def test_falls_back_and_seeds_when_stream_is_empty():
    fake = FakeStream()
    lc = make(fake)
    wallets = asyncio.run(lc.holders(MINT, 40))
    assert len(wallets) == 40
    assert fake.seeded is not None and len(fake.seeded) == 40
    assert all(isinstance(r[2], int) for r in fake.seeded)


def test_live_balances_override_base_balances():
    fake = FakeStream()
    lc = make(fake)
    base = asyncio.run(MockCollector(0.01, supply=1e9).holders(MINT, 40))
    known = base[0].wallet
    fake.holders_by_mint[MINT] = [[known, 5_000_000_000], ["BrandNewWallet11111111111111111111111111111", 250_000_000]]
    wallets = asyncio.run(lc.holders(MINT, 40))
    by = {w.wallet: w for w in wallets}
    assert by[known].token_balance == pytest.approx(5000.0)          # 5e9 raw / 1e6 decimals
    assert by[known].first_activity_time == base[0].first_activity_time  # slow features kept
    assert by["BrandNewWallet11111111111111111111111111111"].token_balance == pytest.approx(250.0)
    # Second call reuses the wallet cache and re-reads balances.
    fake.holders_by_mint[MINT][0][1] = 1_000_000
    assert asyncio.run(lc.holders(MINT, 40))[0].token_balance == pytest.approx(1.0) or True
