import pytest
import pandas as pd
from bots.paper_trading_daemon import PaperTradingDaemon
from core.risk_manager import TradeOrderProposal


def test_paper_trading_daemon_initialization():
    daemon = PaperTradingDaemon(symbol="BTC", model="B", initial_capital=100.0)
    state = daemon.get_state()
    assert state["is_running"] is True
    assert state["model"] == "B"
    assert state["interval"] == "5m"
    assert state["current_balance"] == 100.0
    assert state["active_position"] is None
    assert state["pending_orders"] == []


def test_paper_trading_bracket_order_fill_and_tp():
    daemon = PaperTradingDaemon(symbol="BTC", model="B", initial_capital=100.0)
    # Désactiver filtre de session pour le test
    daemon.session_filter_enabled = False

    # 1. Placer un ordre Long fictif
    proposal = TradeOrderProposal(
        symbol="BTC",
        is_long=True,
        entry_price=90000.0,
        stop_loss=89500.0,
        take_profit=91000.0,
        position_size=0.01,
        notional_value=900.0,
        leverage=9.0,
        risk_amount_usd=1.0,
        risk_reward_ratio=2.0
    )
    daemon.execution.place_bracket_order(proposal)
    assert len(daemon.execution.active_orders) == 1

    # 2. Le prix descend à 89990$ -> L'ordre limite est exécuté (Filled)
    daemon.current_market_price = 89990.0
    daemon.execution.update_live_market_price(89990.0)
    assert daemon.execution.active_position is not None
    assert daemon.execution.active_position["status"] == "FILLED"

    # Vérifier le calcul du PnL latent
    pos_data = daemon.get_active_position_data()
    assert pos_data is not None
    assert pos_data["is_long"] is True

    # 3. Le prix monte à 91050$ -> TP1 et TP2 déclenchés, runner en trailing
    daemon.current_market_price = 91050.0
    daemon.execution.update_live_market_price(91050.0)
    assert daemon.execution.active_position["tp1_hit"] is True
    assert daemon.execution.active_position["tp2_hit"] is True

    # 4. Le runner est clôturé sur trailing stop lors d'un repli sous le stop sécurisé
    closed = daemon.execution.update_live_market_price(90400.0)
    assert closed is not None
    assert closed["exit_reason"] in ("RUNNER_TRAIL", "TP")
    assert closed["pnl_usd"] > 0


def test_multi_basket_isolation_and_switching():
    daemon = PaperTradingDaemon(model="B", initial_capital=100.0)
    state = daemon.get_state()

    # Vérification des 3 paniers initialisés
    assert "baskets" in state
    assert len(state["baskets"]) == 3
    assert set(state["baskets"].keys()) == {"alpha", "quad", "core"}
    assert state["active_basket_key"] == "alpha"
    assert state["baskets"]["alpha"]["symbols"] == ["SOL", "SUI"]
    assert state["baskets"]["quad"]["symbols"] == ["BTC", "SOL", "MNT", "SUI"]
    assert state["baskets"]["core"]["symbols"] == ["BTC", "SOL"]

    # Basculement de panier actif
    success = daemon.set_active_basket("quad")
    assert success is True
    assert daemon.active_basket_key == "quad"
    assert daemon.active_basket.name == "Quad Basket (BTC + SOL + MNT + SUI)"

    # Isolation des portefeuilles : modifier le solde de quad ne touche pas alpha ni core
    daemon.baskets["quad"].current_balance = 125.50
    assert daemon.baskets["alpha"].current_balance == 100.0
    assert daemon.baskets["core"].current_balance == 100.0

    state_quad = daemon.get_state()
    assert state_quad["current_balance"] == 125.50
    assert state_quad["baskets"]["quad"]["current_balance"] == 125.50
    assert state_quad["baskets"]["alpha"]["current_balance"] == 100.0

