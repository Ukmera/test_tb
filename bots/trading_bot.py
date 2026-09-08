import time
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Ajouter la racine du projet au sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import pandas as pd

from config.settings import DEFAULT_SYMBOL, HTF_TIMEFRAME, LTF_TIMEFRAME
from core.data_feed import HyperliquidDataFeed
from core.smc_engine import SMCEngine, TrendDirection
from core.risk_manager import RiskManager
from core.execution_engine import ExecutionEngine
from bots.sentinel_bot import MacroSentinelBot
from bots.critic_bot import AICriticBot

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class MasterTradingDesk:
    """
    Orchestrateur Principal du Desk de Trading Multi-Bots.
    Coordonne le Scanner SMC, la Sentinelle Macro, le Risk Manager et le Critique IA.
    """
    def __init__(self, symbol: str = DEFAULT_SYMBOL):
        self.symbol = symbol
        print(f"[Trading Desk] Initialisation du desk pour {self.symbol}...")

        # Bot 1: Scanner & SMC Engine
        self.data_feed = HyperliquidDataFeed()
        self.smc = SMCEngine()

        # Bot 2: Sentinelle Macro
        self.sentinel = MacroSentinelBot()

        # Bot 3: Risk Manager & Exécution
        self.risk_mgr = RiskManager()
        self.execution = ExecutionEngine()

        # Bot 4: Auto-Critique IA
        self.critic = AICriticBot()

        self.trade_counter = 0

    def step(self) -> Optional[Dict[str, Any]]:
        """
        Un cycle complet d'analyse et d'exécution du desk.
        """
        # 1. Vérification des ordres expirés
        self.execution.cancel_stale_orders()

        # 2. Récupération des données récentes
        best_bid, best_ask, spread = self.data_feed.fetch_order_book(self.symbol)
        if best_bid <= 0:
            return None

        current_price = (best_bid + best_ask) / 2.0

        # Mettre à jour l'exécution et vérifier si un trade se clôture
        closed_trade = self.execution.update_live_market_price(current_price)
        if closed_trade:
            self.trade_counter += 1
            self.risk_mgr.update_balance(self.risk_mgr.current_balance + closed_trade["pnl_usd"])
            self.risk_mgr.record_trade_result(closed_trade["pnl_usd"])

            # Bot 4 : Auto-Critique déclenchée automatiquement
            critique = self.critic.analyze_trade(
                trade_id=self.trade_counter,
                symbol=self.symbol,
                is_long=closed_trade["is_long"],
                entry_price=closed_trade["entry_price"],
                exit_price=closed_trade["exit_price"],
                stop_loss=closed_trade["stop_loss"],
                take_profit=closed_trade["take_profit"],
                pnl_usd=closed_trade["pnl_usd"],
                exit_reason=closed_trade["exit_reason"],
                trend_at_entry="BULLISH" if closed_trade["is_long"] else "BEARISH",
                had_rsi_div=True
            )
            print(f"[Bot Critique IA] Diagnostic trade #{critique.trade_id} ({critique.category}): {critique.diagnosis}")
            return closed_trade

        # Si nous avons déjà une position active ou un ordre limite ouvert, pas de nouveau signal
        if self.execution.active_orders or self.execution.active_position:
            return None

        # 3. Vérification des garde-fous de spread et du Kill-Switch
        guard_check = self.risk_mgr.check_guardrails(best_bid, best_ask)
        if not guard_check.allowed:
            return None

        # 4. Vérification par la Sentinelle Macro
        df = self.data_feed.fetch_candles(self.symbol, interval=HTF_TIMEFRAME, limit_candles=100)
        if df.empty or len(df) < 30:
            return None

        sentinel_ok, sentinel_reason = self.sentinel.is_trading_allowed(df)
        if not sentinel_ok:
            return None

        # 5. Détection SMC par le Scanner
        analysis = self.smc.analyze(df)
        if analysis.trend == TrendDirection.NEUTRAL or not analysis.order_blocks:
            return None

        # 6. Évaluation du retest d'un Order Block récent
        for ob in reversed(analysis.order_blocks):
            if ob.mitigated:
                continue

            # Signal Long sur Bullish OB
            if analysis.trend == TrendDirection.BULLISH and ob.is_bullish:
                if current_price <= ob.top and current_price >= ob.bottom:
                    entry_px = ob.top
                    stop_px = ob.bottom * 0.9995
                    take_px = entry_px + (abs(entry_px - stop_px) * self.risk_mgr.min_rr)

                    prop, msg = self.risk_mgr.evaluate_proposal(
                        symbol=self.symbol,
                        is_long=True,
                        entry_price=entry_px,
                        stop_loss=stop_px,
                        take_profit=take_px
                    )
                    if prop is not None:
                        order = self.execution.place_bracket_order(prop)
                        ob.mitigated = True
                        return order

            # Signal Short sur Bearish OB
            elif analysis.trend == TrendDirection.BEARISH and not ob.is_bullish:
                if current_price >= ob.bottom and current_price <= ob.top:
                    entry_px = ob.bottom
                    stop_px = ob.top * 1.0005
                    take_px = entry_px - (abs(stop_px - entry_px) * self.risk_mgr.min_rr)

                    prop, msg = self.risk_mgr.evaluate_proposal(
                        symbol=self.symbol,
                        is_long=False,
                        entry_price=entry_px,
                        stop_loss=stop_px,
                        take_profit=take_px
                    )
                    if prop is not None:
                        order = self.execution.place_bracket_order(prop)
                        ob.mitigated = True
                        return order

        return None


if __name__ == "__main__":
    desk = MasterTradingDesk("BTC")
    print("⚡ Exécution d'un cycle de test du desk...")
    result = desk.step()
    print("Cycle terminé avec succès. Résultat :", result or "En attente de signal optimal.")
