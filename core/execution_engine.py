import time
from typing import Optional, Dict, Any, Union
from config.settings import (
    HYPERLIQUID_TESTNET,
    HYPERLIQUID_WALLET_ADDRESS,
    HYPERLIQUID_PRIVATE_KEY,
    ORDER_TIMEOUT_SECONDS,
    ORDER_TIMEOUT_MAP
)
from core.risk_manager import TradeOrderProposal


class ExecutionEngine:
    """
    Gestionnaire d'exécution des ordres sur Hyperliquid.
    Supporte le mode Testnet / Paper-trading et le mode Live.
    Gère les ordres limites (Maker), le suivi des Stop Loss et Take Profit.
    """
    def __init__(self, testnet: bool = HYPERLIQUID_TESTNET):
        self.testnet = testnet
        self.is_simulated = not bool(HYPERLIQUID_WALLET_ADDRESS and HYPERLIQUID_PRIVATE_KEY)
        self.active_orders: Dict[str, Any] = {}
        self.active_position: Optional[Dict[str, Any]] = None

    def place_bracket_order(self, proposal: TradeOrderProposal, timeframe: str = "5m") -> Dict[str, Any]:
        """
        Place un ordre limite d'entrée avec gestion institutionnelle en 3 tiers :
        Tier 1 (+1.0R, 33%) -> Activation du True Breakeven (+ fees nettes)
        Tier 2 (+3.0R, 33%) -> Verrouillage du Stop Loss à +1.0R
        Tier 3 (34%) -> Trailing Stop dynamique structurel & ATR
        Calcule un délai d'expiration adapté à la timeframe et à la qualité du setup SMC.
        """
        order_id = f"HL_{proposal.symbol}_{int(time.time()*1000)}"
        risk_dist = abs(proposal.entry_price - proposal.stop_loss)
        tp1 = proposal.take_profit_1r if proposal.take_profit_1r > 0 else (proposal.entry_price + risk_dist if proposal.is_long else proposal.entry_price - risk_dist)
        tp2 = proposal.take_profit_2r if proposal.take_profit_2r > 0 else proposal.take_profit
        true_be = proposal.true_be_price if proposal.true_be_price > 0 else (
            round(proposal.entry_price + (proposal.entry_price * 0.0008 + 1.0), 2) if proposal.is_long else round(proposal.entry_price - (proposal.entry_price * 0.0008 + 1.0), 2)
        )

        t1_sz = round(proposal.position_size * 0.33, 6)
        t2_sz = round(proposal.position_size * 0.33, 6)
        t3_sz = round(proposal.position_size - t1_sz - t2_sz, 6)
        entry_fee = proposal.entry_price * proposal.position_size * 0.0002

        # Délai d'expiration adapté à la timeframe (1m=15min, 3m=30min, 5m=45min, 15m=90min)
        tf_timeout = ORDER_TIMEOUT_MAP.get(timeframe, ORDER_TIMEOUT_SECONDS)
        # Pour les setups 5 étoiles (avec prior liquidity sweep), accorder plus de patience (+50%)
        is_5_star = getattr(proposal, "has_prior_sweep", False) or "5_STAR" in getattr(proposal, "grade", "")
        if is_5_star:
            tf_timeout = int(tf_timeout * 1.5)

        order_data = {
            "order_id": order_id,
            "symbol": proposal.symbol,
            "is_long": proposal.is_long,
            "entry_price": proposal.entry_price,
            "initial_stop_loss": proposal.stop_loss,
            "stop_loss": proposal.stop_loss,
            "take_profit_1r": round(tp1, 2),
            "take_profit_2r": round(tp2, 2),
            "take_profit": round(tp2, 2),
            "true_be_price": round(true_be, 2),
            "size": proposal.position_size,
            "initial_size": proposal.position_size,
            "remaining_size": proposal.position_size,
            "t1_size": t1_sz,
            "t2_size": t2_sz,
            "t3_size": t3_sz,
            "notional_usd": proposal.notional_value,
            "status": "PLACED_LIMIT_MAKER",
            "created_at": time.time(),
            "simulated": self.is_simulated,
            "tp1_hit": False,
            "tp2_hit": False,
            "be_activated": False,
            "accumulated_pnl": 0.0,
            "fees_paid": entry_fee,
            "grade": proposal.grade,
            "has_prior_sweep": proposal.has_prior_sweep,
            "timeframe": timeframe,
            "timeout_seconds": tf_timeout
        }

        self.active_orders[order_id] = order_data
        timeout_min = tf_timeout // 60
        print(f"[Execution Engine] Ordre Maker placé : {order_id} | {'LONG' if proposal.is_long else 'SHORT'} {proposal.position_size} {proposal.symbol} @ {proposal.entry_price}$ (SL: {proposal.stop_loss}$, TP1: {tp1:.1f}$, TP2: {tp2:.1f}$ | Validité: {timeout_min} min)")
        return order_data

    def cancel_stale_orders(self, current_market_prices: Optional[Dict[str, float]] = None) -> int:
        """
        Annule les ordres limites non exécutés après expiration de leur délai adapté.
        Annule également de façon proactive si l'objectif Take Profit a été atteint avant l'exécution ("missed train").
        """
        now = time.time()
        cancelled_count = 0
        to_remove = []

        for oid, order in list(self.active_orders.items()):
            timeout = order.get("timeout_seconds", ORDER_TIMEOUT_SECONDS)
            is_expired = (now - order["created_at"]) > timeout

            # Invalidation proactive SMC : si le cours a déjà rallié le Take Profit sans nous exécuter
            is_missed_train = False
            if current_market_prices and isinstance(current_market_prices, dict):
                sym = order.get("symbol")
                cur_px = current_market_prices.get(sym, 0.0)
                if cur_px > 0:
                    if order["is_long"] and cur_px >= order["take_profit"]:
                        is_missed_train = True
                    elif not order["is_long"] and cur_px <= order["take_profit"]:
                        is_missed_train = True

            if is_expired or is_missed_train:
                to_remove.append(oid)
                cancelled_count += 1
                reason = "Objectif TP atteint sans nous (Missed Train)" if is_missed_train else f"Expiration ({timeout//60} min)"
                print(f"[Execution Engine] Ordre limite annulé [{reason}] : {oid}")

        for oid in to_remove:
            del self.active_orders[oid]

        return cancelled_count

    def update_live_market_price(self, current_price: Union[float, Dict[str, float]]) -> Optional[Dict[str, Any]]:
        """
        Simule le remplissage des ordres limites et applique la gestion dynamique en 3 tiers
        avec armement automatique du True Breakeven et trailing runner en live.
        Supporte soit un prix unitaire (float), soit un dictionnaire de prix par symbole (dict).
        """
        if not self.active_orders and not self.active_position:
            return None

        price_dict = current_price if isinstance(current_price, dict) else {}

        # 1. Vérification des ordres limites en attente
        to_fill = []
        for oid, order in list(self.active_orders.items()):
            sym = order.get("symbol")
            px = price_dict.get(sym, current_price) if isinstance(current_price, dict) else current_price
            if px is None or not isinstance(px, (int, float)) or px <= 0:
                continue
            if order["is_long"] and px <= order["entry_price"]:
                to_fill.append(oid)
            elif not order["is_long"] and px >= order["entry_price"]:
                to_fill.append(oid)

        for oid in to_fill:
            order = self.active_orders.pop(oid)
            order["status"] = "FILLED"
            order["fill_price"] = order["entry_price"]
            order["fill_time"] = time.time()
            self.active_position = order
            print(f"[Execution Engine] ⚡ Ordre exécuté (Filled) : {oid} au prix de {order['entry_price']}$")

        # 2. Vérification de la position ouverte
        if self.active_position:
            pos = self.active_position
            pos_sym = pos.get("symbol")
            pos_px = price_dict.get(pos_sym, current_price) if isinstance(current_price, dict) else current_price
            if pos_px is None or not isinstance(pos_px, (int, float)) or pos_px <= 0:
                return None
            current_price = pos_px

            is_long = pos["is_long"]
            entry_px = pos["entry_price"]
            risk_dist = abs(entry_px - pos["initial_stop_loss"])
            maker_fee_pct = 0.0002
            taker_fee_pct = 0.0005

            # A. Vérification Tier 1 (+1.0R, 33%) et armement du True Breakeven
            if not pos["tp1_hit"]:
                hit_tp1 = (current_price >= pos["take_profit_1r"]) if is_long else (current_price <= pos["take_profit_1r"])
                if hit_tp1:
                    t1_sz = pos["t1_size"]
                    pos["remaining_size"] = round(pos["remaining_size"] - t1_sz, 6)
                    pos["tp1_hit"] = True
                    diff_tp1 = (pos["take_profit_1r"] - entry_px) if is_long else (entry_px - pos["take_profit_1r"])
                    fee_tp1 = pos["take_profit_1r"] * t1_sz * maker_fee_pct
                    pnl_tp1 = (diff_tp1 * t1_sz) - fee_tp1
                    pos["accumulated_pnl"] += pnl_tp1
                    pos["fees_paid"] += fee_tp1
                    pos["be_activated"] = True
                    pos["stop_loss"] = pos["true_be_price"]
                    print(f"[Execution Engine] 💰 Tier 1 (+1.0R) validé @ {pos['take_profit_1r']}$ ! 33% encaissé (+{pnl_tp1:.2f}$). True Breakeven armé à {pos['true_be_price']}$")

            # B. Vérification Tier 2 (+3.0R, 33%) et sécurisation du Runner
            if pos["tp1_hit"] and not pos["tp2_hit"]:
                hit_tp2 = (current_price >= pos["take_profit_2r"]) if is_long else (current_price <= pos["take_profit_2r"])
                if hit_tp2:
                    t2_sz = pos["t2_size"]
                    pos["remaining_size"] = round(pos["remaining_size"] - t2_sz, 6)
                    pos["tp2_hit"] = True
                    diff_tp2 = (pos["take_profit_2r"] - entry_px) if is_long else (entry_px - pos["take_profit_2r"])
                    fee_tp2 = pos["take_profit_2r"] * t2_sz * maker_fee_pct
                    pnl_tp2 = (diff_tp2 * t2_sz) - fee_tp2
                    pos["accumulated_pnl"] += pnl_tp2
                    pos["fees_paid"] += fee_tp2
                    pos["stop_loss"] = pos["take_profit_1r"]
                    print(f"[Execution Engine] 🎯 Tier 2 (+3.0R) validé @ {pos['take_profit_2r']}$ ! 33% encaissé (+{pnl_tp2:.2f}$). Runner verrouillé à {pos['take_profit_1r']}$")

            # C. Trailing Stop dynamique sur le Tier 3 Runner (34%)
            if pos["tp2_hit"]:
                local_trail_dist = max(0.50 * risk_dist, entry_px * 0.001)
                if is_long:
                    cand_trail = current_price - (1.2 * local_trail_dist)
                    if cand_trail > pos["stop_loss"]:
                        pos["stop_loss"] = round(cand_trail, 4 if entry_px < 10.0 else 2)
                else:
                    cand_trail = current_price + (1.2 * local_trail_dist)
                    if cand_trail < pos["stop_loss"]:
                        pos["stop_loss"] = round(cand_trail, 4 if entry_px < 10.0 else 2)

            # D. Vérification de sortie du solde restant (SL / True BE / Runner Trail / Full TP)
            hit_sl = (current_price <= pos["stop_loss"]) if is_long else (current_price >= pos["stop_loss"])
            hit_full_tp = (current_price >= pos["take_profit"]) if is_long else (current_price <= pos["take_profit"])

            if hit_sl or pos["remaining_size"] <= 1e-7:
                exit_price = pos["stop_loss"]
                rem_sz = pos["remaining_size"]
                if pos["tp2_hit"]:
                    exit_reason = "RUNNER_TRAIL"
                elif pos["tp1_hit"]:
                    be_tol = entry_px * 0.0005 if entry_px < 10.0 else 5.0
                    exit_reason = "BE" if abs(exit_price - pos["true_be_price"]) < be_tol else "PROFIT_LOCK"
                else:
                    exit_reason = "SL"

                if rem_sz > 1e-7:
                    fee_exit = exit_price * rem_sz * (maker_fee_pct if exit_reason == "RUNNER_TRAIL" else taker_fee_pct)
                    diff_rem = (exit_price - entry_px) if is_long else (entry_px - exit_price)
                    pnl_rem = (diff_rem * rem_sz) - fee_exit
                    pos["accumulated_pnl"] += pnl_rem
                    pos["fees_paid"] += fee_exit

                total_pnl = round(pos["accumulated_pnl"], 2)
                closed_trade = {
                    **pos,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_usd": total_pnl,
                    "fees_usd": round(pos["fees_paid"], 4),
                    "closed_at": time.time(),
                    "be_activated": pos["be_activated"],
                    "tp1_hit": pos["tp1_hit"],
                    "tp2_hit": pos["tp2_hit"]
                }
                self.active_position = None
                print(f"[Execution Engine] 🎯 Position fermée : [{exit_reason}] @ {exit_price}$ | PnL Total: {total_pnl:+.2f}$ (Frais: {closed_trade['fees_usd']}$)")
                return closed_trade

            elif hit_full_tp and not pos["tp2_hit"]:
                exit_price = pos["take_profit"]
                rem_sz = pos["remaining_size"]
                fee_exit = exit_price * rem_sz * maker_fee_pct
                diff_rem = (exit_price - entry_px) if is_long else (entry_px - exit_price)
                pnl_rem = (diff_rem * rem_sz) - fee_exit
                pos["accumulated_pnl"] += pnl_rem
                pos["fees_paid"] += fee_exit
                total_pnl = round(pos["accumulated_pnl"], 2)
                closed_trade = {
                    **pos,
                    "exit_price": exit_price,
                    "exit_reason": "TP",
                    "pnl_usd": total_pnl,
                    "fees_usd": round(pos["fees_paid"], 4),
                    "closed_at": time.time(),
                    "be_activated": pos["be_activated"],
                    "tp1_hit": True,
                    "tp2_hit": True
                }
                self.active_position = None
                print(f"[Execution Engine] 🎯 Position fermée : [TP] @ {exit_price}$ | PnL Total: {total_pnl:+.2f}$")
                return closed_trade

        return None
