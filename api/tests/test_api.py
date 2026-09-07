import math

import pytest
from fastapi.testclient import TestClient

from api import native
from api.main import app
from api.models import Candle, Point

client = TestClient(app)
DEMO = "DemoBONK1111111111111111111111111111111111111"


def test_status_demo_mode():
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["demo"] is True


def test_chart_and_metric_align_on_time():
    chart = client.get(f"/api/chart/{DEMO}", params={"interval": "15m"}).json()
    holders = client.get(f"/api/metric/{DEMO}", params={"interval": "15m", "metric": "holders"}).json()
    assert len(chart["candles"]) > 250
    times = {c["time"] for c in chart["candles"]}
    assert times == {p["time"] for p in holders["points"]}
    assert all(c["time"] % 900 == 0 for c in chart["candles"])
    # Candles are ordered and internally consistent.
    for a, b in zip(chart["candles"], chart["candles"][1:]):
        assert a["time"] < b["time"]
        assert b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"]


def test_market_cap_mode_scales_price():
    price = client.get(f"/api/chart/{DEMO}", params={"interval": "1h"}).json()["candles"]
    mcap = client.get(f"/api/chart/{DEMO}", params={"interval": "1h", "mode": "marketCap"}).json()["candles"]
    assert mcap[0]["close"] / price[0]["close"] == pytest.approx(1e9)


def test_flow_metrics_sum_consistently():
    p = {"interval": "1h"}
    buys = client.get(f"/api/metric/{DEMO}", params={**p, "metric": "buys"}).json()["points"]
    sells = client.get(f"/api/metric/{DEMO}", params={**p, "metric": "sells"}).json()["points"]
    txns = client.get(f"/api/metric/{DEMO}", params={**p, "metric": "txns"}).json()["points"]
    assert [b["value"] + s["value"] for b, s in zip(buys, sells)] == [t["value"] for t in txns]


def test_invalid_inputs():
    assert client.get("/api/chart/not-a-mint").status_code == 400
    assert client.get(f"/api/chart/{DEMO}", params={"interval": "7m"}).status_code == 422
    assert client.get(f"/api/metric/{DEMO}", params={"metric": "nope"}).status_code == 422


def test_native_fallback_matches_native():
    rows = [Candle(time=t * 60, open=t, high=t + 1, low=t - 1, close=t + 0.5, volume=1) for t in range(12)]
    fast = native.resample_candles(rows, 300, 0, 10_000)
    slow = native._resample_py(rows, 300, 0, 10_000)
    assert [c.model_dump() for c in fast] == [c.model_dump() for c in slow]
    assert fast[0].volume == 5 and fast[-1].time == 600

    pts = [Point(time=t, value=t) for t in range(0, 1000, 7)]
    assert native.bucket_last(pts, 300, 0, 1000)[0].value == 294

    assert native.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert math.isnan(native.pearson([1, 1, 1], [1, 2, 3]))


def test_shared_secret_gate(monkeypatch):
    from api import main as m
    monkeypatch.setattr(m, "_SHARED_SECRET", "s3cret")
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers={"x-api-secret": "s3cret"}).status_code == 200
    assert client.get("/api/health").status_code == 200
