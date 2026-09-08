import time
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DEFAULT_SYMBOL, INITIAL_CAPITAL_USD
from config.smc_params import ASIA_SESSION_RESTRICT_ENTRIES
from core.data_feed import HyperliquidDataFeed, CACHE_DIR
from core.execution_engine import ExecutionEngine
from bots.agents.desk_team import ProfessorAgent, DeskPipelineResult
from bots.notifications import NotificationManager

STATE_FILE = CACHE_DIR / "paper_trading_state.json"



class PaperStrategyTrack:
    """
    Sous-portefeuille de stratégie isolé (Scalp M1/M3, Intraday M5, ou Day M15) au sein d'un panier d'actifs.
    Capital dédié indépendant (100$), positions et métriques autonomes.
    """
    def __init__(
        self,
        strategy_id: str,
        name: str,
        symbols: List[str],
        interval: str,
        htf_interval: str,
        model: str = "B",
        initial_capital: float = INITIAL_CAPITAL_USD
    ):
        self.strategy_id = strategy_id
        self.name = name
        self.symbols = symbols
        self.interval = interval
        self.htf_interval = htf_interval
        self.model = model.upper()
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
        ret_usd = round(self.current_balance - self.initial_capital, 2)
        ret_pct = round((ret_usd / self.initial_capital) * 100, 2)
        pos = self.get_active_position_data(market_prices)

        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "interval": self.interval,
            "htf_interval": self.htf_interval,
            "model": self.model,
            "current_balance": round(self.current_balance, 2),
            "initial_capital": self.initial_capital,
            "total_return_usd": ret_usd,
            "total_return_pct": ret_pct,
            "closed_trades_count": len(self.closed_trades),
            "win_rate_pct": self.get_win_rate(),
            "active_position": pos,
            "pending_orders": list(self.execution.active_orders.values())
        }


class PaperBasket:
    """
    Portefeuille de Paper Trading isolé pour l'A/B Testing en direct.
    Gère son propre capital, ses positions, ses ordres et son historique de trades.
    Exécute en parallèle 3 stratégies indépendantes (Scalp, Intraday, Day Trading).
    """
    def __init__(
        self,
        key: str,
        name: str,
        symbols: List[str],
        initial_capital: float = INITIAL_CAPITAL_USD,
        model: str = "B",
        interval: Optional[str] = None,
        htf_interval: Optional[str] = None
    ):
        self.key = key
        self.name = name
        self.symbols = symbols
        self.initial_capital = initial_capital

        scalp_int = "3m" if key == "quad" else "1m"
        scalp_htf = "30m" if key == "quad" else "15m"

        self.strategies: Dict[str, PaperStrategyTrack] = {
            "scalp": PaperStrategyTrack(
                strategy_id="scalp",
                name=f"Scalp Ultra-Court ({scalp_int})",
                symbols=symbols,
                interval=scalp_int,
                htf_interval=scalp_htf,
                model="A",
                initial_capital=initial_capital
            ),
            "intraday": PaperStrategyTrack(
                strategy_id="intraday",
                name="Intraday Structure (5m)",
                symbols=symbols,
                interval="5m",
                htf_interval="1h",
                model="B",
                initial_capital=initial_capital
            ),
            "day": PaperStrategyTrack(
                strategy_id="day",
                name="Day Trading / Swing (15m)",
                symbols=symbols,
                interval="15m",
                htf_interval="4h",
                model="B",
                initial_capital=initial_capital
            )
        }

        if interval:
            if interval in ["1m", "3m"]:
                self.active_strategy_id = "scalp"
            elif interval == "15m":
                self.active_strategy_id = "day"
            else:
                self.active_strategy_id = "intraday"
        else:
            self.active_strategy_id = "scalp" if model.upper() == "A" else "intraday"

    @property
    def primary_track(self) -> PaperStrategyTrack:
        return self.strategies.get(self.active_strategy_id, self.strategies["intraday"])

    @property
    def current_balance(self) -> float:
        return self.primary_track.current_balance

    @current_balance.setter
    def current_balance(self, val: float):
        self.primary_track.current_balance = float(val)

    @property
    def closed_trades(self) -> List[Dict[str, Any]]:
        return self.primary_track.closed_trades

    @closed_trades.setter
    def closed_trades(self, val: List[Dict[str, Any]]):
        self.primary_track.closed_trades = val

    @property
    def execution(self) -> ExecutionEngine:
        return self.primary_track.execution

    @property
    def professors(self) -> Dict[str, ProfessorAgent]:
        return self.primary_track.professors

    @property
    def model(self) -> str:
        return self.primary_track.model

    @model.setter
    def model(self, val: str):
        self.primary_track.model = val.upper()

    @property
    def interval(self) -> str:
        return self.primary_track.interval

    @interval.setter
    def interval(self, val: str):
        self.primary_track.interval = val

    @property
    def htf_interval(self) -> str:
        return self.primary_track.htf_interval

    @htf_interval.setter
    def htf_interval(self, val: str):
        self.primary_track.htf_interval = val

    @property
    def last_scanned_candle_times(self) -> Dict[str, int]:
        return self.primary_track.last_scanned_candle_times

    def get_win_rate(self) -> float:
        return self.primary_track.get_win_rate()

    def get_active_position_data(self, market_prices: Dict[str, float]) -> Optional[Dict[str, Any]]:
        return self.primary_track.get_active_position_data(market_prices)

    def get_summary(self, market_prices: Dict[str, float]) -> Dict[str, Any]:
        """Retourne le résumé complet des métriques du portefeuille et de ses 3 stratégies parallèles."""
        summary = self.primary_track.get_summary(market_prices)
        summary["key"] = self.key
        summary["name"] = self.name
        summary["symbols"] = self.symbols
        summary["active_strategy_id"] = self.active_strategy_id
        summary["strategies"] = {
            s_id: s.get_summary(market_prices) for s_id, s in self.strategies.items()
        }
        return summary


class PaperTradingDaemon:
    """
    Démon Autonome de Paper Trading en Temps Réel avec A/B Testing Multi-Paniers et Persistance Disque.
    Fait tourner en parallèle 3 portefeuilles indépendants :
      1. Alpha Duo : SOL + SUI (Meilleure performance backtest +66.7%)
      2. Quad Basket : BTC + SOL + MNT + SUI (Diversification maximale & Bogota Arbitrage)
      3. Core Duo : BTC + SOL (Benchmark institutionnel de référence)
    Sauvegarde automatiquement l'historique et les soldes pour résister aux redémarrages serveur.
    """
    def __init__(
        self,
        symbol: str = DEFAULT_SYMBOL,
        symbols: Optional[List[str]] = None,
        model: str = "B",
        initial_capital: float = INITIAL_CAPITAL_USD,
        session_filter: bool = ASIA_SESSION_RESTRICT_ENTRIES,
        state_file: Optional[Path] = None
    ):
        self.initial_capital = initial_capital
        self.model = model.upper()
        self.interval = "1m" if self.model == "A" else "5m"
        self.session_filter_enabled = session_filter
        self.is_running = True
        self.data_feed = HyperliquidDataFeed()
        self.last_update_time: float = time.time()
        self.state_file = state_file or STATE_FILE

        # Configuration des 3 portefeuilles parallèles (A/B Testing Multi-Stratégies)
        self.baskets: Dict[str, PaperBasket] = {
            "alpha": PaperBasket(
                key="alpha",
                name="Alpha Duo (SOL + SUI)",
                symbols=["SOL", "SUI"],
                initial_capital=initial_capital,
                model="A",
                interval="1m",
                htf_interval="15m"
            ),
            "quad": PaperBasket(
                key="quad",
                name="Quad Basket (BTC + SOL + MNT + SUI)",
                symbols=["BTC", "SOL", "MNT", "SUI"],
                initial_capital=initial_capital,
                model="B",
                interval="5m",
                htf_interval="1h"
            ),
            "core": PaperBasket(
                key="core",
                name="Core Duo (BTC + SOL)",
                symbols=["BTC", "SOL"],
                initial_capital=initial_capital,
                model="B",
                interval="15m",
                htf_interval="4h"
            )
        }

        # Panier actif visualisé par défaut : Alpha Duo
        self.active_basket_key = "alpha"

        # Symboles uniques à interroger sur le marché
        self.all_symbols: List[str] = sorted(list(set().union(*(b.symbols for b in self.baskets.values()))))
        self.current_market_prices: Dict[str, float] = {sym: 0.0 for sym in self.all_symbols}

        # Gestionnaire de notifications temps réel (Discord / Telegram)
        self.notifier = NotificationManager()

        # Restauration automatique de l'état persistant si disponible sur le disque
        self.load_state(self.state_file)


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
        """Change le panier actif pour l'affichage dans le dashboard et sauvegarde l'état."""
        if basket_key in self.baskets:
            self.active_basket_key = basket_key
            self.save_state(self.state_file)
            return True
        return False

    # =========================================================================
    # Persistance Disque & Auto-Save
    # =========================================================================
    def save_state(self, file_path: Optional[Path] = None) -> bool:
        """Sauvegarde l'état complet des 3 portefeuilles de façon atomique sur le disque."""
        target = file_path or self.state_file
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "saved_at": time.time(),
                "saved_str": datetime.now(timezone.utc).isoformat(),
                "active_basket_key": self.active_basket_key,
                "baskets": {}
            }
            for k, b in self.baskets.items():
                data["baskets"][k] = {
                    "key": b.key,
                    "name": b.name,
                    "symbols": b.symbols,
                    "current_balance": round(b.current_balance, 2),
                    "initial_capital": b.initial_capital,
                    "closed_trades": b.closed_trades,
                    "active_position": b.execution.active_position,
                    "active_orders": b.execution.active_orders,
                    "strategies": {
                        s_id: {
                            "current_balance": round(s.current_balance, 2),
                            "closed_trades": s.closed_trades,
                            "active_position": s.execution.active_position,
                            "active_orders": s.execution.active_orders
                        } for s_id, s in b.strategies.items()
                    }
                }
            tmp = target.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp.replace(target)
            return True
        except Exception as e:
            print(f"[Paper Trading Daemon] Erreur sauvegarde état: {e}")
            return False

    def load_state(self, file_path: Optional[Path] = None) -> bool:
        """Restaure les soldes, l'historique et les positions ouvertes depuis le disque."""
        target = file_path or self.state_file
        if not target.exists():
            return False
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)

            saved_baskets = data.get("baskets", {})
            for k, b in self.baskets.items():
                if k in saved_baskets:
                    b_info = saved_baskets[k]
                    b.current_balance = float(b_info.get("current_balance", b.initial_capital))
                    b.closed_trades = b_info.get("closed_trades", [])

                    pos = b_info.get("active_position")
                    if pos:
                        b.execution.active_position = pos

                    orders = b_info.get("active_orders")
                    if orders and isinstance(orders, dict):
                        b.execution.active_orders = orders

                    # Restaurer les sous-stratégies si présentes
                    saved_strats = b_info.get("strategies", {})
                    for s_id, s in b.strategies.items():
                        if s_id in saved_strats:
                            s_info = saved_strats[s_id]
                            s.current_balance = float(s_info.get("current_balance", s.initial_capital))
                            s.closed_trades = s_info.get("closed_trades", [])
                            if s_info.get("active_position"):
                                s.execution.active_position = s_info["active_position"]
                            if s_info.get("active_orders"):
                                s.execution.active_orders = s_info["active_orders"]

                    for p in b.professors.values():
                        p.balance = b.current_balance
                        p.risk_mgr.update_balance(b.current_balance)

            saved_key = data.get("active_basket_key")
            if saved_key and saved_key in self.baskets:
                self.active_basket_key = saved_key

            print(f"[Paper Trading Daemon] État persistant restauré depuis {target.name}")
            return True
        except Exception as e:
            print(f"[Paper Trading Daemon] Erreur chargement état persistant: {e}")
            return False

    def reset_state(self, file_path: Optional[Path] = None) -> Dict[str, Any]:
        """Réinitialise tous les portefeuilles et stratégies à 100$ et efface les données sauvegardées."""
        for b in self.baskets.values():
            for s in b.strategies.values():
                s.current_balance = s.initial_capital
                s.closed_trades = []
                s.execution.active_position = None
                s.execution.active_orders.clear()
                for p in s.professors.values():
                    p.balance = s.initial_capital
                    p.risk_mgr.update_balance(s.initial_capital)
                    p.palermo.consecutive_losses = 0
                    p.palermo.daily_realized_r = 0.0
                    p.palermo.is_halted = False
            b.current_balance = b.initial_capital
            b.closed_trades = []
            b.execution.active_position = None
            b.execution.active_orders.clear()
        target = file_path or self.state_file
        if target.exists():
            try:
                target.unlink()
            except Exception:
                pass
        self.save_state(file_path=target)
        return self.get_state()

    def check_session_window(self) -> Tuple[bool, str]:
        """
        Vérifie si l'heure actuelle est dans les sessions de haute liquidité (Londres / NY : 07:00 - 21:00 UTC).
        Couvre le pré-open Londres (09h00 Paris) jusqu'à la clôture US (23h00 Paris).
        """
        if not self.session_filter_enabled:
            return True, "Filtre de session inactif (24h/24)"

        current_utc_hour = datetime.now(timezone.utc).hour
        if 7 <= current_utc_hour < 21:
            return True, f"Session active : Londres/New York ({current_utc_hour:02d}:00 UTC)"
        else:
            return False, f"Session Asiatique ({current_utc_hour:02d}:00 UTC) : Entrées suspendues par sécurité"

    def step(self) -> Dict[str, Any]:
        """
        Exécute un cycle de surveillance parallèle sur l'ensemble des 3 paniers et leurs 3 stratégies (Scalp, Intraday, Day).
        Grâce au cache mémoire des bougies et carnets, chaque coin n'est interrogé qu'une fois par cycle.
        """
        self.last_update_time = time.time()
        state_changed = False

        # 1. Mise à jour des cours de marché pour chaque symbole unique
        for sym in self.all_symbols:
            best_bid, best_ask, spread = self.data_feed.fetch_order_book(sym)
            if best_bid > 0 and best_ask > 0:
                mid_px = (best_bid + best_ask) / 2.0
                self.current_market_prices[sym] = mid_px

        session_allowed, session_msg = self.check_session_window()

        # 2. Cycle pour chaque panier et chaque stratégie en parallèle
        for b_key, basket in self.baskets.items():
            for strat_id, strat in basket.strategies.items():
                had_active_pos = bool(strat.execution.active_position)

                # Mise à jour des ordres limites en attente et des positions actives
                if strat.execution.active_orders or strat.execution.active_position:
                    closed_trade = strat.execution.update_live_market_price(self.current_market_prices)
                    if closed_trade:
                        pnl = closed_trade["pnl_usd"]
                        strat.current_balance += pnl
                        for p in strat.professors.values():
                            p.balance = strat.current_balance
                            p.risk_mgr.update_balance(strat.current_balance)

                        risk_usd = closed_trade.get("notional_usd", 10.0) * 0.01
                        r_multiple = round(pnl / max(0.1, risk_usd), 2)
                        pos_sym = closed_trade.get("symbol", strat.symbols[0])
                        if pos_sym in strat.professors:
                            strat.professors[pos_sym].palermo.record_trade_result(r_multiple)

                        closed_trade["closed_balance"] = round(strat.current_balance, 2)
                        closed_trade["r_multiple"] = r_multiple
                        strat.closed_trades.append(closed_trade)
                        state_changed = True

                        # Alerte mobile de trade clôturé
                        tag = f"{basket.name} • {strat.name}"
                        self.notifier.notify_trade_closed(tag, closed_trade)

                        now_str = time.strftime("%H:%M:%S")
                        if pos_sym in strat.professors:
                            strat.professors[pos_sym].activity_log.append(
                                type("Msg", (), {
                                    "timestamp": now_str,
                                    "agent": "HELSINKI",
                                    "status": "CLEARED" if pnl >= 0 else "VETO",
                                    "message": f"[{tag}] Position {pos_sym} clôturée [{closed_trade['exit_reason']}] PnL: {pnl:+.2f}$ ({r_multiple:+.1f}R) | Solde: {strat.current_balance:.2f}$"
                                })()
                            )

                # Notification si un ordre limite vient d'être exécuté (Filled)
                if not had_active_pos and strat.execution.active_position:
                    tag = f"{basket.name} • {strat.name}"
                    self.notifier.notify_position_filled(tag, strat.execution.active_position)
                    state_changed = True

                # Notification si le True Breakeven vient d'être activé
                if strat.execution.active_position and strat.execution.active_position.get("be_activated") and not strat.execution.active_position.get("_be_notified"):
                    tag = f"{basket.name} • {strat.name}"
                    self.notifier.notify_breakeven_activated(tag, strat.execution.active_position)
                    strat.execution.active_position["_be_notified"] = True

                # Nettoyage des ordres limites expirés ou invalidés (Missed Train)
                canceled_count = strat.execution.cancel_stale_orders(self.current_market_prices)
                if canceled_count > 0:
                    state_changed = True

                # Si cette stratégie a déjà une position ou un ordre actif, ou si session fermée, ne pas chercher d'entrée
                if strat.execution.active_orders or strat.execution.active_position or not session_allowed:
                    continue

                # Scanner les symboles propres à cette stratégie
                for sym in strat.symbols:
                    mid_px = self.current_market_prices.get(sym, 0.0)
                    if mid_px <= 0:
                        continue

                    best_bid, best_ask, _ = self.data_feed.fetch_order_book(sym)
                    if best_bid <= 0 or best_ask <= 0:
                        continue

                    htf_df = self.data_feed.fetch_candles(sym, interval=strat.htf_interval, limit_candles=100)
                    df = self.data_feed.fetch_candles(sym, interval=strat.interval, limit_candles=200)
                    if df.empty or len(df) < 30:
                        continue

                    latest_candle_time = int(df['timestamp'].iloc[-1])
                    if latest_candle_time == strat.last_scanned_candle_times.get(sym, 0):
                        continue
                    strat.last_scanned_candle_times[sym] = latest_candle_time

                    # Délibération de la brigade d'agents pour ce symbole et cette stratégie
                    if sym in strat.professors:
                        pipeline_result: DeskPipelineResult = strat.professors[sym].route(df, best_bid, best_ask, htf_df=htf_df)
                        if pipeline_result.approved and pipeline_result.proposal:
                            order_ticket = strat.execution.place_bracket_order(pipeline_result.proposal, timeframe=strat.interval)
                            tag = f"{basket.name} • {strat.name}"
                            self.notifier.notify_order_placed(tag, order_ticket)
                            state_changed = True
                            break  # Un ordre placé pour cette stratégie à ce cycle


        if state_changed:
            self.save_state(self.state_file)

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
            "closed_trades": active_b.closed_trades,
            "closed_trades_count": len(active_b.closed_trades),
            "win_rate_pct": active_b.get_win_rate(),
            "session_allowed": session_allowed,
            "session_message": session_msg,
            "palermo_halted": self.professor.palermo.is_halted,
            "portfolio_symbols": active_b.symbols,
            "market_prices": self.current_market_prices,
            "baskets": baskets_summary
        }
