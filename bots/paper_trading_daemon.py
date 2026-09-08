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


class PaperBasket:
    """
    Portefeuille de Paper Trading isolé pour l'A/B Testing en direct.
    Gère son propre capital, ses positions, ses ordres et son historique de trades.
    """
    def __init__(
        self,
        key: str,
        name: str,
        symbols: List[str],
        initial_capital: float = INITIAL_CAPITAL_USD,
        model: str = "B"
    ):
        self.key = key
        self.name = name
        self.symbols = symbols
        self.model = model.upper()
        self.interval = "1m" if self.model == "A" else "5m"
        self.initial_capital = initial_capital
        self.current_balance = initial_capital
        self.execution = ExecutionEngine()
        self.professors = {sym: ProfessorAgent(symbol=sym, initial_balance=initial_capital) for sym in symbols}
        self.closed_trades: List[Dict[str, Any]] = []
        self.last_scanned_candle_times: Dict[str, int] = {sym: 0 for sym in symbols}

    def get_win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.get("pnl_usd", 0) > 0)
        return round((wins / len(self.closed_trades)) * 100, 1)

    def get_active_position_data(self, market_prices: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Calcule le PnL latent et les métriques de la position active en direct."""
        if not self.execution.active_position:
            return None

        pos = self.execution.active_position
        sym = pos.get("symbol", self.symbols[0])
        cur_px = market_prices.get(sym, pos["entry_price"])
        if cur_px <= 0:
            cur_px = pos["entry_price"]
        entry_px = pos["entry_price"]
        size = pos["size"]
        is_long = pos["is_long"]

        price_diff = (cur_px - entry_px) if is_long else (entry_px - cur_px)
        unrealized_pnl = price_diff * size
        roi_pct = (price_diff / entry_px) * 100.0 * (pos.get("notional_usd", 10.0) / max(1.0, self.current_balance))

        return {
            "order_id": pos["order_id"],
            "symbol": sym,
            "is_long": is_long,
            "entry_price": entry_px,
            "current_price": round(cur_px, 2),
            "stop_loss": pos["stop_loss"],
            "take_profit": pos["take_profit"],
            "size": size,
            "notional_usd": pos["notional_usd"],
            "unrealized_pnl": round(unrealized_pnl, 2),
            "roi_pct": round(roi_pct, 2),
            "created_at": pos.get("fill_time", pos["created_at"])
        }

    def get_summary(self, market_prices: Dict[str, float]) -> Dict[str, Any]:
        """Retourne le résumé complet des métriques du portefeuille."""
        ret_usd = round(self.current_balance - self.initial_capital, 2)
        ret_pct = round((ret_usd / self.initial_capital) * 100, 2)
        pos = self.get_active_position_data(market_prices)

        return {
            "key": self.key,
            "name": self.name,
            "symbols": self.symbols,
            "current_balance": round(self.current_balance, 2),
            "initial_capital": self.initial_capital,
            "total_return_usd": ret_usd,
            "total_return_pct": ret_pct,
            "closed_trades_count": len(self.closed_trades),
            "win_rate_pct": self.get_win_rate(),
            "active_position": pos,
            "pending_orders": list(self.execution.active_orders.values())
        }


class PaperTradingDaemon:
    """
    Démon Autonome de Paper Trading en Temps Réel avec A/B Testing Multi-Paniers.
    Fait tourner en parallèle 3 portefeuilles indépendants :
      1. Alpha Duo : SOL + SUI (Meilleure performance backtest +66.7%)
      2. Quad Basket : BTC + SOL + MNT + SUI (Diversification maximale & Bogota Arbitrage)
      3. Core Duo : BTC + SOL (Benchmark institutionnel de référence)
    """
    def __init__(
        self,
        symbol: str = DEFAULT_SYMBOL,
        symbols: Optional[List[str]] = None,
        model: str = "B",
        initial_capital: float = INITIAL_CAPITAL_USD,
        session_filter: bool = ASIA_SESSION_RESTRICT_ENTRIES
    ):
        self.initial_capital = initial_capital
        self.model = model.upper()
        self.interval = "1m" if self.model == "A" else "5m"
        self.session_filter_enabled = session_filter
        self.is_running = True
        self.data_feed = HyperliquidDataFeed()
        self.last_update_time: float = time.time()

        # Configuration des 3 portefeuilles parallèles (A/B Testing)
        self.baskets: Dict[str, PaperBasket] = {
            "alpha": PaperBasket(
                key="alpha",
                name="Alpha Duo (SOL + SUI)",
                symbols=["SOL", "SUI"],
                initial_capital=initial_capital,
                model=self.model
            ),
            "quad": PaperBasket(
                key="quad",
                name="Quad Basket (BTC + SOL + MNT + SUI)",
                symbols=["BTC", "SOL", "MNT", "SUI"],
                initial_capital=initial_capital,
                model=self.model
            ),
            "core": PaperBasket(
                key="core",
                name="Core Duo (BTC + SOL)",
                symbols=["BTC", "SOL"],
                initial_capital=initial_capital,
                model=self.model
            )
        }

        # Panier actif visualisé par défaut : Alpha Duo
        self.active_basket_key = "alpha"

        # Symboles uniques à interroger sur le marché
        self.all_symbols: List[str] = sorted(list(set().union(*(b.symbols for b in self.baskets.values()))))
        self.current_market_prices: Dict[str, float] = {sym: 0.0 for sym in self.all_symbols}

    # =========================================================================
    # Propriétés de compatibilité ascendante (mappées sur le panier actif)
    # =========================================================================
    @property
    def active_basket(self) -> PaperBasket:
        return self.baskets.get(self.active_basket_key, self.baskets["alpha"])

    @property
    def symbols(self) -> List[str]:
        return self.active_basket.symbols

    @symbols.setter
    def symbols(self, sym_list: List[str]):
        self.active_basket.symbols = sym_list

    @property
    def symbol(self) -> str:
        return self.active_basket.symbols[0]

    @symbol.setter
    def symbol(self, s: str):
        if s in self.active_basket.symbols:
            self.active_basket.symbols.remove(s)
            self.active_basket.symbols.insert(0, s)

    @property
    def execution(self) -> ExecutionEngine:
        return self.active_basket.execution

    @property
    def professors(self) -> Dict[str, ProfessorAgent]:
        return self.active_basket.professors

    @property
    def professor(self) -> ProfessorAgent:
        sym = self.symbol
        if sym in self.active_basket.professors:
            return self.active_basket.professors[sym]
        return next(iter(self.active_basket.professors.values()))

    @property
    def closed_trades(self) -> List[Dict[str, Any]]:
        return self.active_basket.closed_trades

    @property
    def current_balance(self) -> float:
        return self.active_basket.current_balance

    @current_balance.setter
    def current_balance(self, val: float):
        self.active_basket.current_balance = val

    @property
    def current_market_price(self) -> float:
        return self.current_market_prices.get(self.symbol, 0.0)

    @current_market_price.setter
    def current_market_price(self, val: float):
        self.current_market_prices[self.symbol] = val

    def set_active_basket(self, basket_key: str) -> bool:
        """Change le panier actif pour l'affichage dans le dashboard."""
        if basket_key in self.baskets:
            self.active_basket_key = basket_key
            return True
        return False

    def check_session_window(self) -> Tuple[bool, str]:
        """
        Vérifie si l'heure actuelle est dans les sessions de haute liquidité (Londres / NY : 08:00 - 20:00 UTC).
        """
        if not self.session_filter_enabled:
            return True, "Filtre de session inactif (24h/24)"

        current_utc_hour = datetime.now(timezone.utc).hour
        if 8 <= current_utc_hour < 20:
            return True, f"Session active : Londres/New York ({current_utc_hour:02d}:00 UTC)"
        else:
            return False, f"Session Asiatique ({current_utc_hour:02d}:00 UTC) : Entrées suspendues par sécurité"

    def step(self) -> Dict[str, Any]:
        """
        Exécute un cycle de surveillance parallèle sur l'ensemble des 3 paniers.
        Les carnets d'ordres sont interrogés une seule fois par symbole pour une efficacité maximale.
        """
        self.last_update_time = time.time()

        # 1. Mise à jour des cours de marché pour chaque symbole unique
        for sym in self.all_symbols:
            best_bid, best_ask, spread = self.data_feed.fetch_order_book(sym)
            if best_bid > 0 and best_ask > 0:
                mid_px = (best_bid + best_ask) / 2.0
                self.current_market_prices[sym] = mid_px

        session_allowed, session_msg = self.check_session_window()

        # 2. Cycle pour chaque panier en parallèle
        for b_key, basket in self.baskets.items():
            # Mise à jour des positions actives si le marché a bougé
            if basket.execution.active_position:
                pos_sym = basket.execution.active_position.get("symbol")
                if pos_sym and self.current_market_prices.get(pos_sym, 0) > 0:
                    closed_trade = basket.execution.update_live_market_price(self.current_market_prices[pos_sym])
                    if closed_trade:
                        pnl = closed_trade["pnl_usd"]
                        basket.current_balance += pnl
                        for p in basket.professors.values():
                            p.balance = basket.current_balance
                            p.risk_mgr.update_balance(basket.current_balance)

                        risk_usd = closed_trade.get("notional_usd", 10.0) * 0.01
                        r_multiple = round(pnl / max(0.1, risk_usd), 2)
                        if pos_sym in basket.professors:
                            basket.professors[pos_sym].palermo.record_trade_result(r_multiple)

                        closed_trade["closed_balance"] = round(basket.current_balance, 2)
                        closed_trade["r_multiple"] = r_multiple
                        basket.closed_trades.append(closed_trade)

                        now_str = time.strftime("%H:%M:%S")
                        if pos_sym in basket.professors:
                            basket.professors[pos_sym].activity_log.append(
                                type("Msg", (), {
                                    "timestamp": now_str,
                                    "agent": "HELSINKI",
                                    "status": "CLEARED" if pnl >= 0 else "VETO",
                                    "message": f"[{basket.name}] Position {pos_sym} clôturée [{closed_trade['exit_reason']}] PnL: {pnl:+.2f}$ ({r_multiple:+.1f}R) | Solde: {basket.current_balance:.2f}$"
                                })()
                            )

            # Nettoyage des ordres limites expirés (> 3 min)
            basket.execution.cancel_stale_orders()

            # Si ce panier a déjà une position ou un ordre actif, ou si session fermée, ne pas chercher d'entrée
            if basket.execution.active_orders or basket.execution.active_position or not session_allowed:
                continue

            # Scanner les symboles propres à ce panier
            for sym in basket.symbols:
                mid_px = self.current_market_prices.get(sym, 0.0)
                if mid_px <= 0:
                    continue

                best_bid, best_ask, _ = self.data_feed.fetch_order_book(sym)
                if best_bid <= 0 or best_ask <= 0:
                    continue

                htf_df = self.data_feed.fetch_candles(sym, interval="1h", limit_candles=50)
                df = self.data_feed.fetch_candles(sym, interval=basket.interval, limit_candles=80)
                if df.empty or len(df) < 30:
                    continue

                latest_candle_time = int(df['timestamp'].iloc[-1])
                if latest_candle_time == basket.last_scanned_candle_times.get(sym, 0):
                    continue
                basket.last_scanned_candle_times[sym] = latest_candle_time

                # Délibération de la brigade d'agents pour ce symbole et ce panier
                if sym in basket.professors:
                    pipeline_result: DeskPipelineResult = basket.professors[sym].route(df, best_bid, best_ask, htf_df=htf_df)
                    if pipeline_result.approved and pipeline_result.proposal:
                        basket.execution.place_bracket_order(pipeline_result.proposal)
                        break  # Un ordre placé pour ce panier à ce cycle

        return self.get_state()

    def get_active_position_data(self) -> Optional[Dict[str, Any]]:
        """Calcule le PnL latent du panier actif."""
        return self.active_basket.get_active_position_data(self.current_market_prices)

    def get_state(self) -> Dict[str, Any]:
        """Retourne l'état complet du Paper Trading avec le récapitulatif comparatif de tous les paniers."""
        session_allowed, session_msg = self.check_session_window()
        active_b = self.active_basket

        baskets_summary = {}
        for k, b in self.baskets.items():
            b_data = b.get_summary(self.current_market_prices)
            b_data["is_active"] = (k == self.active_basket_key)
            baskets_summary[k] = b_data

        return {
            "is_running": self.is_running,
            "active_basket_key": self.active_basket_key,
            "active_basket_name": active_b.name,
            "model": self.model,
            "interval": self.interval,
            "current_balance": round(active_b.current_balance, 2),
            "initial_capital": active_b.initial_capital,
            "total_return_usd": round(active_b.current_balance - active_b.initial_capital, 2),
            "total_return_pct": round(((active_b.current_balance - active_b.initial_capital) / active_b.initial_capital) * 100, 2),
            "active_position": active_b.get_active_position_data(self.current_market_prices),
            "pending_orders": list(active_b.execution.active_orders.values()),
            "closed_trades_count": len(active_b.closed_trades),
            "win_rate_pct": active_b.get_win_rate(),
            "session_allowed": session_allowed,
            "session_message": session_msg,
            "palermo_halted": self.professor.palermo.is_halted,
            "portfolio_symbols": active_b.symbols,
            "market_prices": self.current_market_prices,
            "baskets": baskets_summary
        }
