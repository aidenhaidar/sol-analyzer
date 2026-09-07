import time

import numpy as np
from fastapi.testclient import TestClient

from api import native
from api.main import app
from api.ml.features import FEATURE_NAMES, engineer
from api.ml.raw import LaunchOutcome, MockCollector, RawWallet, Trade

client = TestClient(app)
DEMO = "DemoBONK1111111111111111111111111111111111111"


def test_feature_formulas_match_notes():
    now = 1_000_000
    w = RawWallet(
        wallet="w", token_balance=1000, token_value_usd=900, total_wallet_value_usd=1000,
        first_activity_time=now - 10 * 86400, creation_slot=1, associated_wallets=3, associated_tokens=7,
        outbound_tx_count=50,
        trades=[Trade(now - 7200, "buy", 2000, 1000), Trade(now - 3600, "sell", 1000, 500)],
        launches=[LaunchOutcome("a", 0, 3600), LaunchOutcome("b", 0, None), LaunchOutcome("c", 0, 90000), LaunchOutcome("d", 0, 600)],
    )
    f = engineer(w, now)
    assert f.wallet_age_days == 10                       # (now - first)/86400
    assert f.tx_per_day == 5                             # 50 tx / 10 days
    assert f.concentration_pct == 90                     # 900 / 1000 * 100
    assert f.avg_hold_hours == 1                         # sell - buy = 3600s
    assert f.paper_hand_ratio == 0.5                     # 2 of 4 launches exited within 24h
    assert f.token_velocity == 0.5                       # sold 1000 of 2000 bought
    assert f.ecosystem_footprint == 7
    assert len(f.vector()) == len(FEATURE_NAMES)


def test_mock_population_is_deterministic_and_labelled():
    col = MockCollector()
    a = col.population("mint-x", 50, now=123456)
    b = col.population("mint-x", 50, now=123456)
    assert [w.wallet for w in a] == [w.wallet for w in b]
    assert all(w.churned_24h is not None for w in a)
    assert len({w.archetype for w in a}) >= 3


def test_risk_endpoint_scores_and_tiers():
    r = client.get(f"/api/risk/{DEMO}", params={"limit": 120})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sampled_holders"] == 120
    assert 0 <= body["risk_score"] <= 100
    assert sum(body["tier_counts"].values()) == 120
    assert set(body["tier_counts"]) == {"stable", "watch", "elevated", "critical"}
    for h in body["holders"]:
        assert 0 <= h["churn_probability"] <= 1
        assert set(h["features"]) == set(FEATURE_NAMES)
    # Fresh, concentrated sybils should score far riskier than diamond hands on average.
    by_arch = {}
    for h in body["holders"]:
        by_arch.setdefault(h["archetype"], []).append(h["churn_probability"])
    if "sybil" in by_arch and "diamond" in by_arch:
        assert np.mean(by_arch["sybil"]) > np.mean(by_arch["diamond"])


def test_cascade_endpoint_scales_with_shock():
    mild = client.get(f"/api/cascade/{DEMO}", params={"shock": -5, "sims": 500, "limit": 120}).json()
    harsh = client.get(f"/api/cascade/{DEMO}", params={"shock": -40, "sims": 500, "limit": 120}).json()
    assert 0 <= mild["drained_mean"] <= harsh["drained_mean"] <= 1
    assert abs(sum(harsh["histogram"]) - 1) < 1e-6
    assert "draining" in harsh["narrative"]
    assert client.get(f"/api/cascade/{DEMO}", params={"shock": -200}).status_code == 422


def test_cascade_python_fallback_agrees_with_native():
    bal, churn, thr = [10_000.0] * 60, [0.9] * 30 + [0.05] * 30, [0.05] * 30 + [0.6] * 30
    fast = native.cascade_simulate(bal, churn, thr, 5e6, 1000, -15, n_sims=1500, seed=3)
    slow = native._cascade_py(bal, churn, thr, 5e6, 1000, -15, 1500, 8, 3, 20, 0.3)
    assert abs(fast["drained_mean"] - slow["drained_mean"]) < 0.05
    assert abs(fast["sellers_mean"] - slow["sellers_mean"]) < 5
