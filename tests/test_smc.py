import pytest
import numpy as np
import pandas as pd
from core.smc_engine import SMCEngine, TrendDirection, FairValueGap, OrderBlock, SwingPoint


@pytest.fixture
def sample_candlestick_data():
    """Génère une série temporelle avec une impulsion haussière créant un FVG et un OB."""
    timestamps = [1700000000000 + i * 900000 for i in range(30)]
    opens = [100.0] * 30
    highs = [101.0] * 30
    lows = [99.0] * 30
    closes = [100.0] * 30
    volumes = [10.0] * 30

    # Bougie 10: Order Block baissier (Bougie 1)
    opens[10] = 100.0
    closes[10] = 98.0  # bougie rouge
    highs[10] = 100.5
    lows[10] = 97.5
    volumes[10] = 50.0  # fort volume institutionnel

    # Bougie 11: impulsion haussière puissante (Bougie 2)
    opens[11] = 98.0
    closes[11] = 106.0
    highs[11] = 107.0
    lows[11] = 98.0
    volumes[11] = 80.0

    # Bougie 12: continuation haussière (Bougie 3 laissant un FVG avec lows[12]=103.0 > highs[10]=100.5)
    opens[12] = 106.0
    closes[12] = 108.0
    highs[12] = 109.0
    lows[12] = 103.0
    volumes[12] = 40.0

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })
    return df


def test_fvg_and_ob_detection(sample_candlestick_data):
    engine = SMCEngine()
    atr_series = engine.calculate_atr(sample_candlestick_data)
    fvgs = engine.detect_fvg(sample_candlestick_data, atr_series)
    
    assert len(fvgs) > 0
    bullish_fvgs = [f for f in fvgs if f.is_bullish]
    assert len(bullish_fvgs) >= 1
    fvg = bullish_fvgs[0]
    # Gap attendu entre le haut de la bougie 10 (100.5) et le bas de la bougie 12 (103.0)
    assert fvg.bottom == 100.5
    assert fvg.top == 103.0
    assert fvg.consequent_encroachment == (100.5 + 103.0) / 2.0

    # Test Order Block associé
    obs = engine.detect_order_blocks(sample_candlestick_data, fvgs)
    assert len(obs) > 0
    bullish_obs = [ob for ob in obs if ob.is_bullish]
    assert len(bullish_obs) >= 1
    ob = bullish_obs[0]
    assert ob.index == 10
    assert ob.top == 100.5
    assert ob.bottom == 97.5


def test_fibonacci_ote_zone():
    engine = SMCEngine()
    swings = [
        SwingPoint(index=0, timestamp=1000, price=80000.0, is_high=False),  # Swing Low
        SwingPoint(index=10, timestamp=2000, price=90000.0, is_high=True)   # Swing High (+10,000$)
    ]
    ote = engine.calculate_ote_zone(swings)
    assert ote is not None
    assert ote.is_bullish is True
    # 61.8% = 90000 - 6180 = 83820
    assert abs(ote.fib_618 - 83820.0) < 1e-3
    # 70.5% (Sweet spot) = 90000 - 7050 = 82950
    assert abs(ote.fib_705 - 82950.0) < 1e-3
    # 79.0% = 90000 - 7900 = 82100
    assert abs(ote.fib_790 - 82100.0) < 1e-3

    # Prix dans la zone OTE
    assert ote.contains_price(83000.0) is True
    # Prix hors de la zone
    assert ote.contains_price(85000.0) is False


def test_full_analysis_with_setups(sample_candlestick_data):
    engine = SMCEngine(swing_window=3)
    result = engine.analyze(sample_candlestick_data)
    assert result.current_atr > 0
    assert len(result.fvgs) > 0
    assert len(result.order_blocks) > 0
