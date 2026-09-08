from typing import List, Optional, Dict, Any
import numpy as np
import pandas as pd
from core.smc_engine import SMCEngine, TrendDirection, OrderBlock
from core.risk_manager import RiskManager
from core.trade_diagnostics import TradeForensicAnalyzer
from backtester.metrics import TradeRecord, BacktestReport, calculate_backtest_metrics


class SMCBacktester:
    def __init__(
        self,
        initial_capital: float = 100.0,
        risk_pct: float = 0.01,
        min_rr: float = 2.0,
        maker_fee_pct: float = 0.0002,   # Hyperliquid Maker fee: 0.02%
        taker_fee_pct: float = 0.0005,   # Taker fee: 0.05%
        slippage_pct: float = 0.0002,    # Slippage moyen simulé
        model: str = "B"
    ):
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct
        self.min_rr = min_rr
        self.maker_fee_pct = maker_fee_pct
        self.taker_fee_pct = taker_fee_pct
        self.slippage_pct = slippage_pct
        self.model = model.upper()

        # Paramètres selon le modèle SMC
        if self.model == "A":
            self.time_stop_bars = 30   # Modèle A : 30 barres
            self.cooldown_ms = 30 * 60 * 1000
        else:
            self.time_stop_bars = 25   # Modèle B : 25 barres
            self.cooldown_ms = 60 * 60 * 1000

        self.smc = SMCEngine()
        self.risk_mgr = RiskManager(
            current_balance=initial_capital,
            risk_pct=risk_pct,
            min_rr=min_rr
        )
        self.sweep_only = False
        self.session_filter = False
        self.macro_filter = False

    def run(
        self,
        df: pd.DataFrame,
        htf_df: Optional[pd.DataFrame] = None,
        warmup_candles: int = 40
    ) -> BacktestReport:
        """
        Exécute le backtest institutionnel pas-à-pas sans aucun biais d'anticipation.
        - Supporte l'analyse Multi-Timeframe synchronisée (HTF 1H + LTF).
        - Exécution Two-Stage : Prise partielle de 50% à +1.0R, trailing du solde au True Breakeven (+ fees nettes).
        - Attache une analyse médico-légale médico-diagnostique (MAE, MFE, Classification IA) à chaque trade.
        """
        n = len(df)
        if n < warmup_candles + 10:
            return calculate_backtest_metrics(self.initial_capital, [], [])

        trades: List[TradeRecord] = []
        equity_curve: List[Dict[str, Any]] = []
        current_balance = self.initial_capital
        equity_curve.append({"timestamp": int(df['timestamp'].iloc[0]), "balance": current_balance})

        active_trade: Optional[Dict[str, Any]] = None
        trade_counter = 0
        last_exit_time = 0
        last_day: Optional[int] = None

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        opens = df['open'].values
        times = df['timestamp'].values

        # Préparation de l'indexation HTF pour éliminer tout look-ahead bias
        has_htf = htf_df is not None and not htf_df.empty and len(htf_df) >= 15
        htf_times = htf_df['timestamp'].values if has_htf else None

        for i in range(warmup_candles, n):
            current_time = int(times[i])
            current_day = current_time // (24 * 3600 * 1000)
            if last_day is not None and current_day != last_day:
                self.risk_mgr.reset_daily_stats()
            last_day = current_day

            current_high = highs[i]
            current_low = lows[i]
            current_close = closes[i]

            # 1. Gestion de la position ouverte si active
            if active_trade is not None:
                active_trade["bars_held"] += 1
                is_long = active_trade["is_long"]
                sl = active_trade["stop_loss"]
                tp2 = active_trade["take_profit"]
                tp1 = active_trade["take_profit_1r"]
                entry_px = active_trade["entry_price"]
                risk_dist = active_trade["risk_dist"]
                rem_size = active_trade["remaining_size"]
                init_size = active_trade["initial_size"]

                # ─── A. Prise partielle Tier 1 (+1.5R, 33%) et armement du True Breakeven ───
                if not active_trade["tp1_hit"]:
                    hit_tp1 = (current_high >= tp1) if is_long else (current_low <= tp1)
                    if hit_tp1:
                        t1_sz = active_trade["t1_size"]
                        active_trade["remaining_size"] -= t1_sz
                        active_trade["tp1_hit"] = True
                        active_trade["tp1_bar"] = active_trade["bars_held"]

                        diff_tp1 = (tp1 - entry_px) if is_long else (entry_px - tp1)
                        gross_tp1 = diff_tp1 * t1_sz
                        fee_tp1 = tp1 * t1_sz * self.maker_fee_pct
                        active_trade["tp1_pnl_net"] = gross_tp1 - fee_tp1
                        active_trade["fees_accumulated"] += fee_tp1

                        # Activer le True Breakeven sur le solde
                        active_trade["be_activated"] = True
                        active_trade["stop_loss"] = active_trade["true_be_price"]

                # ─── B. Prise partielle Tier 2 (+3.0R, 33%) et verrouillage du Runner ───
                if active_trade["tp1_hit"] and not active_trade["tp2_hit"]:
                    hit_tp2 = (current_high >= tp2) if is_long else (current_low <= tp2)
                    if hit_tp2:
                        t2_sz = active_trade["t2_size"]
                        active_trade["remaining_size"] -= t2_sz
                        active_trade["tp2_hit"] = True
                        active_trade["tp2_bar"] = active_trade["bars_held"]

                        diff_tp2 = (tp2 - entry_px) if is_long else (entry_px - tp2)
                        gross_tp2 = diff_tp2 * t2_sz
                        fee_tp2 = tp2 * t2_sz * self.maker_fee_pct
                        active_trade["tp2_pnl_net"] = gross_tp2 - fee_tp2
                        active_trade["fees_accumulated"] += fee_tp2

                        # Verrouiller le Stop Loss du Runner restant à au moins TP1 (+1.5R)
                        active_trade["stop_loss"] = tp1

                # ─── C. Trailing Stop dynamique sur le Tier 3 Runner (34%) ───
                if active_trade["tp2_hit"]:
                    local_trail_dist = max(0.50 * risk_dist, 50.0)
                    if is_long:
                        candidate_trail = current_close - (1.2 * local_trail_dist)
                        if candidate_trail > active_trade["stop_loss"]:
                            active_trade["stop_loss"] = round(candidate_trail, 2)
                    else:
                        candidate_trail = current_close + (1.2 * local_trail_dist)
                        if candidate_trail < active_trade["stop_loss"]:
                            active_trade["stop_loss"] = round(candidate_trail, 2)

                # ─── D. Vérification des conditions de sortie sur la taille restante ───
                # Protection Same-Bar : si TP1 ou TP2 activé sur la MÊME barre, ne pas être stoppé
                # par la mèche qui a précédé le push.
                if active_trade["tp2_hit"] and active_trade.get("tp2_bar") == active_trade["bars_held"]:
                    effective_sl = active_trade["true_be_price"]
                elif active_trade["be_activated"] and active_trade.get("tp1_bar") == active_trade["bars_held"]:
                    effective_sl = active_trade["initial_stop_loss"]
                else:
                    effective_sl = active_trade["stop_loss"]

                hit_sl = (current_low <= effective_sl) if is_long else (current_high >= effective_sl)

                # Time-stop : s'applique uniquement avant TP1 pour éviter de couper un swing gagnant
                hit_time_stop = (not active_trade["tp1_hit"]) and (active_trade["bars_held"] >= self.time_stop_bars)
                if active_trade["tp1_hit"] and active_trade["bars_held"] >= 150:
                    hit_time_stop = True

                if hit_sl or hit_time_stop:
                    exit_px = effective_sl if hit_sl else current_close
                    if active_trade["tp2_hit"]:
                        exit_reason = "RUNNER_TRAIL"
                    elif active_trade["tp1_hit"]:
                        exit_reason = "BE" if abs(exit_px - active_trade["true_be_price"]) < 5.0 else "PROFIT_LOCK"
                    elif hit_time_stop:
                        exit_reason = "TIME_STOP"
                    else:
                        exit_reason = "SL"

                    rem_size = active_trade["remaining_size"]
                    diff_rem = (exit_px - entry_px) if is_long else (entry_px - exit_px)
                    gross_rem = diff_rem * rem_size
                    fee_rate = self.maker_fee_pct if hit_sl else self.taker_fee_pct
                    fee_rem = exit_px * rem_size * fee_rate
                    active_trade["fees_accumulated"] += fee_rem

                    net_rem = gross_rem - fee_rem
                    total_net_pnl = active_trade["tp1_pnl_net"] + active_trade["tp2_pnl_net"] + net_rem
                    total_fees = active_trade["fees_accumulated"]

                    current_balance += total_net_pnl
                    self.risk_mgr.update_balance(current_balance)
                    self.risk_mgr.record_trade_result(total_net_pnl)

                    initial_risk_usd = risk_dist * init_size if risk_dist > 0 else 1.0
                    r_mult = round(total_net_pnl / initial_risk_usd, 2)

                    trade_counter += 1
                    trade_record = TradeRecord(
                        trade_id=trade_counter,
                        symbol="BTC",
                        is_long=is_long,
                        entry_time=active_trade["entry_time"],
                        exit_time=current_time,
                        entry_price=entry_px,
                        exit_price=exit_px,
                        stop_loss=effective_sl,
                        take_profit=tp2,
                        position_size=init_size,
                        pnl_usd=round(total_net_pnl, 2),
                        pnl_pct=round((total_net_pnl / current_balance) * 100.0, 2),
                        exit_reason=exit_reason,
                        fees_usd=round(total_fees, 4),
                        risk_reward=round(abs(tp2 - entry_px) / risk_dist, 2) if risk_dist > 0 else 2.0,
                        grade=active_trade.get("grade", "5_STAR_OB"),
                        be_activated=active_trade["be_activated"],
                        r_multiple=r_mult,
                        bars_held=active_trade["bars_held"],
                        tp1_hit=active_trade["tp1_hit"],
                        tp2_hit=active_trade["tp2_hit"],
                        partial_pnl_usd=round(active_trade["tp1_pnl_net"] + active_trade["tp2_pnl_net"], 2),
                        initial_stop_loss=active_trade["initial_stop_loss"]
                    )

                    # Diagnostic médico-légal quantitatif post-trade
                    diag = TradeForensicAnalyzer.analyze_trade(
                        trade=trade_record,
                        candles_df=df,
                        htf_trend=active_trade.get("htf_trend_at_entry", "NEUTRAL")
                    )
                    trade_record.diagnostics = diag.to_dict()

                    trades.append(trade_record)
                    active_trade = None
                    last_exit_time = current_time
                    equity_curve.append({"timestamp": current_time, "balance": round(current_balance, 2)})
                continue

            # Respect du cooldown obligatoire après un trade
            if current_time < last_exit_time + self.cooldown_ms:
                continue

            # Filtre de session optionnel (Londres / New York : 08:00 - 20:00 UTC)
            if self.session_filter:
                current_hour = (current_time // (3600 * 1000)) % 24
                if not (8 <= current_hour < 20):
                    continue

            # 2. Recherche d'un signal SMC si aucune position n'est ouverte
            window_df = df.iloc[max(0, i - 120):i + 1].copy().reset_index(drop=True)

            if has_htf:
                htf_idx = np.searchsorted(htf_times, current_time, side='right')
                current_htf_slice = htf_df.iloc[max(0, htf_idx - 100):htf_idx].copy().reset_index(drop=True) if htf_idx >= 15 else None
                analysis = self.smc.analyze_mtf(current_htf_slice, window_df)
            else:
                analysis = self.smc.analyze(window_df)

            if not analysis.setups:
                continue

            for candidate in analysis.setups:
                if self.sweep_only and not candidate.has_prior_sweep and "SWEEP" not in candidate.grade:
                    continue

                # Vérifier si l'ordre limite a été touché sur la bougie courante
                if candidate.is_long:
                    touched = (current_low <= candidate.entry_price) and (candidate.entry_price <= current_high or opens[i] >= candidate.entry_price)
                else:
                    touched = (current_high >= candidate.entry_price) and (candidate.entry_price >= current_low or opens[i] <= candidate.entry_price)

                if not touched:
                    continue

                # Allocation de risque institutionnelle
                if "SWEEP" in candidate.grade:
                    risk_alloc = 0.008
                elif "OB" in candidate.grade:
                    risk_alloc = 0.007
                else:
                    risk_alloc = 0.004
                self.risk_mgr.risk_pct = risk_alloc

                prop, msg = self.risk_mgr.evaluate_proposal(
                    symbol="BTC",
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

                    active_trade = {
                        "is_long": candidate.is_long,
                        "entry_price": candidate.entry_price,
                        "initial_stop_loss": candidate.stop_loss,
                        "stop_loss": candidate.stop_loss,
                        "true_be_price": true_be_px,
                        "take_profit_1r": tp1_px,
                        "take_profit_2r": tp2_px,
                        "take_profit": tp2_px,
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
                        "htf_trend_at_entry": analysis.trend.value if analysis.trend else "NEUTRAL"
                    }
                    break

        return calculate_backtest_metrics(self.initial_capital, trades, equity_curve)

