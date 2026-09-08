from dataclasses import dataclass
from typing import Optional, Tuple
from config.settings import (
    INITIAL_CAPITAL_USD,
    RISK_PER_TRADE_PCT,
    MAX_LEVERAGE_CAP,
    MIN_RISK_REWARD,
    MAX_SPREAD_PCT,
    MAX_SLIPPAGE_PCT,
    MAX_DAILY_DRAWDOWN_PCT,
    MAX_CONSECUTIVE_LOSSES
)


@dataclass
class TradeOrderProposal:
    symbol: str
    is_long: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float        # En unités de l'actif (ex: BTC)
    notional_value: float       # En USD
    risk_amount_usd: float      # Risque en USD (1% du capital)
    risk_reward_ratio: float
    leverage: float
    take_profit_1r: float = 0.0
    take_profit_2r: float = 0.0
    true_be_price: float = 0.0
    grade: str = "5_STAR_OB"
    has_prior_sweep: bool = False


@dataclass
class GuardrailCheckResult:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(
        self,
        current_balance: float = INITIAL_CAPITAL_USD,
        risk_pct: float = RISK_PER_TRADE_PCT,
        max_leverage: float = MAX_LEVERAGE_CAP,
        min_rr: float = MIN_RISK_REWARD,
        max_spread: float = MAX_SPREAD_PCT,
        max_slippage: float = MAX_SLIPPAGE_PCT
    ):
        self.current_balance = current_balance
        self.starting_daily_balance = current_balance
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.min_rr = min_rr
        self.max_spread = max_spread
        self.max_slippage = max_slippage

        self.consecutive_losses = 0
        self.kill_switch_active = False
        self.kill_switch_reason = ""

    def update_balance(self, new_balance: float):
        self.current_balance = new_balance
        # Vérification du Max Daily Drawdown
        daily_loss_pct = (self.starting_daily_balance - self.current_balance) / self.starting_daily_balance
        if daily_loss_pct >= MAX_DAILY_DRAWDOWN_PCT:
            self.kill_switch_active = True
            self.kill_switch_reason = f"Kill-Switch: Perte journalière de {daily_loss_pct*100:.2f}% (Seuil: {MAX_DAILY_DRAWDOWN_PCT*100}%)"

    def record_trade_result(self, pnl_usd: float):
        if pnl_usd < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.kill_switch_active = True
                self.kill_switch_reason = f"Kill-Switch: {self.consecutive_losses} pertes consécutives. Pause de sécurité activée."
        else:
            self.consecutive_losses = 0

    def reset_daily_stats(self):
        self.starting_daily_balance = self.current_balance
        self.kill_switch_active = False
        self.kill_switch_reason = ""

    def check_guardrails(self, best_bid: float, best_ask: float) -> GuardrailCheckResult:
        """Vérifie le Kill-Switch et les conditions de liquidité du carnet d'ordres."""
        if self.kill_switch_active:
            return GuardrailCheckResult(False, self.kill_switch_reason)

        if best_bid <= 0 or best_ask <= 0:
            return GuardrailCheckResult(False, "Prix de marché invalide ou carnet vide.")

        spread = (best_ask - best_bid) / best_bid
        if spread > self.max_spread:
            return GuardrailCheckResult(
                False,
                f"Spread trop élevé : {spread*100:.3f}% (Max autorisé : {self.max_spread*100:.3f}%)"
            )

        return GuardrailCheckResult(True, "Guardrails OK")

    def calculate_true_breakeven(
        self,
        entry_price: float,
        is_long: bool,
        maker_fee_pct: float = 0.0002,
        taker_fee_pct: float = 0.0005,
        buffer_ticks: float = 1.0
    ) -> float:
        """
        Calcule le niveau de True Breakeven net incluant les frais de protocole Hyperliquid
        (Entrée Maker 0.02% + Sortie Maker/Taker 0.02-0.05% + buffer de sécurité relatif).
        Garantit que le trade ne génère pas de perte nette sur fermeture au BE.
        """
        round_trip_fee_pct = maker_fee_pct + taker_fee_pct + 0.0001
        fee_offset = entry_price * round_trip_fee_pct
        decimals = 4 if entry_price < 10.0 else 2
        safe_buffer = (entry_price * 0.0001) if entry_price < 10.0 else min(buffer_ticks, entry_price * 0.0002)
        if is_long:
            return round(entry_price + fee_offset + safe_buffer, decimals)
        else:
            return round(entry_price - fee_offset - safe_buffer, decimals)

    def evaluate_proposal(
        self,
        symbol: str,
        is_long: bool,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        take_profit_1r: Optional[float] = None,
        take_profit_2r: Optional[float] = None,
        grade: str = "5_STAR_OB",
        has_prior_sweep: bool = False
    ) -> Tuple[Optional[TradeOrderProposal], str]:
        """
        Calcule la taille exacte de position pour risquer exactement 1% du capital,
        vérifie le Risk/Reward et applique les garde-fous.
        """
        if self.kill_switch_active:
            return None, self.kill_switch_reason

        # 1. Vérification cohérence Long/Short
        if is_long:
            if stop_loss >= entry_price:
                return None, "Incohérence Long : Le Stop Loss doit être inférieur au prix d'entrée."
            if take_profit <= entry_price:
                return None, "Incohérence Long : Le Take Profit doit être supérieur au prix d'entrée."
        else:
            if stop_loss <= entry_price:
                return None, "Incohérence Short : Le Stop Loss doit être supérieur au prix d'entrée."
            if take_profit >= entry_price:
                return None, "Incohérence Short : Le Take Profit doit être inférieur au prix d'entrée."

        # 2. Calcul du Risk/Reward
        risk_distance = abs(entry_price - stop_loss)
        reward_distance = abs(take_profit - entry_price)
        rr_ratio = reward_distance / risk_distance

        if rr_ratio < self.min_rr:
            return None, f"Risk/Reward insuffisant : {rr_ratio:.2f} (Minimum exigé : {self.min_rr:.2f})"

        # 3. Calcul de la taille de position (1% strict)
        risk_amount_usd = self.current_balance * self.risk_pct
        position_size_asset = risk_amount_usd / risk_distance
        notional_value = position_size_asset * entry_price
        effective_leverage = notional_value / self.current_balance

        # 4. Plafond de levier de sécurité
        if effective_leverage > self.max_leverage:
            # Réduction automatique de la taille pour plafonner au levier max autorisé
            adjusted_notional = self.current_balance * self.max_leverage
            position_size_asset = adjusted_notional / entry_price
            notional_value = adjusted_notional
            effective_leverage = self.max_leverage
            # Le risque réel devient inférieur à 1% pour garantir la sécurité
            risk_amount_usd = position_size_asset * risk_distance

        tp1_val = take_profit_1r if take_profit_1r is not None else (entry_price + (risk_distance * 1.0) if is_long else entry_price - (risk_distance * 1.0))
        tp2_val = take_profit_2r if take_profit_2r is not None else take_profit
        true_be_val = self.calculate_true_breakeven(entry_price, is_long)
        decimals = 4 if entry_price < 10.0 else 2

        proposal = TradeOrderProposal(
            symbol=symbol,
            is_long=is_long,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=round(position_size_asset, 2 if entry_price < 10.0 else 5),
            notional_value=round(notional_value, 2),
            risk_amount_usd=round(risk_amount_usd, 2),
            risk_reward_ratio=round(rr_ratio, 2),
            leverage=round(effective_leverage, 2),
            take_profit_1r=round(tp1_val, decimals),
            take_profit_2r=round(tp2_val, decimals),
            true_be_price=round(true_be_val, decimals),
            grade=grade,
            has_prior_sweep=has_prior_sweep
        )

        return proposal, "Proposition validée"
