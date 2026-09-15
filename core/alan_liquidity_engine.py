import time
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class AlanEvaluation:
    symbol: str
    is_long: bool
    approved: bool
    is_vetoed: bool
    is_boosted: bool
    regime: str  # "SHORT_SQUEEZE_ALERT", "LONG_SQUEEZE_ALERT", "NEUTRAL"
    score_boost: float
    funding_8h_pct: float
    fng_value: int
    fng_classification: str
    adjusted_tp: float
    reason: str


class AlanLiquidityEngine:
    """
    Moteur institutionnel Dérivés & Liquidités inspiré d'Alan Trading (@AlanTradingYT).
    Analyse les flux de dérivés (Funding Rates, Open Interest) et le sentiment (Fear & Greed)
    pour identifier les régimes de squeeze et appliquer un biais asymétrique :
    - Risque de Short Squeeze -> VETO sur les Shorts, BOOST agressif sur les Longs (+15 pts, TP étendu).
    - Risque de Long Squeeze  -> VETO sur les Longs, BOOST agressif sur les Shorts (+15 pts, TP étendu).
    """

    def __init__(
        self,
        funding_short_squeeze_threshold_8h: float = -0.00005,  # -0.005% sur 8h
        funding_long_squeeze_threshold_8h: float = 0.00025,   # +0.025% sur 8h
        fng_fear_threshold: int = 35,
        fng_greed_threshold: int = 75,
        tp_extension_mult: float = 1.35
    ):
        self.funding_short_squeeze_threshold_8h = funding_short_squeeze_threshold_8h
        self.funding_long_squeeze_threshold_8h = funding_long_squeeze_threshold_8h
        self.fng_fear_threshold = fng_fear_threshold
        self.fng_greed_threshold = fng_greed_threshold
        self.tp_extension_mult = tp_extension_mult

    def evaluate_signal(
        self,
        symbol: str,
        is_long: bool,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        asset_context: Optional[Dict[str, Any]] = None,
        fear_and_greed: Optional[Dict[str, Any]] = None
    ) -> AlanEvaluation:
        """
        Évalue l'adéquation d'un signal SMC avec le carnet de dérivés et le sentiment.
        Retourne une décision intégrant VETO ou BOOST directionnel.
        """
        ctx = asset_context or {}
        fng = fear_and_greed or {"value": 50, "classification": "Neutral"}

        hourly_funding = float(ctx.get("funding") or 0.0)
        funding_8h = hourly_funding * 8.0
        funding_8h_pct = funding_8h * 100.0  # Pourcentage lisible

        fng_val = int(fng.get("value") or 50)
        fng_class = str(fng.get("classification") or "Neutral")

        # 1. Détection du régime de marché
        short_squeeze_risk = (
            funding_8h <= self.funding_short_squeeze_threshold_8h or
            (funding_8h < 0.0 and fng_val <= self.fng_fear_threshold)
        )
        long_squeeze_risk = (
            funding_8h >= self.funding_long_squeeze_threshold_8h or
            (funding_8h > 0.00015 and fng_val >= self.fng_greed_threshold)
        )

        regime = "NEUTRAL"
        if short_squeeze_risk:
            regime = "SHORT_SQUEEZE_ALERT"
        elif long_squeeze_risk:
            regime = "LONG_SQUEEZE_ALERT"

        adjusted_tp = take_profit
        risk_dist = abs(entry_price - stop_loss)

        # 2. Application de la logique asymétrique Squeeze Booster
        if regime == "SHORT_SQUEEZE_ALERT":
            if not is_long:
                # Tentative de SHORT en plein risque de Short Squeeze -> VETO
                return AlanEvaluation(
                    symbol=symbol,
                    is_long=is_long,
                    approved=False,
                    is_vetoed=True,
                    is_boosted=False,
                    regime=regime,
                    score_boost=-30.0,
                    funding_8h_pct=round(funding_8h_pct, 4),
                    fng_value=fng_val,
                    fng_classification=fng_class,
                    adjusted_tp=take_profit,
                    reason=(
                        f"VETO ALAN TRADING : Risque de Short Squeeze sur {symbol} "
                        f"(Funding 8h: {funding_8h_pct:+.3f}%, F&G: {fng_val} {fng_class}). "
                        f"Interdiction de short dans un piège de vendeurs surendettés."
                    )
                )
            else:
                # Signal LONG aligné avec le Short Squeeze -> BOOST agressif
                if risk_dist > 0:
                    adjusted_tp = entry_price + (risk_dist * 2.0 * self.tp_extension_mult)
                return AlanEvaluation(
                    symbol=symbol,
                    is_long=is_long,
                    approved=True,
                    is_vetoed=False,
                    is_boosted=True,
                    regime=regime,
                    score_boost=15.0,
                    funding_8h_pct=round(funding_8h_pct, 4),
                    fng_value=fng_val,
                    fng_classification=fng_class,
                    adjusted_tp=round(adjusted_tp, 5),
                    reason=(
                        f"BOOST ALAN TRADING : Alignement Short Squeeze sur {symbol} "
                        f"(Funding 8h: {funding_8h_pct:+.3f}%, F&G: {fng_val}). "
                        f"Les liquidations de shorts offrent un puissant fuel haussier. TP étendu à {adjusted_tp}."
                    )
                )

        elif regime == "LONG_SQUEEZE_ALERT":
            if is_long:
                # Tentative de LONG en plein risque de Long Squeeze -> VETO
                return AlanEvaluation(
                    symbol=symbol,
                    is_long=is_long,
                    approved=False,
                    is_vetoed=True,
                    is_boosted=False,
                    regime=regime,
                    score_boost=-30.0,
                    funding_8h_pct=round(funding_8h_pct, 4),
                    fng_value=fng_val,
                    fng_classification=fng_class,
                    adjusted_tp=take_profit,
                    reason=(
                        f"VETO ALAN TRADING : Risque de Long Squeeze sur {symbol} "
                        f"(Funding 8h surchauffé: {funding_8h_pct:+.3f}%, F&G: {fng_val} {fng_class}). "
                        f"Interdiction d'acheter sur un sommet de levier acheteur saturé."
                    )
                )
            else:
                # Signal SHORT aligné avec le Long Squeeze -> BOOST agressif
                if risk_dist > 0:
                    adjusted_tp = entry_price - (risk_dist * 2.0 * self.tp_extension_mult)
                return AlanEvaluation(
                    symbol=symbol,
                    is_long=is_long,
                    approved=True,
                    is_vetoed=False,
                    is_boosted=True,
                    regime=regime,
                    score_boost=15.0,
                    funding_8h_pct=round(funding_8h_pct, 4),
                    fng_value=fng_val,
                    fng_classification=fng_class,
                    adjusted_tp=round(adjusted_tp, 5),
                    reason=(
                        f"BOOST ALAN TRADING : Alignement Long Squeeze sur {symbol} "
                        f"(Funding 8h surchauffé: {funding_8h_pct:+.3f}%, F&G: {fng_val}). "
                        f"Cascade de liquidations acheteurs attendue. TP étendu à {adjusted_tp}."
                    )
                )

        # 3. Régime neutre : conditions régulières de marché
        return AlanEvaluation(
            symbol=symbol,
            is_long=is_long,
            approved=True,
            is_vetoed=False,
            is_boosted=False,
            regime="NEUTRAL",
            score_boost=0.0,
            funding_8h_pct=round(funding_8h_pct, 4),
            fng_value=fng_val,
            fng_classification=fng_class,
            adjusted_tp=take_profit,
            reason=f"ALAN TRADING : Dérivés équilibrés (Funding 8h: {funding_8h_pct:+.3f}%, F&G: {fng_val}). Validation neutre."
        )
