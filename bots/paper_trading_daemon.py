import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DEFAULT_SYMBOL, INITIAL_CAPITAL_USD
from config.smc_params import ASIA_SESSION_RESTRICT_ENTRIES
from core.data_feed import HyperliquidDataFeed
from core.execution_engine import ExecutionEngine
from bots.agents.desk_team import ProfessorAgent, DeskPipelineResult


class PaperTradingDaemon:
    """
    Démon Autonome de Paper Trading en Temps Réel.
    Surveille le marché en continu, fait délibérer la brigade des 10 agents,
    place des ordres limites réels simulés et gère le cycle de vie complet des positions.
    """
    def __init__(
        self,
        symbol: str = DEFAULT_SYMBOL,
        symbols: Optional[List[str]] = None,
        model: str = "B",
        initial_capital: float = INITIAL_CAPITAL_USD,
        session_filter: bool = ASIA_SESSION_RESTRICT_ENTRIES
    ):
        self.symbols = symbols if symbols is not None else ["BTC", "SOL", "MNT", "SUI"]
        self.symbol = symbol if symbol in self.symbols else self.symbols[0]
        self.model = model.upper()
        self.interval = "1m" if self.model == "A" else "5m"
        self.initial_capital = initial_capital
        self.current_balance = initial_capital
        self.session_filter_enabled = session_filter

        self.data_feed = HyperliquidDataFeed()
        self.professors = {sym: ProfessorAgent(symbol=sym, initial_balance=initial_capital) for sym in self.symbols}
        self.professor = self.professors[self.symbol]
        self.execution = ExecutionEngine()

        self.is_running = True
        self.closed_trades: List[Dict[str, Any]] = []
        self.last_scanned_candle_times: Dict[str, int] = {sym: 0 for sym in self.symbols}
        self.last_scanned_candle_time: int = 0
        self.last_update_time: float = time.time()
        self.current_market_prices: Dict[str, float] = {sym: 0.0 for sym in self.symbols}
        self.current_market_price: float = 0.0

    def check_session_window(self) -> Tuple[bool, str]:
        """
        Vérifie si l'heure actuelle est dans les sessions de haute liquidité (Londres / NY : 08:00 - 20:00 UTC).
        """
        if not self.session_filter_enabled:
            return True, "Filtre de session inactif (24h/24)"

        current_utc_hour = datetime.now(timezone.utc).hour
        # 08:00 UTC (ouverture Londres) à 20:00 UTC (clôture NY)
        if 8 <= current_utc_hour < 20:
            return True, f"Session active : Londres/New York ({current_utc_hour:02d}:00 UTC)"
        else:
            return False, f"Session Asiatique ({current_utc_hour:02d}:00 UTC) : Entrées suspendues par sécurité"

    def step(self) -> Dict[str, Any]:
        """
        Exécute un cycle de surveillance sur le panier d'actifs (BTC, SOL, MNT),
        actualise les positions et scanne les opportunités.
        """
        self.last_update_time = time.time()

        # 1. Mise à jour des cours de marché et des ordres pour chaque actif
        for sym in self.symbols:
            best_bid, best_ask, spread = self.data_feed.fetch_order_book(sym)
            if best_bid > 0 and best_ask > 0:
                mid_px = (best_bid + best_ask) / 2.0
                self.current_market_prices[sym] = mid_px
                if sym == self.symbol:
                    self.current_market_price = mid_px

                # Si une position ou un ordre est ouvert sur cet actif, mise à jour
                if self.execution.active_position and self.execution.active_position.get("symbol") == sym:
                    closed_trade = self.execution.update_live_market_price(mid_px)
                    if closed_trade:
                        pnl = closed_trade["pnl_usd"]
                        self.current_balance += pnl
                        for p in self.professors.values():
                            p.balance = self.current_balance
                            p.risk_mgr.update_balance(self.current_balance)

                        risk_usd = closed_trade.get("notional_usd", 10.0) * 0.01
                        r_multiple = round(pnl / max(0.1, risk_usd), 2)
                        self.professors[sym].palermo.record_trade_result(r_multiple)

                        closed_trade["closed_balance"] = round(self.current_balance, 2)
                        closed_trade["r_multiple"] = r_multiple
                        self.closed_trades.append(closed_trade)

                        now_str = time.strftime("%H:%M:%S")
                        self.professors[sym].activity_log.append(
                            type("Msg", (), {
                                "timestamp": now_str,
                                "agent": "HELSINKI",
                                "status": "CLEARED" if pnl >= 0 else "VETO",
                                "message": f"Position {sym} clôturée [{closed_trade['exit_reason']}] PnL: {pnl:+.2f}$ ({r_multiple:+.1f}R) | Solde: {self.current_balance:.2f}$"
                            })()
                        )

        # Nettoyage des ordres limites expirés (> 3 minutes sans fill)
        self.execution.cancel_stale_orders()

        # Si déjà en position ou ordre en cours, continuer la surveillance
        if self.execution.active_orders or self.execution.active_position:
            return {
                "status": "IN_POSITION" if self.execution.active_position else "ORDER_PENDING",
                "active_position": self.get_active_position_data(),
                "portfolio_symbols": self.symbols
            }

        # Filtre de session (08:00 - 20:00 UTC)
        session_allowed, session_msg = self.check_session_window()
        if not session_allowed:
            return {
                "status": "SESSION_RESTRICTED",
                "session_message": session_msg,
                "active_position": None,
                "portfolio_symbols": self.symbols
            }

        # Scanner les symboles du panier tour à tour
        for sym in self.symbols:
            best_bid, best_ask, spread = self.data_feed.fetch_order_book(sym)
            if best_bid <= 0 or best_ask <= 0:
                continue

            htf_df = self.data_feed.fetch_candles(sym, interval="1h", limit_candles=50)
            df = self.data_feed.fetch_candles(sym, interval=self.interval, limit_candles=80)
            if df.empty or len(df) < 30:
                continue

            latest_candle_time = int(df['timestamp'].iloc[-1])
            if latest_candle_time == self.last_scanned_candle_times.get(sym, 0):
                continue
            self.last_scanned_candle_times[sym] = latest_candle_time

            # Routage du setup par la brigade des 10 agents
            pipeline_result: DeskPipelineResult = self.professors[sym].route(df, best_bid, best_ask, htf_df=htf_df)

            if pipeline_result.approved and pipeline_result.proposal:
                order_ticket = self.execution.place_bracket_order(pipeline_result.proposal)
                self.symbol = sym
                self.professor = self.professors[sym]
                return {
                    "status": "ORDER_PLACED",
                    "order": order_ticket,
                    "active_position": self.get_active_position_data(),
                    "portfolio_symbols": self.symbols
                }

        return {
            "status": "IDLE_SCANNING",
            "active_position": None,
            "portfolio_symbols": self.symbols
        }

    def get_active_position_data(self) -> Optional[Dict[str, Any]]:
        """Calcule le PnL latent et les métriques de la position active en direct."""
        if not self.execution.active_position:
            return None

        pos = self.execution.active_position
        cur_px = self.current_market_price or pos["entry_price"]
        entry_px = pos["entry_price"]
        size = pos["size"]
        is_long = pos["is_long"]

        price_diff = (cur_px - entry_px) if is_long else (entry_px - cur_px)
        unrealized_pnl = price_diff * size
        roi_pct = (price_diff / entry_px) * 100.0 * (pos.get("notional_usd", 10.0) / max(1.0, self.current_balance))

        return {
            "order_id": pos["order_id"],
            "symbol": pos["symbol"],
            "is_long": is_long,
            "entry_price": entry_px,
            "current_price": round(cur_px, 1),
            "stop_loss": pos["stop_loss"],
            "take_profit": pos["take_profit"],
            "size": size,
            "notional_usd": pos["notional_usd"],
            "unrealized_pnl": round(unrealized_pnl, 2),
            "roi_pct": round(roi_pct, 2),
            "created_at": pos.get("fill_time", pos["created_at"])
        }

    def get_state(self) -> Dict[str, Any]:
        """Retourne l'état complet du Paper Trading pour l'API et le Dashboard."""
        session_allowed, session_msg = self.check_session_window()
        return {
            "is_running": self.is_running,
            "model": self.model,
            "interval": self.interval,
            "current_balance": round(self.current_balance, 2),
            "initial_capital": self.initial_capital,
            "total_return_usd": round(self.current_balance - self.initial_capital, 2),
            "total_return_pct": round(((self.current_balance - self.initial_capital) / self.initial_capital) * 100, 2),
            "active_position": self.get_active_position_data(),
            "pending_orders": list(self.execution.active_orders.values()),
            "closed_trades_count": len(self.closed_trades),
            "session_allowed": session_allowed,
            "session_message": session_msg,
            "palermo_halted": self.professor.palermo.is_halted,
            "portfolio_symbols": self.symbols,
            "market_prices": self.current_market_prices
        }
