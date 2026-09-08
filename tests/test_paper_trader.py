import pytest
import pandas as pd
from bots.paper_trading_daemon import PaperTradingDaemon
from core.risk_manager import TradeOrderProposal


def test_paper_trading_daemon_initialization(tmp_path):
    daemon = PaperTradingDaemon(symbol="BTC", model="B", initial_capital=100.0, state_file=tmp_path / "init.json")
    state = daemon.get_state()
    assert state["is_running"] is True
    assert state["model"] == "B"
    assert state["interval"] == "5m"
    assert state["current_balance"] == 100.0
    assert state["active_position"] is None
    assert state["pending_orders"] == []


def test_paper_trading_bracket_order_fill_and_tp(tmp_path):
    daemon = PaperTradingDaemon(symbol="BTC", model="B", initial_capital=100.0, state_file=tmp_path / "fill.json")
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


def test_multi_basket_isolation_and_switching(tmp_path):
    daemon = PaperTradingDaemon(model="B", initial_capital=100.0, state_file=tmp_path / "multi_iso.json")
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


def test_paper_trading_persistence_save_load_and_reset(tmp_path):
    test_state_file = tmp_path / "test_paper_state.json"

    # 1. Créer une instance initiale et simuler des gains
    daemon = PaperTradingDaemon(model="B", initial_capital=100.0, state_file=test_state_file)
    daemon.baskets["alpha"].current_balance = 118.50
    daemon.baskets["alpha"].closed_trades.append({
        "order_id": "TEST_1",
        "symbol": "SOL",
        "pnl_usd": 18.50,
        "exit_reason": "TP"
    })
    daemon.set_active_basket("quad")
    daemon.save_state(test_state_file)

    assert test_state_file.exists()

    # 2. Créer une nouvelle instance (simulant un redémarrage du serveur)
    daemon_restarted = PaperTradingDaemon(model="B", initial_capital=100.0, state_file=test_state_file)

    # Vérifier que l'état a été restauré fidèlement
    assert daemon_restarted.active_basket_key == "quad"
    assert daemon_restarted.baskets["alpha"].current_balance == 118.50
    assert len(daemon_restarted.baskets["alpha"].closed_trades) == 1
    assert daemon_restarted.baskets["alpha"].closed_trades[0]["pnl_usd"] == 18.50

    # 3. Tester la réinitialisation
    reset_state = daemon_restarted.reset_state(test_state_file)
    assert reset_state["baskets"]["alpha"]["current_balance"] == 100.0
    assert len(daemon_restarted.baskets["alpha"].closed_trades) == 0


def test_paper_trading_daemon_fills_active_order_on_step():
    """Vérifie qu'un ordre limite Maker placé dans une stratégie est automatiquement exécuté (Filled) lors de step()."""
    daemon = PaperTradingDaemon(model="B", initial_capital=100.0, session_filter=False)
    strat = daemon.baskets["alpha"].strategies["scalp"]

    # Placer un ordre limite Long sur SOL à 100.0$
    proposal = TradeOrderProposal(
        symbol="SOL",
        is_long=True,
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        position_size=1.0,
        notional_value=100.0,
        leverage=1.0,
        risk_amount_usd=2.0,
        risk_reward_ratio=2.0
    )
    order_data = strat.execution.place_bracket_order(proposal)
    assert len(strat.execution.active_orders) == 1
    assert strat.execution.active_position is None

    # Simuler le prix de marché SOL qui descend à 99.8$
    daemon.current_market_prices["SOL"] = 99.8
    # Exécuter un cycle de mise à jour des ordres
    strat.execution.update_live_market_price(daemon.current_market_prices)

    # L'ordre doit être exécuté et devenir une position active
    assert len(strat.execution.active_orders) == 0
    assert strat.execution.active_position is not None
    assert strat.execution.active_position["status"] == "FILLED"
    assert strat.execution.active_position["symbol"] == "SOL"



