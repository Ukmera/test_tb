import pytest
from core.alan_liquidity_engine import AlanLiquidityEngine, AlanEvaluation
from bots.agents.desk_team import ProfessorAgent


def test_alan_short_squeeze_veto_and_boost():
    engine = AlanLiquidityEngine()
    
    # Contexte dérivé avec fort taux de funding négatif (shorts sur-encombrés)
    # funding horaire = -0.00002 -> 8h funding = -0.00016 (-0.016%), bien sous -0.00005
    ctx = {
        "funding": "-0.00002",
        "openInterest": "50000000.0",
        "prevDayPx": "90000.0",
        "dayNtlVlm": "100000000.0",
        "markPx": "91000.0"
    }
    fng = {"value": 25, "classification": "Extreme Fear"}
    
    # 1. Proposition SHORT -> Doit être VETO
    eval_short = engine.evaluate_signal(
        symbol="BTC",
        is_long=False,
        entry_price=91000.0,
        stop_loss=91500.0,
        take_profit=90000.0,
        asset_context=ctx,
        fear_and_greed=fng
    )
    assert eval_short.approved is False
    assert eval_short.is_vetoed is True
    assert eval_short.regime == "SHORT_SQUEEZE_ALERT"
    assert "VETO ALAN TRADING" in eval_short.reason
    
    # 2. Proposition LONG -> Doit être BOOSTÉE (Short Squeeze imminent = pump violent)
    eval_long = engine.evaluate_signal(
        symbol="BTC",
        is_long=True,
        entry_price=91000.0,
        stop_loss=90500.0,
        take_profit=92000.0,
        asset_context=ctx,
        fear_and_greed=fng
    )
    assert eval_long.approved is True
    assert eval_long.is_vetoed is False
    assert eval_long.is_boosted is True
    assert eval_long.score_boost == 15.0
    # TP étendu : 91000 + (500 * 2.0 * 1.35) = 91000 + 1350 = 92350
    assert eval_long.adjusted_tp == 92350.0
    assert "BOOST ALAN TRADING" in eval_long.reason


def test_alan_long_squeeze_veto_and_boost():
    engine = AlanLiquidityEngine()
    
    # Contexte dérivé avec fort taux de funding positif (longs sur-leveragés, greedy)
    # funding horaire = +0.00005 -> 8h funding = +0.0004 (+0.04%), au-dessus de +0.00025
    ctx = {
        "funding": "0.00005",
        "openInterest": "30000000.0",
        "prevDayPx": "180.0",
        "dayNtlVlm": "50000000.0",
        "markPx": "185.0"
    }
    fng = {"value": 82, "classification": "Extreme Greed"}
    
    # 1. Proposition LONG -> Doit être VETO
    eval_long = engine.evaluate_signal(
        symbol="SOL",
        is_long=True,
        entry_price=185.0,
        stop_loss=180.0,
        take_profit=195.0,
        asset_context=ctx,
        fear_and_greed=fng
    )
    assert eval_long.approved is False
    assert eval_long.is_vetoed is True
    assert eval_long.regime == "LONG_SQUEEZE_ALERT"
    assert "VETO ALAN TRADING" in eval_long.reason
    
    # 2. Proposition SHORT -> Doit être BOOSTÉE (Long Squeeze imminent = dump cascade)
    eval_short = engine.evaluate_signal(
        symbol="SOL",
        is_long=False,
        entry_price=185.0,
        stop_loss=190.0,
        take_profit=175.0,
        asset_context=ctx,
        fear_and_greed=fng
    )
    assert eval_short.approved is True
    assert eval_short.is_vetoed is False
    assert eval_short.is_boosted is True
    assert eval_short.score_boost == 15.0
    # TP étendu : 185 - (5 * 2.0 * 1.35) = 185 - 13.5 = 171.5
    assert eval_short.adjusted_tp == 171.5
    assert "BOOST ALAN TRADING" in eval_short.reason


def test_alan_neutral_regime():
    engine = AlanLiquidityEngine()
    
    ctx = {
        "funding": "0.000001",
        "openInterest": "20000000.0",
        "prevDayPx": "3000.0",
        "dayNtlVlm": "40000000.0",
        "markPx": "3050.0"
    }
    fng = {"value": 50, "classification": "Neutral"}
    
    eval_long = engine.evaluate_signal(
        symbol="ETH",
        is_long=True,
        entry_price=3050.0,
        stop_loss=3000.0,
        take_profit=3150.0,
        asset_context=ctx,
        fear_and_greed=fng
    )
    assert eval_long.approved is True
    assert eval_long.is_vetoed is False
    assert eval_long.is_boosted is False
    assert eval_long.regime == "NEUTRAL"
    assert eval_long.score_boost == 0.0
    assert eval_long.adjusted_tp == 3150.0


def test_professor_agent_alan_integration():
    # Test Professor avec Alan désactivé (Groupe A / B)
    prof_standard = ProfessorAgent(enable_alan_engine=False)
    assert prof_standard.alan is None
    
    # Test Professor avec Alan activé (Groupe C / D)
    prof_alan = ProfessorAgent(enable_alan_engine=True)
    assert prof_alan.alan is not None
    status = prof_alan.get_team_status()
    assert "ALAN" in status["agents"]
    assert status["agents"]["ALAN"]["status"] == "ACTIVE"
