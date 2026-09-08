import time
import pytest
from unittest.mock import patch, MagicMock
from bots.sentinel_bot import MacroSentinelBot


def test_macro_sentinel_event_freeze():
    sentinel = MacroSentinelBot(freeze_before_min=15, freeze_after_min=15)
    now = int(time.time())

    # Événement dans 10 minutes (doit geler)
    sentinel.add_scheduled_event("US CPI Report", now + 600, impact="HIGH")
    allowed, msg = sentinel.check_macro_freeze(now)
    assert allowed is False
    assert "US CPI Report" in msg

    # Événement il y a 5 minutes (doit geler)
    sentinel.scheduled_events.clear()
    sentinel.add_scheduled_event("FOMC Rate Decision", now - 300, impact="HIGH")
    allowed2, msg2 = sentinel.check_macro_freeze(now)
    assert allowed2 is False
    assert "FOMC Rate Decision" in msg2

    # Événement il y a 2 heures (ne doit plus geler)
    sentinel.scheduled_events.clear()
    sentinel.add_scheduled_event("Old News", now - 7200, impact="HIGH")
    allowed3, msg3 = sentinel.check_macro_freeze(now)
    assert allowed3 is True


@patch("requests.get")
def test_sync_economic_calendar(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"title": "Core CPI m/m", "country": "USD", "date": "2026-09-11T08:30:00-04:00", "impact": "High"},
        {"title": "Low Impact Survey", "country": "USD", "date": "2026-09-11T10:00:00-04:00", "impact": "Low"},
        {"title": "ECB Rate", "country": "EUR", "date": "2026-09-10T08:15:00-04:00", "impact": "High"}
    ]
    mock_get.return_value = mock_resp

    sentinel = MacroSentinelBot()
    count = sentinel.sync_economic_calendar()
    assert count == 2  # Seulement les 2 High impact (USD et EUR)
    assert len(sentinel.scheduled_events) == 2
    assert "Core CPI m/m (USD)" in sentinel.scheduled_events[0]["name"]
