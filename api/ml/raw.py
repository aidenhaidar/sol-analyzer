"""Raw per-wallet fields pulled from the chain, and the collectors that produce them.

Fields (see docs/predictive-engine.md):
  wallet, token_balance, transfer timestamps, creation slot / first activity time,
  associated wallet count, associated token count, plus per-token trade history.

`RpcCollector` talks to a Solana JSON-RPC node directly. `MockCollector` produces a
deterministic population of wallet archetypes so the pipeline runs offline.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


@dataclass(slots=True)
class Trade:
    """One buy or sell of the analysed token by this wallet."""
    time: int          # unix seconds
    side: str          # "buy" | "sell"
    amount: float      # tokens
    value_usd: float


@dataclass(slots=True)
class LaunchOutcome:
    """How the wallet behaved in a previous token launch it took part in."""
    token: str
    first_buy: int
    fully_exited_at: Optional[int]  # None if it still holds


@dataclass(slots=True)
class RawWallet:
    wallet: str
    token_balance: float
    token_value_usd: float
    total_wallet_value_usd: float
    first_activity_time: int           # unix seconds of the wallet's first on-chain activity
    creation_slot: int
    associated_wallets: int            # unique counterparties over the wallet's life
    associated_tokens: int             # unique mints ever held
    outbound_tx_count: int             # lifetime outbound transfers
    transfer_timestamps: list[int] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    launches: list[LaunchOutcome] = field(default_factory=list)
    sentiment_alignment: float = 0.0   # -1..1; 0 when no social signal is wired up
    # Label used only for training: did the wallet fully exit within 24h of its first buy?
    churned_24h: Optional[bool] = None
    archetype: Optional[str] = None


class Collector(Protocol):
    async def holders(self, mint: str, limit: int) -> list[RawWallet]: ...


# ---------------------------------------------------------------------------- mock

ARCHETYPES = ("bot", "sybil", "flipper", "retail", "diamond", "whale")


def _rng(mint: str, salt: str = "") -> random.Random:
    return random.Random(int(hashlib.sha256((mint + salt).encode()).hexdigest()[:16], 16))


def synth_wallet(rng: random.Random, archetype: str, now: int, token_price: float, idx: int) -> RawWallet:
    """Build one plausible wallet for the archetype. Numbers are tuned to the heuristics
    in the raw-data notes (fresh sybils, 500-tx/day bots, 100-token flippers, etc.)."""
    day = 86400
    if archetype == "bot":
        age_days = rng.uniform(1, 120)
        assoc_w, assoc_t = rng.randint(200, 3000), rng.randint(50, 800)
        tx_per_day = rng.uniform(150, 800)
        balance = rng.uniform(1e5, 5e6)
        conc = rng.uniform(1, 15)
        hold_hours = rng.uniform(0.01, 1.5)
        paper = rng.uniform(0.7, 1.0)
        churn = rng.random() < 0.85
    elif archetype == "sybil":
        age_days = rng.uniform(0.1, 3)
        assoc_w, assoc_t = rng.randint(1, 4), rng.randint(1, 4)
        tx_per_day = rng.uniform(1, 10)
        balance = rng.uniform(5e4, 2e6)
        conc = rng.uniform(75, 100)
        hold_hours = rng.uniform(0.5, 20)
        paper = rng.uniform(0.6, 1.0)
        churn = rng.random() < 0.9
    elif archetype == "flipper":
        age_days = rng.uniform(30, 900)
        assoc_w, assoc_t = rng.randint(50, 600), rng.randint(100, 500)
        tx_per_day = rng.uniform(10, 80)
        balance = rng.uniform(1e5, 3e6)
        conc = rng.uniform(5, 40)
        hold_hours = rng.uniform(1, 30)
        paper = rng.uniform(0.5, 0.9)
        churn = rng.random() < 0.65
    elif archetype == "retail":
        age_days = rng.uniform(20, 1200)
        assoc_w, assoc_t = rng.randint(5, 80), rng.randint(3, 40)
        tx_per_day = rng.uniform(0.1, 4)
        balance = rng.uniform(1e3, 5e5)
        conc = rng.uniform(5, 60)
        hold_hours = rng.uniform(12, 400)
        paper = rng.uniform(0.1, 0.5)
        churn = rng.random() < 0.25
    elif archetype == "diamond":
        age_days = rng.uniform(200, 2000)
        assoc_w, assoc_t = rng.randint(10, 150), rng.randint(5, 60)
        tx_per_day = rng.uniform(0.05, 1.5)
        balance = rng.uniform(1e4, 2e6)
        conc = rng.uniform(10, 70)
        hold_hours = rng.uniform(300, 5000)
        paper = rng.uniform(0.0, 0.2)
        churn = rng.random() < 0.05
    else:  # whale
        age_days = rng.uniform(300, 2500)
        assoc_w, assoc_t = rng.randint(30, 400), rng.randint(20, 200)
        tx_per_day = rng.uniform(0.5, 8)
        balance = rng.uniform(5e6, 6e7)
        conc = rng.uniform(0.2, 6)
        hold_hours = rng.uniform(100, 3000)
        paper = rng.uniform(0.05, 0.35)
        churn = rng.random() < 0.12

    first_activity = int(now - age_days * day)
    value = balance * token_price
    total = value / (conc / 100.0)
    # Trade history for this token: a buy, maybe partial sells.
    first_buy = max(first_activity, now - int(hold_hours * 3600) - rng.randint(0, 3 * day))
    trades = [Trade(first_buy, "buy", balance * rng.uniform(1.0, 2.5), value * rng.uniform(0.6, 1.4))]
    n_sells = rng.randint(0, 3) if archetype in ("bot", "flipper", "sybil") else rng.randint(0, 1)
    for _ in range(n_sells):
        t = min(now, first_buy + int(rng.uniform(0.2, 1.5) * hold_hours * 3600))
        trades.append(Trade(t, "sell", trades[0].amount * rng.uniform(0.1, 0.5), value * rng.uniform(0.1, 0.5)))
    trades.sort(key=lambda t: t.time)
    launches = []
    for j in range(10):
        fb = first_activity + rng.randint(0, max(1, now - first_activity))
        exited = rng.random() < paper
        launches.append(LaunchOutcome(f"L{j}", fb, fb + rng.randint(600, day) if exited else None))
    timestamps = sorted(int(now - rng.uniform(0, age_days * day)) for _ in range(min(200, int(tx_per_day * age_days) + 1)))
    return RawWallet(
        wallet=f"{archetype[:3].upper()}{idx:04d}{hashlib.sha1(f'{archetype}{idx}'.encode()).hexdigest()[:30]}",
        token_balance=balance, token_value_usd=value, total_wallet_value_usd=total,
        first_activity_time=first_activity, creation_slot=int(first_activity * 2.5),
        associated_wallets=assoc_w, associated_tokens=assoc_t,
        outbound_tx_count=int(tx_per_day * age_days), transfer_timestamps=timestamps,
        trades=trades, launches=launches,
        sentiment_alignment=rng.uniform(-0.2, 0.6) if archetype in ("retail", "diamond") else rng.uniform(-0.6, 0.3),
        churned_24h=churn, archetype=archetype,
    )


class MockCollector:
    """Deterministic population per mint; archetype mix depends on the mint hash so
    different demo tokens look different. When `supply` is given, balances are rescaled
    so the sample collectively holds `supply_share` of it, keeping the cascade honest."""

    def __init__(self, token_price: float = 0.0003, supply: Optional[float] = None, supply_share: float = 0.2):
        self.token_price = token_price
        self.supply = supply
        self.supply_share = supply_share

    def population(self, mint: str, n: int, now: Optional[int] = None) -> list[RawWallet]:
        rng = _rng(mint)
        now = now or int(time.time())
        base = {"bot": 0.5, "sybil": 0.4, "flipper": 0.8, "retail": 3.0, "diamond": 1.5, "whale": 0.3}
        weights = [base[a] * rng.uniform(0.5, 1.6) for a in ARCHETYPES]
        pop = [synth_wallet(rng, rng.choices(ARCHETYPES, weights)[0], now, self.token_price, i) for i in range(n)]
        if self.supply:
            total = sum(w.token_balance for w in pop) or 1.0
            k = self.supply * self.supply_share / total
            for w in pop:
                w.token_balance *= k
                w.token_value_usd *= k
                w.total_wallet_value_usd *= k
                for t in w.trades:
                    t.amount *= k
                    t.value_usd *= k
        return pop

    async def holders(self, mint: str, limit: int = 300) -> list[RawWallet]:
        return self.population(mint, limit)


# ----------------------------------------------------------------------------- RPC

class RpcCollector:
    """Pulls holder wallets straight from a Solana RPC node.

    Uses getTokenLargestAccounts for the top holders (cheap), then for each owner
    getSignaturesForAddress (timestamps, first activity) and getTokenAccountsByOwner
    (associated token count). Counterparty counts require transaction bodies, which
    are sampled to `tx_sample` per wallet to keep RPC load bounded.
    """

    def __init__(self, rpc_url: str, token_price_usd: float, concurrency: int = 8, tx_sample: int = 40):
        self.rpc_url = rpc_url
        self.token_price = token_price_usd
        self.sem = asyncio.Semaphore(concurrency)
        self.tx_sample = tx_sample
        self.client = httpx.AsyncClient(timeout=30)

    async def _rpc(self, method: str, params: list) -> dict:
        async with self.sem:
            r = await self.client.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"rpc {method}: {body['error']}")
        return body["result"]

    async def holders(self, mint: str, limit: int = 20) -> list[RawWallet]:
        largest = (await self._rpc("getTokenLargestAccounts", [mint]))["value"][:limit]
        wallets = await asyncio.gather(*(self._wallet(mint, acct) for acct in largest), return_exceptions=True)
        return [w for w in wallets if isinstance(w, RawWallet)]

    async def _wallet(self, mint: str, acct: dict) -> RawWallet:
        info = await self._rpc("getAccountInfo", [acct["address"], {"encoding": "jsonParsed"}])
        parsed = info["value"]["data"]["parsed"]["info"]
        owner = parsed["owner"]
        balance = float(parsed["tokenAmount"]["uiAmount"] or 0)
        sigs = await self._rpc("getSignaturesForAddress", [owner, {"limit": 1000}])
        times = sorted(s["blockTime"] for s in sigs if s.get("blockTime"))
        first = times[0] if times else int(time.time())
        first_slot = min((s["slot"] for s in sigs), default=0)
        tokens = await self._rpc("getTokenAccountsByOwner", [owner, {"programId": TOKEN_PROGRAM}, {"encoding": "jsonParsed"}])
        assoc_tokens = len(tokens["value"])
        # Counterparties + this token's trades from a sample of transactions.
        counterparties: set[str] = set()
        trades: list[Trade] = []
        for s in sigs[: self.tx_sample]:
            try:
                tx = await self._rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
            except Exception:  # noqa: BLE001
                continue
            if not tx:
                continue
            keys = tx["transaction"]["message"]["accountKeys"]
            counterparties.update(k["pubkey"] for k in keys if k["pubkey"] != owner)
            delta = _token_delta(tx, owner, mint)
            if delta:
                trades.append(Trade(tx["blockTime"], "buy" if delta > 0 else "sell", abs(delta), abs(delta) * self.token_price))
        trades.sort(key=lambda t: t.time)
        # Total wallet value: SOL balance only (token pricing needs a price oracle per mint).
        lamports = (await self._rpc("getBalance", [owner]))["value"]
        sol_usd = float(os_env_float("SOL_PRICE_USD", 150.0))
        total = lamports / 1e9 * sol_usd + balance * self.token_price
        return RawWallet(
            wallet=owner, token_balance=balance, token_value_usd=balance * self.token_price,
            total_wallet_value_usd=max(total, 1e-9), first_activity_time=first, creation_slot=first_slot,
            associated_wallets=len(counterparties), associated_tokens=assoc_tokens,
            outbound_tx_count=len(sigs), transfer_timestamps=times, trades=trades, launches=[],
        )


def _token_delta(tx: dict, owner: str, mint: str) -> float:
    meta = tx.get("meta") or {}
    def amt(entries):
        return sum(float(e["uiTokenAmount"]["uiAmount"] or 0) for e in entries if e.get("owner") == owner and e.get("mint") == mint)
    return amt(meta.get("postTokenBalances", [])) - amt(meta.get("preTokenBalances", []))


def os_env_float(name: str, default: float) -> float:
    import os
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default
