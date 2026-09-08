import pytest
from unittest.mock import patch, MagicMock
from bots.notifications import NotificationManager


def test_notification_manager_graceful_when_empty():
    # En l'absence de credentials, ne doit pas crasher ni tenter d'envoyer
    mgr = NotificationManager(discord_webhook_url="", telegram_token="", telegram_chat_id="")
    assert mgr.enabled is False

    # Appel des méthodes sans exception
    mgr.notify_order_placed("Alpha Duo", {"symbol": "SOL", "entry_price": 102.5, "is_long": True})
    mgr.notify_position_filled("Alpha Duo", {"symbol": "SOL", "entry_price": 102.5, "is_long": True})
    mgr.notify_breakeven_activated("Alpha Duo", {"symbol": "SOL", "true_be_price": 102.6})
    mgr.notify_trade_closed("Alpha Duo", {"symbol": "SOL", "pnl_usd": 3.5, "r_multiple": 2.0, "exit_reason": "TP"})


@patch("requests.post")
def test_notification_manager_discord_and_telegram_calls(mock_post):
    mock_post.return_value = MagicMock(status_code=200)

    mgr = NotificationManager(
        discord_webhook_url="https://discord.com/api/webhooks/test/123",
        telegram_token="123456:ABC-DEF",
        telegram_chat_id="987654321"
    )
    assert mgr.enabled is True

    # 1. Order Placed
    mgr.notify_order_placed("Alpha Duo", {
        "symbol": "SOL",
        "entry_price": 102.5,
        "is_long": False,
        "stop_loss": 103.0,
        "take_profit": 101.0,
        "notional_usd": 100.0,
        "grade": "5_STAR_OB"
    })
    assert mock_post.call_count == 2  # 1 Discord + 1 Telegram

    # 2. Trade Closed
    mock_post.reset_mock()
    mgr.notify_trade_closed("Alpha Duo", {
        "symbol": "SOL",
        "pnl_usd": 4.50,
        "r_multiple": 2.5,
        "exit_reason": "TP2",
        "closed_balance": 104.50,
        "entry_price": 102.5,
        "exit_price": 100.0
    })
    assert mock_post.call_count == 2


@patch("requests.get")
def test_detect_chat_id_success(mock_get):
    mock_get.return_value = MagicMock(
        json=lambda: {
            "ok": True,
            "result": [
                {
                    "update_id": 1001,
                    "message": {
                        "message_id": 1,
                        "from": {"id": 123456789, "first_name": "Sacha"},
                        "chat": {"id": 123456789, "first_name": "Sacha", "type": "private"},
                        "text": "/start"
                    }
                }
            ]
        }
    )
    mgr = NotificationManager(telegram_token="dummy_token")
    res = mgr.detect_chat_id("dummy_token")
    assert res["success"] is True
    assert res["chat_id"] == "123456789"
    assert res["first_name"] == "Sacha"


@patch("requests.post")
def test_send_test_message_success(mock_post):
    mock_post.return_value = MagicMock(json=lambda: {"ok": True, "result": {"message_id": 123}})
    mgr = NotificationManager()
    res = mgr.send_test_message(token="dummy_token", chat_id="123456789")
    assert res["success"] is True
    assert "succès" in res["message"]

