import pytest
from fastapi.testclient import TestClient
from dashboard.app import app

client = TestClient(app)

def test_dashboard_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "GPTHEIST DESK" in response.text


def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "symbol" in data
    assert data["symbol"] == "BTC"
    assert "capital_usd" in data
    assert "spread_allowed" in data

def test_api_backtest():
    response = client.get("/api/backtest")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "candles" in data
    assert len(data["candles"]) > 0

def test_api_agents():
    response = client.get("/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert "palermo_gate" in data
    assert "agents" in data
    assert "TOKYO" in data["agents"]
    assert "PALERMO" in data["agents"]
    assert "activity_log" in data
    assert "mission_clock" in data

def test_api_paper_trading():
    response = client.get("/api/paper-trading")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "model" in data
    assert "current_balance" in data

    toggle_resp = client.post("/api/paper-trading/toggle")
    assert toggle_resp.status_code == 200
    assert "is_running" in toggle_resp.json()


def test_api_candles_extended():
    response = client.get("/api/candles?coin=BTC&interval=15m&limit=50")
    assert response.status_code == 200
    data = response.json()
    assert "candles" in data
    assert "smc" in data
    smc = data["smc"]
    assert "order_blocks" in smc
    assert "fvgs" in smc
    assert "swings" in smc
    assert "structures" in smc
    assert "range_info" in smc
    assert "trendlines" in smc


def test_api_backtest_history():
    response = client.get("/api/backtest/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_paper_trading_basket_endpoints():
    # Test récupération des baskets
    response = client.get("/api/paper-trading")
    assert response.status_code == 200
    data = response.json()
    assert "baskets" in data
    assert "alpha" in data["baskets"]
    assert "quad" in data["baskets"]
    assert "core" in data["baskets"]

    # Test basculement sur 'quad'
    switch_resp = client.post("/api/paper-trading/basket?basket=quad")
    assert switch_resp.status_code == 200
    switch_data = switch_resp.json()
    assert switch_data["active_basket_key"] == "quad"
    assert "BTC" in switch_data["symbols"]

    # Test basculement sur 'core'
    switch_resp2 = client.post("/api/paper-trading/basket?basket=core")
    assert switch_resp2.status_code == 200
    assert switch_resp2.json()["active_basket_key"] == "core"

    # Test erreur sur panier inexistant
    bad_resp = client.post("/api/paper-trading/basket?basket=unknown_basket")
    assert bad_resp.status_code == 400

    # Test réinitialisation
    reset_resp = client.post("/api/paper-trading/reset")
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()
    assert reset_data["baskets"]["alpha"]["current_balance"] == 100.0





