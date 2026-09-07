"""Feature engineering: turns RawWallet records into the numeric vector the classifier
consumes. Formulas follow the raw-data notes (wallet age, ecosystem footprint,
holding time, tx frequency, concentration, paper-hand ratio) plus token velocity and
sentiment alignment.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

from .raw import RawWallet

FEATURE_NAMES = [
    "wallet_age_days",
    "ecosystem_footprint",
    "associated_wallets",
    "avg_hold_hours",
    "tx_per_day",
    "token_velocity",
    "concentration_pct",
    "paper_hand_ratio",
    "sentiment_alignment",
    "hours_since_first_buy",
    "log_balance",
]


@dataclass(slots=True)
class WalletFeatures:
    wallet: str
    wallet_age_days: float
    ecosystem_footprint: int
    associated_wallets: int
    avg_hold_hours: float
    tx_per_day: float
    token_velocity: float
    concentration_pct: float
    paper_hand_ratio: float
    sentiment_alignment: float
    hours_since_first_buy: float
    log_balance: float
    token_balance: float
    label: Optional[bool] = None
    archetype: Optional[str] = None

    def vector(self) -> list[float]:
        d = asdict(self)
        return [float(d[k]) for k in FEATURE_NAMES]


def engineer(w: RawWallet, now: Optional[int] = None) -> WalletFeatures:
    import math
    now = now or int(time.time())
    age_days = max((now - w.first_activity_time) / 86400.0, 1e-3)

    # Holding time: hours between each sell and the most recent prior buy.
    holds: list[float] = []
    last_buy: Optional[int] = None
    bought = 0.0
    sold = 0.0
    for t in w.trades:
        if t.side == "buy":
            last_buy = t.time
            bought += t.amount
        elif last_buy is not None:
            holds.append((t.time - last_buy) / 3600.0)
            sold += t.amount
    first_buy = next((t.time for t in w.trades if t.side == "buy"), None)
    if not holds and first_buy is not None:
        holds = [(now - first_buy) / 3600.0]  # still holding: open position age
    avg_hold = sum(holds) / len(holds) if holds else 0.0

    # Token velocity: fraction of everything ever bought that has already been sold.
    velocity = sold / bought if bought > 0 else 0.0

    tx_per_day = w.outbound_tx_count / age_days
    concentration = 100.0 * w.token_value_usd / w.total_wallet_value_usd if w.total_wallet_value_usd > 0 else 0.0

    recent = w.launches[-10:]
    paper = sum(1 for l in recent if l.fully_exited_at is not None and l.fully_exited_at - l.first_buy <= 86400) / len(recent) if recent else 0.0

    return WalletFeatures(
        wallet=w.wallet,
        wallet_age_days=age_days,
        ecosystem_footprint=w.associated_tokens,
        associated_wallets=w.associated_wallets,
        avg_hold_hours=avg_hold,
        tx_per_day=tx_per_day,
        token_velocity=min(velocity, 1.0),
        concentration_pct=min(concentration, 100.0),
        paper_hand_ratio=paper,
        sentiment_alignment=w.sentiment_alignment,
        hours_since_first_buy=(now - first_buy) / 3600.0 if first_buy else 0.0,
        log_balance=math.log10(max(w.token_balance, 1.0)),
        token_balance=w.token_balance,
        label=w.churned_24h,
        archetype=w.archetype,
    )


def engineer_all(wallets: Iterable[RawWallet], now: Optional[int] = None) -> list[WalletFeatures]:
    now = now or int(time.time())
    return [engineer(w, now) for w in wallets]
