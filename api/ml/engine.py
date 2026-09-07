"""Predictive engine: scores every holder's churn probability, tiers them by how far
they sit from the population in standard deviations, and drives the C++ Monte Carlo
cascade to estimate liquidity-drainage risk under a quote-asset shock.
"""
from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .. import native
from .features import FEATURE_NAMES, WalletFeatures, engineer_all
from .raw import Collector, RawWallet
from .train import MODEL_PATH, build_dataset, save, train

TIERS = ("stable", "watch", "elevated", "critical")


@dataclass(slots=True)
class HolderRisk:
    wallet: str
    churn_probability: float
    z_score: float
    tier: str
    token_balance: float
    features: dict[str, float]
    archetype: Optional[str]


@dataclass(slots=True)
class TokenRisk:
    mint: str
    model: str
    holders: list[HolderRisk]
    mean_probability: float
    std_probability: float
    supply_at_risk_pct: float      # % of sampled balance held by elevated+critical tiers
    tier_counts: dict[str, int]
    risk_score: float              # 0..100
    feature_importance: dict[str, float]
    generated_at: int


@dataclass(slots=True)
class CascadeReport:
    mint: str
    quote_shock_pct: float
    drained_mean: float
    drained_p50: float
    drained_p90: float
    drained_p99: float
    price_impact_mean: float
    sellers_mean: float
    rounds_mean: float
    histogram: list[float]
    n_sims: int
    absorption: float
    narrative: str


class PredictiveEngine:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.model_path = model_path
        self._bundle: Optional[dict] = None

    # ------------------------------------------------------------------ model

    def bundle(self) -> dict:
        if self._bundle is None:
            import joblib
            if not self.model_path.exists():
                X, y = build_dataset(3000)
                name, model, scores = train(X, y)
                save(model, name, scores, self.model_path)
            self._bundle = joblib.load(self.model_path)
        return self._bundle

    def predict(self, feats: list[WalletFeatures]) -> np.ndarray:
        if not feats:
            return np.zeros(0)
        X = np.asarray([f.vector() for f in feats], dtype=float)
        return self.bundle()["model"].predict_proba(X)[:, 1]

    # ------------------------------------------------------------------ scoring

    async def assess(self, mint: str, collector: Collector, limit: int = 300) -> TokenRisk:
        wallets: list[RawWallet] = await collector.holders(mint, limit)
        now = int(time.time())
        feats = engineer_all(wallets, now)
        probs = self.predict(feats)
        mean = float(probs.mean()) if len(probs) else 0.0
        std = float(probs.std()) if len(probs) > 1 else 0.0

        holders: list[HolderRisk] = []
        for f, p in zip(feats, probs):
            z = (p - mean) / std if std > 1e-9 else 0.0
            holders.append(HolderRisk(
                wallet=f.wallet, churn_probability=float(p), z_score=float(z), tier=_tier(p, z),
                token_balance=f.token_balance,
                features={k: float(v) for k, v in zip(FEATURE_NAMES, f.vector())},
                archetype=f.archetype,
            ))
        holders.sort(key=lambda h: h.churn_probability * math.log10(max(h.token_balance, 10)), reverse=True)

        total_bal = sum(h.token_balance for h in holders) or 1.0
        at_risk = sum(h.token_balance for h in holders if h.tier in ("elevated", "critical")) / total_bal * 100
        counts = {t: sum(1 for h in holders if h.tier == t) for t in TIERS}
        # Balance-weighted probability is what actually threatens the pool.
        weighted = sum(h.churn_probability * h.token_balance for h in holders) / total_bal
        score = 100 * (0.6 * weighted + 0.4 * mean)

        model = self.bundle()["model"]
        imp = getattr(model, "feature_importances_", None)
        return TokenRisk(
            mint=mint, model=self.bundle()["name"], holders=holders, mean_probability=mean, std_probability=std,
            supply_at_risk_pct=at_risk, tier_counts=counts, risk_score=float(min(100, score)),
            feature_importance=dict(zip(FEATURE_NAMES, map(float, imp))) if imp is not None else {},
            generated_at=now,
        )

    # ------------------------------------------------------------------ cascade

    def cascade(self, risk: TokenRisk, pool_token_reserve: float, pool_quote_reserve: float,
                quote_shock_pct: float, n_sims: int = 4000, seed: int = 42, absorption: float = 0.5) -> CascadeReport:
        hs = risk.holders
        balance = [h.token_balance for h in hs]
        churn = [h.churn_probability for h in hs]
        # Panic threshold: holders concentrated in this token break earlier; deep-pocket
        # holders with low concentration tolerate more. Range roughly 8%..60% drawdown.
        thr = [max(0.08, 0.6 - 0.55 * (h.features["concentration_pct"] / 100.0) - 0.15 * h.features["paper_hand_ratio"]) for h in hs]
        res = native.cascade_simulate(balance, churn, thr, pool_token_reserve, pool_quote_reserve, quote_shock_pct, n_sims, seed=seed, absorption=absorption)
        drained_pct = res["drained_mean"] * 100
        critical = risk.tier_counts.get("critical", 0) + risk.tier_counts.get("elevated", 0)
        narrative = (
            f"If the quote asset drops {abs(quote_shock_pct):.0f}%, about {res['sellers_mean']:.0f} of {len(hs)} sampled holders "
            f"(mostly the {critical} in the elevated/critical tiers) are expected to sell across ~{res['rounds_mean']:.1f} cascade rounds, "
            f"draining {drained_pct:.0f}% of the pool on average ({res['drained_p90'] * 100:.0f}% in the worst decile) "
            f"and pushing the token a further {abs(res['price_impact_mean']) * 100:.0f}% down in quote terms."
        )
        return CascadeReport(mint=risk.mint, quote_shock_pct=quote_shock_pct, histogram=res["histogram"], n_sims=n_sims, absorption=absorption,
                             narrative=narrative, **{k: res[k] for k in ("drained_mean", "drained_p50", "drained_p90", "drained_p99", "price_impact_mean", "sellers_mean", "rounds_mean")})


def _tier(p: float, z: float) -> str:
    """Tier by distance from the population mean, floored by absolute probability so a
    uniformly dangerous population is not all labelled 'stable'."""
    if z >= 1.0 or p >= 0.8:
        return "critical"
    if z >= 0.0 and p >= 0.5:
        return "elevated"
    if z >= -1.0 and p >= 0.25:
        return "watch"
    return "stable"
