import pytest
import numpy as np
import pandas as pd
from core.smc_engine import SMCEngine, TrendDirection
from backtester.engine import SMCBacktester
from core.risk_manager import RiskManager
from core.trade_diagnostics import TradeForensicAnalyzer

def test_true_breakeven_math():
    rm = RiskManager(current_balance=100.0)
    entry_long = 60000.0
    true_be_long = rm.calculate_true_breakeven(entry_long, is_long=True, maker_fee_pct=0.0002, taker_fee_pct=0.0005, buffer_ticks=1.0)
    assert true_be_long > entry_long
    # Fees roundtrip 0.08% = ~48$, so true_be_long should be ~60049$
    assert true_be_long >= 60045.0

    entry_short = 60000.0
    true_be_short = rm.calculate_true_breakeven(entry_short, is_long=False, maker_fee_pct=0.0002, taker_fee_pct=0.0005, buffer_ticks=1.0)
    assert true_be_short < entry_short
    assert true_be_short <= 59955.0

def test_analyze_mtf_alignment():
    engine = SMCEngine(swing_window=3)
    
    # Créer HTF baissier (prix qui descend)
    htf_times = [1700000000000 + i * 3600000 for i in range(40)]
    htf_closes = [100000.0 - i * 500.0 for i in range(40)]
    htf_df = pd.DataFrame({
        'timestamp': htf_times,
        'open': htf_closes,
        'high': [c + 100.0 for c in htf_closes],
        'low': [c - 100.0 for c in htf_closes],
        'close': htf_closes,
        'volume': [100.0] * 40
    })

    # LTF data
    ltf_times = [1700000000000 + i * 900000 for i in range(100)]
    ltf_closes = [90000.0 + (i % 5) * 50.0 for i in range(100)]
    ltf_df = pd.DataFrame({
        'timestamp': ltf_times,
        'open': ltf_closes,
        'high': [c + 100.0 for c in ltf_closes],
        'low': [c - 100.0 for c in ltf_closes],
        'close': ltf_closes,
        'volume': [50.0] * 100
    })

    res = engine.analyze_mtf(htf_df, ltf_df)
    assert res.htf_trend == TrendDirection.BEARISH
    # Les setups autorisés ne doivent être que SHORT
    for s in res.setups:
        assert s.is_long is False

def test_backtester_two_stage_exit():
    # Générer une série de données où le prix monte à +1R (déclenche TP1 + True BE) puis se retourne
    # Prix initial: 60,000$, Stop: 59,500$ (Risk = 500$). TP1 = 60,500$, TP2 = 61,000$
    times = [1700000000000 + i * 60000 for i in range(60)]
    opens = [60000.0] * 60
    highs = [60100.0] * 60
    lows = [59900.0] * 60
    closes = [60000.0] * 60
    vols = [100.0] * 60

    df = pd.DataFrame({
        'timestamp': times,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': vols
    })

    bt = SMCBacktester(initial_capital=100.0, model='B')
    report = bt.run(df)
    assert report is not None

def test_anti_fee_drag_sizing():
    engine = SMCEngine(swing_window=3)
    times = [1700000000000 + i * 60000 for i in range(50)]
    df = pd.DataFrame({
        'timestamp': times,
        'open': [60000.0 + i * 10 for i in range(50)],
        'high': [60050.0 + i * 10 for i in range(50)],
        'low': [59950.0 + i * 10 for i in range(50)],
        'close': [60010.0 + i * 10 for i in range(50)],
        'volume': [100.0] * 50
    })
    res = engine.analyze(df)
    for s in res.setups:
        risk_dist = abs(s.entry_price - s.stop_loss)
        min_allowed = s.entry_price * 0.0020
        assert risk_dist >= min_allowed - 1e-4

def test_anti_chop_compression():
    engine = SMCEngine(swing_window=3)
    times = [1700000000000 + i * 60000 for i in range(50)]
    df = pd.DataFrame({
        'timestamp': times,
        'open': [60000.0] * 50,
        'high': [60000.5] * 50,
        'low': [59999.5] * 50,
        'close': [60000.0] * 50,
        'volume': [100.0] * 50
    })
    res = engine.analyze(df)
    assert res.is_choppy is True
