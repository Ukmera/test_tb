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


def test_api_notifications_endpoints(tmp_path):
    from unittest.mock import patch, MagicMock

    # 1. Status
    resp = client.get("/api/notifications/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "telegram_configured" in data
    assert "discord_configured" in data

    # 2. Detect Chat ID (Mock)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: {
                "ok": True,
                "result": [
                    {
                        "message": {
                            "chat": {"id": 998877, "first_name": "Trader"}
                        }
                    }
                ]
            }
        )
        det_resp = client.post("/api/notifications/telegram/detect", json={"token": "123:ABC"})
        assert det_resp.status_code == 200
        det_data = det_resp.json()
        assert det_data["success"] is True
        assert det_data["chat_id"] == "998877"

    # 3. Test Message (Mock)
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(json=lambda: {"ok": True, "result": {"message_id": 1}})
        test_resp = client.post("/api/notifications/telegram/test", json={"token": "123:ABC", "chat_id": "998877"})
        assert test_resp.status_code == 200
        assert test_resp.json()["success"] is True

    # 4. Save Config (Using tmp .env)
    fake_env = tmp_path / ".env"
    with patch("dashboard.app.BASE_DIR", tmp_path):
        save_resp = client.post("/api/notifications/telegram/save", json={"token": "123:ABC", "chat_id": "998877"})
        assert save_resp.status_code == 200
        assert save_resp.json()["status"] == "success"
        assert fake_env.exists()
        content = fake_env.read_text()
        assert "TELEGRAM_BOT_TOKEN=123:ABC" in content
        assert "TELEGRAM_CHAT_ID=998877" in content






