import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np

from core.smc_engine import SMCEngine, SMCSetupCandidate, TrendDirection
from core.risk_manager import RiskManager
from backtester.engine import TradeRecord, calculate_backtest_metrics
from backtester.metrics import BacktestReport


class MultiAssetPortfolioEngine:
    """
    Moteur de Backtest & Simulation de Portefeuille Multi-Actifs (BTC, ETH, SOL, BNB, MNT).
    - Exécute une simulation temporelle synchronisée tick-par-tick (ou bougie 5m par bougie 5m).
    - Plafonne le risque global à N positions actives simultanées (ex: 3 max).
    - Arbitre les signaux simultanés par ordre de conviction (Sweep > OB > FVG).
    - Exécute la stratégie 3 Paliers institutionnelle :
        * Tier 1 (33% @ +1.0R) -> Arme le True Breakeven (+ fees nettes)
        * Tier 2 (33% @ +3.0R) -> Verrouille le stop au prix TP1
        * Tier 3 (34% Runner Trailing) -> Maximise les tendances majeures
    - Filtre optionnel de session institutionnelle (08:00 - 20:00 UTC).
    """
    def __init__(
        self,
        initial_capital: float = 100.0,
        max_concurrent_positions: int = 3,
        risk_per_trade_sweep: float = 0.007,  # 0.70% sur Sweep
        risk_per_trade_cont: float = 0.004,   # 0.40% sur Continuation
        min_rr: float = 2.0,
        session_filter: bool = True,
        time_stop_bars: int = 25,
        maker_fee_pct: float = 0.0002,
        taker_fee_pct: float = 0.0005,
        cooldown_minutes: int = 60
    ):
        self.initial_capital = initial_capital
        self.max_concurrent_positions = max_concurrent_positions
        self.risk_sweep = risk_per_trade_sweep
        self.risk_cont = risk_per_trade_cont
        self.min_rr = min_rr
        self.session_filter = session_filter
        self.time_stop_bars = time_stop_bars
        self.maker_fee_pct = maker_fee_pct
        self.taker_fee_pct = taker_fee_pct
        self.cooldown_ms = cooldown_minutes * 60 * 1000

        self.risk_mgr = RiskManager(
            current_balance=initial_capital,
            risk_pct=self.risk_sweep,
            min_rr=min_rr
        )

    def run(
        self,
        market_data: Dict[str, Dict[str, pd.DataFrame]],
        warmup_candles: int = 50
    ) -> Dict[str, Any]:
        """
        Exécute la simulation synchronisée sur l'ensemble des paires.
        market_data format:
        {
            "BTC": {"ltf": df_5m, "htf": df_1h},
            "ETH": {"ltf": df_5m, "htf": df_1h},
            ...
        }
        """
        symbols = list(market_data.keys())
        smc_instances = {sym: SMCEngine() for sym in symbols}

        # 1. Aligner les séries temporelles sur l'union des timestamps LTF
        candle_maps: Dict[str, Dict[int, Dict[str, float]]] = {}
        all_timestamps_set = set()

        for sym in symbols:
            ltf_df = market_data[sym]["ltf"]
            sym_map = {}
            for row in ltf_df.itertuples():
                ts = int(row.timestamp)
                sym_map[ts] = {
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume)
                }
                all_timestamps_set.add(ts)
            candle_maps[sym] = sym_map

        sorted_timestamps = sorted(list(all_timestamps_set))
        if len(sorted_timestamps) < warmup_candles + 10:
            return {"error": "Pas assez de données pour le warmup"}

        # États de suivi du portefeuille
        current_balance = self.initial_capital
        equity_curve: List[Dict[str, Any]] = [
            {"timestamp": sorted_timestamps[0], "balance": current_balance, "open_positions": 0}
        ]

        active_positions: Dict[str, Dict[str, Any]] = {}
        all_trades: List[TradeRecord] = []
        trades_by_symbol: Dict[str, List[TradeRecord]] = {sym: [] for sym in symbols}
        last_exit_times: Dict[str, int] = {sym: 0 for sym in symbols}
        trade_counter = 0
        last_day: Optional[int] = None

        # Indexations pré-calculées pour vitesse maximale
        htf_times_dict = {}
        for sym in symbols:
            htf_df = market_data[sym].get("htf")
            if htf_df is not None and not htf_df.empty:
                htf_times_dict[sym] = htf_df["timestamp"].values
            else:
                htf_times_dict[sym] = None

        # Boucle temporelle synchronisée universelle
        for i in range(warmup_candles, len(sorted_timestamps)):
            current_time = sorted_timestamps[i]
            current_day = current_time // (24 * 3600 * 1000)

            if last_day is not None and current_day != last_day:
                self.risk_mgr.reset_daily_stats()
            last_day = current_day

            # ─── ÉTAPE A : Mise à jour & Sorties des Positions Ouvertes ───
            closed_this_bar = []
            for sym, pos in list(active_positions.items()):
                bar_data = candle_maps[sym].get(current_time)
                if not bar_data:
                    continue

                c_high = bar_data["high"]
                c_low = bar_data["low"]
                c_close = bar_data["close"]

                pos["bars_held"] += 1
                is_long = pos["is_long"]
                entry_px = pos["entry_price"]
                sl = pos["stop_loss"]
                tp1 = pos["take_profit_1r"]
                tp2 = pos["take_profit_2r"]
                risk_dist = pos["risk_dist"]

                # 1. Tier 1 (+1.0R, 33%) -> True Breakeven
                if not pos["tp1_hit"]:
                    hit_tp1 = (c_high >= tp1) if is_long else (c_low <= tp1)
                    if hit_tp1:
                        t1_sz = pos["t1_size"]
                        pos["remaining_size"] -= t1_sz
                        pos["tp1_hit"] = True
                        pos["tp1_bar"] = pos["bars_held"]

                        diff_tp1 = (tp1 - entry_px) if is_long else (entry_px - tp1)
                        gross_tp1 = diff_tp1 * t1_sz
                        fee_tp1 = tp1 * t1_sz * self.maker_fee_pct
                        pos["tp1_pnl_net"] = gross_tp1 - fee_tp1
                        pos["fees_accumulated"] += fee_tp1

                        pos["be_activated"] = True
                        pos["stop_loss"] = pos["true_be_price"]

                # 2. Tier 2 (+3.0R, 33%) -> Verrouille à TP1
                if pos["tp1_hit"] and not pos["tp2_hit"]:
                    hit_tp2 = (c_high >= tp2) if is_long else (c_low <= tp2)
                    if hit_tp2:
                        t2_sz = pos["t2_size"]
                        pos["remaining_size"] -= t2_sz
                        pos["tp2_hit"] = True
                        pos["tp2_bar"] = pos["bars_held"]

                        diff_tp2 = (tp2 - entry_px) if is_long else (entry_px - tp2)
                        gross_tp2 = diff_tp2 * t2_sz
                        fee_tp2 = tp2 * t2_sz * self.maker_fee_pct
                        pos["tp2_pnl_net"] = gross_tp2 - fee_tp2
                        pos["fees_accumulated"] += fee_tp2
                        pos["stop_loss"] = tp1

                # 3. Tier 3 (34% Runner Trailing)
                if pos["tp2_hit"]:
                    local_trail_dist = max(0.50 * risk_dist, entry_px * 0.001)
                    if is_long:
                        candidate_trail = c_close - (1.2 * local_trail_dist)
                        if candidate_trail > pos["stop_loss"]:
                            pos["stop_loss"] = round(candidate_trail, 4)
                    else:
                        candidate_trail = c_close + (1.2 * local_trail_dist)
                        if candidate_trail < pos["stop_loss"]:
                            pos["stop_loss"] = round(candidate_trail, 4)

                # Same bar protection
                if pos["tp2_hit"] and pos.get("tp2_bar") == pos["bars_held"]:
                    effective_sl = pos["true_be_price"]
                elif pos["be_activated"] and pos.get("tp1_bar") == pos["bars_held"]:
                    effective_sl = pos["initial_stop_loss"]
                else:
                    effective_sl = pos["stop_loss"]

                hit_sl = (c_low <= effective_sl) if is_long else (c_high >= effective_sl)
                hit_time_stop = (not pos["tp1_hit"]) and (pos["bars_held"] >= self.time_stop_bars)
                if pos["tp1_hit"] and pos["bars_held"] >= 150:
                    hit_time_stop = True

                if hit_sl or hit_time_stop:
                    exit_px = effective_sl if hit_sl else c_close
                    if pos["tp2_hit"]:
                        exit_reason = "RUNNER_TRAIL"
                    elif pos["tp1_hit"]:
                        exit_reason = "BE" if abs(exit_px - pos["true_be_price"]) < (entry_px * 0.0005) else "PROFIT_LOCK"
                    elif hit_time_stop:
                        exit_reason = "TIME_STOP"
                    else:
                        exit_reason = "SL"

                    rem_sz = pos["remaining_size"]
                    exit_fee = exit_px * rem_sz * (self.maker_fee_pct if (exit_reason in ("RUNNER_TRAIL", "TP") and not hit_sl) else self.taker_fee_pct)
                    diff_rem = (exit_px - entry_px) if is_long else (entry_px - exit_px)
                    net_rem = (diff_rem * rem_sz) - exit_fee
                    total_net_pnl = pos["tp1_pnl_net"] + pos["tp2_pnl_net"] + net_rem
                    total_fees = pos["fees_accumulated"] + exit_fee

                    current_balance += total_net_pnl
                    self.risk_mgr.update_balance(current_balance)
                    self.risk_mgr.record_trade_result(total_net_pnl)

                    initial_risk_usd = risk_dist * pos["initial_size"] if risk_dist > 0 else 1.0
                    r_mult = round(total_net_pnl / initial_risk_usd, 2)

                    trade_counter += 1
                    record = TradeRecord(
                        trade_id=trade_counter,
                        symbol=sym,
                        is_long=is_long,
                        entry_time=pos["entry_time"],
                        exit_time=current_time,
                        entry_price=entry_px,
                        exit_price=exit_px,
                        stop_loss=effective_sl,
                        take_profit=tp2,
                        position_size=pos["initial_size"],
                        pnl_usd=round(total_net_pnl, 2),
                        pnl_pct=round((total_net_pnl / current_balance) * 100.0, 2),
                        exit_reason=exit_reason,
                        fees_usd=round(total_fees, 4),
                        risk_reward=round(abs(tp2 - entry_px) / risk_dist, 2) if risk_dist > 0 else 2.0,
                        grade=pos.get("grade", "5_STAR_OB"),
                        be_activated=pos["be_activated"],
                        r_multiple=r_mult,
                        bars_held=pos["bars_held"],
                        tp1_hit=pos["tp1_hit"],
                        tp2_hit=pos["tp2_hit"],
                        partial_pnl_usd=round(pos["tp1_pnl_net"] + pos["tp2_pnl_net"], 2),
                        initial_stop_loss=pos["initial_stop_loss"]
                    )
                    all_trades.append(record)
                    trades_by_symbol[sym].append(record)
                    last_exit_times[sym] = current_time
                    closed_this_bar.append(sym)

            for sym in closed_this_bar:
                del active_positions[sym]

            # ─── ÉTAPE B : Filtre de Session Institutionnelle (08h - 20h UTC) ───
            if self.session_filter:
                current_hour = (current_time // (3600 * 1000)) % 24
                if not (8 <= current_hour < 20):
                    equity_curve.append({
                        "timestamp": current_time,
                        "balance": round(current_balance, 2),
                        "open_positions": len(active_positions)
                    })
                    continue

            # ─── ÉTAPE C : Recherche de Nouveaux Setups Parallèles ───
            available_slots = self.max_concurrent_positions - len(active_positions)
            if available_slots <= 0:
                equity_curve.append({
                    "timestamp": current_time,
                    "balance": round(current_balance, 2),
                    "open_positions": len(active_positions)
                })
                continue

            candidates_this_bar: List[Dict[str, Any]] = []

            for sym in symbols:
                if sym in active_positions:
                    continue
                if current_time < last_exit_times[sym] + self.cooldown_ms:
                    continue

                bar_data = candle_maps[sym].get(current_time)
                if not bar_data:
                    continue

                ltf_df = market_data[sym]["ltf"]
                # Trouver l'indice de la bougie dans ltf_df
                # Comme sorted_timestamps est synchronisé, utilisons searchsorted sur ltf_df timestamps
                sym_times = ltf_df["timestamp"].values
                idx = np.searchsorted(sym_times, current_time)
                if idx < 40 or idx >= len(ltf_df) or sym_times[idx] != current_time:
                    continue

                window_df = ltf_df.iloc[max(0, idx - 120):idx + 1].copy().reset_index(drop=True)
                htf_df = market_data[sym].get("htf")
                htf_times = htf_times_dict[sym]

                if htf_df is not None and htf_times is not None and len(htf_df) >= 15:
                    htf_idx = np.searchsorted(htf_times, current_time, side='right')
                    current_htf_slice = htf_df.iloc[max(0, htf_idx - 100):htf_idx].copy().reset_index(drop=True) if htf_idx >= 15 else None
                    analysis = smc_instances[sym].analyze_mtf(current_htf_slice, window_df)
                else:
                    analysis = smc_instances[sym].analyze(window_df)

                if not analysis.setups:
                    continue

                c_open = bar_data["open"]
                c_high = bar_data["high"]
                c_low = bar_data["low"]

                for candidate in analysis.setups:
                    # Vérifier le touché du limit order
                    if candidate.is_long:
                        touched = (c_low <= candidate.entry_price) and (candidate.entry_price <= c_high or c_open >= candidate.entry_price)
                    else:
                        touched = (c_high >= candidate.entry_price) and (candidate.entry_price >= c_low or c_open <= candidate.entry_price)

                    if not touched:
                        continue

                    # Évaluer la conviction pour classement de priorité
                    is_sweep = "SWEEP" in candidate.grade or candidate.has_prior_sweep
                    priority_score = 3 if is_sweep else (2 if "OB" in candidate.grade else 1)

                    candidates_this_bar.append({
                        "symbol": sym,
                        "candidate": candidate,
                        "priority": priority_score,
                        "is_sweep": is_sweep,
                        "htf_trend": analysis.trend.value if analysis.trend else "NEUTRAL"
                    })
                    break  # 1 setup maximum par symbole par bougie

            # Trier les candidats par priorité (Sweep en premier, puis OB, puis FVG)
            candidates_this_bar.sort(key=lambda x: x["priority"], reverse=True)

            # Prendre les meilleurs candidats dans la limite des slots disponibles
            for c_info in candidates_this_bar[:available_slots]:
                sym = c_info["symbol"]
                candidate: SMCSetupCandidate = c_info["candidate"]
                is_sweep = c_info["is_sweep"]

                risk_alloc = self.risk_sweep if is_sweep else self.risk_cont
                self.risk_mgr.risk_pct = risk_alloc

                prop, msg = self.risk_mgr.evaluate_proposal(
                    symbol=sym,
                    is_long=candidate.is_long,
                    entry_price=candidate.entry_price,
                    stop_loss=candidate.stop_loss,
                    take_profit=candidate.take_profit_2r
                )

                if prop is not None:
                    risk_d = abs(candidate.entry_price - candidate.stop_loss)
                    tp1_px = candidate.take_profit_1r
                    tp2_px = candidate.take_profit_2r
                    true_be_px = self.risk_mgr.calculate_true_breakeven(
                        entry_price=candidate.entry_price,
                        is_long=candidate.is_long,
                        maker_fee_pct=self.maker_fee_pct,
                        taker_fee_pct=self.taker_fee_pct,
                        buffer_ticks=1.0
                    )
                    entry_fee = candidate.entry_price * prop.position_size * self.maker_fee_pct

                    t1_size = round(prop.position_size * 0.33, 6)
                    t2_size = round(prop.position_size * 0.33, 6)
                    t3_size = round(prop.position_size - t1_size - t2_size, 6)

                    active_positions[sym] = {
                        "symbol": sym,
                        "is_long": candidate.is_long,
                        "entry_price": candidate.entry_price,
                        "initial_stop_loss": candidate.stop_loss,
                        "stop_loss": candidate.stop_loss,
                        "true_be_price": true_be_px,
                        "take_profit_1r": tp1_px,
                        "take_profit_2r": tp2_px,
                        "risk_dist": risk_d,
                        "initial_size": prop.position_size,
                        "remaining_size": prop.position_size,
                        "t1_size": t1_size,
                        "t2_size": t2_size,
                        "t3_size": t3_size,
                        "entry_time": current_time,
                        "rr": prop.risk_reward_ratio,
                        "bars_held": 0,
                        "grade": candidate.grade,
                        "be_activated": False,
                        "tp1_hit": False,
                        "tp1_bar": -1,
                        "tp1_pnl_net": 0.0,
                        "tp2_hit": False,
                        "tp2_bar": -1,
                        "tp2_pnl_net": 0.0,
                        "fees_accumulated": entry_fee,
                        "htf_trend_at_entry": c_info["htf_trend"]
                    }

            equity_curve.append({
                "timestamp": current_time,
                "balance": round(current_balance, 2),
                "open_positions": len(active_positions)
            })

        # Calcul des métriques globales et par symbole
        global_report = calculate_backtest_metrics(self.initial_capital, all_trades, equity_curve)

        per_symbol_metrics = {}
        for sym in symbols:
            s_trades = trades_by_symbol[sym]
            rep = calculate_backtest_metrics(self.initial_capital, s_trades, equity_curve)
            per_symbol_metrics[sym] = rep.summary_dict()

        return {
            "summary": global_report.summary_dict(),
            "all_trades": all_trades,
            "equity_curve": equity_curve,
            "per_symbol": per_symbol_metrics
        }
