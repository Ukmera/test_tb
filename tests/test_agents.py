import pytest
import pandas as pd
from bots.agents.desk_team import ProfessorAgent


@pytest.fixture
def test_candlestick_df():
    """Génère 35 bougies avec un setup FVG/OB."""
    timestamps = [1700000000000 + i * 900000 for i in range(35)]
    opens = [100.0] * 35
    highs = [101.0] * 35
    lows = [99.0] * 35
    closes = [100.0] * 35
    volumes = [10.0] * 35

    # Impulsion haussière
    opens[10] = 100.0
    closes[10] = 98.0
    highs[10] = 100.5
    lows[10] = 97.5

    opens[11] = 98.0
    closes[11] = 106.0
    highs[11] = 107.0
    lows[11] = 98.0

    opens[12] = 106.0
    closes[12] = 108.0
    highs[12] = 109.0
    lows[12] = 103.0

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })


def test_professor_pipeline_veto_on_high_spread(test_candlestick_df):
    prof = ProfessorAgent("BTC", initial_balance=100.0)
    # Spread énorme : bid=80000, ask=80200 (0.25% > 0.04%)
    result = prof.route(test_candlestick_df, best_bid=80000.0, best_ask=80200.0)
    
    # Doit être rejeté soit par le scan soit par Palermo
    assert result.approved is False


def test_palermo_halt_on_consecutive_losses():
    prof = ProfessorAgent("BTC", initial_balance=100.0)
    # Enregistrer 2 pertes consécutives de 0.5R (-0.5R, -0.5R)
    prof.palermo.record_trade_result(-0.5)
    prof.palermo.record_trade_result(-0.5)

    assert prof.palermo.is_halted is True
    assert "2 pertes consécutives" in prof.palermo.halt_reason

    # Vérifier que le veto bloque
    cleared, reason, logs = prof.palermo.evaluate_veto(best_bid=80000.0, best_ask=80010.0)
    assert cleared is False
    assert "PORTE DE VETO BLOQUÉE" in logs[0].message
