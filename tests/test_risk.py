import pytest
from core.risk_manager import RiskManager


def test_strict_one_percent_risk_sizing():
    # Capital initial: 100$ -> 1% = 1.00$ de risque
    rm = RiskManager(current_balance=100.0, risk_pct=0.01, max_leverage=10.0, min_rr=2.0)
    
    # Entrée Long BTC à 80,000$, Stop Loss à 79,600$ (distance = 400$)
    # Take profit à 80,800$ (distance = 800$, RR = 2.0)
    proposal, msg = rm.evaluate_proposal(
        symbol="BTC",
        is_long=True,
        entry_price=80000.0,
        stop_loss=79600.0,
        take_profit=80800.0
    )
    
    assert proposal is not None
    assert msg == "Proposition validée"
    assert proposal.risk_reward_ratio == 2.0
    # Risque théorique = 1.00$
    assert proposal.risk_amount_usd == 1.0
    # Position size = 1$ / 400$ = 0.0025 BTC
    assert proposal.position_size == 0.0025
    # Notional = 0.0025 * 80000 = 200.0$ -> Levier = 2.0x (bien sous le cap de 10x)
    assert proposal.notional_value == 200.0
    assert proposal.leverage == 2.0


def test_reject_low_risk_reward():
    rm = RiskManager(current_balance=100.0, min_rr=2.0)
    
    # RR de 1:1 seulement
    proposal, msg = rm.evaluate_proposal(
        symbol="BTC",
        is_long=True,
        entry_price=80000.0,
        stop_loss=79500.0,  # Risque: 500$
        take_profit=80500.0 # Gain: 500$ -> RR = 1.0 < 2.0
    )
    
    assert proposal is None
    assert "Risk/Reward insuffisant" in msg


def test_spread_guardrail():
    rm = RiskManager(max_spread=0.0004)  # 0.04% max
    
    # Spread normal: bid=80000, ask=80010 (0.0125%)
    res_ok = rm.check_guardrails(best_bid=80000.0, best_ask=80010.0)
    assert res_ok.allowed is True
    
    # Spread anormal: bid=80000, ask=80100 (0.125% > 0.04%)
    res_bad = rm.check_guardrails(best_bid=80000.0, best_ask=80100.0)
    assert res_bad.allowed is False
    assert "Spread trop élevé" in res_bad.reason


def test_daily_drawdown_killswitch():
    rm = RiskManager(current_balance=100.0)
    # Perte de 6$ sur 100$ (6% > 5%)
    rm.update_balance(94.0)
    assert rm.kill_switch_active is True
    
    proposal, msg = rm.evaluate_proposal(
        symbol="BTC",
        is_long=True,
        entry_price=80000.0,
        stop_loss=79000.0,
        take_profit=82000.0
    )
    assert proposal is None
    assert "Kill-Switch" in msg
