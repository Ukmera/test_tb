from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import pandas as pd


@dataclass
class TradeDiagnosticResult:
    trade_id: int
    category: str
    badge_label: str
    badge_color: str
    mae_r: float
    mfe_r: float
    htf_aligned: bool
    diagnosis_summary: str
    ai_tuning_tip: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "category": self.category,
            "badge_label": self.badge_label,
            "badge_color": self.badge_color,
            "mae_r": round(self.mae_r, 2),
            "mfe_r": round(self.mfe_r, 2),
            "htf_aligned": self.htf_aligned,
            "diagnosis_summary": self.diagnosis_summary,
            "ai_tuning_tip": self.ai_tuning_tip
        }


class TradeForensicAnalyzer:
    """
    Moteur médico-légal quantitatif analysant chaque trade clôturé :
    - Calcule le MAE (Maximum Adverse Excursion) et le MFE (Maximum Favorable Excursion).
    - Détecte l'alignement ou le contre-courant avec la tendance HTF.
    - Classifie la cause racine de succès ou d'échec pour guider le calibrage de l'IA.
    """

    @staticmethod
    def analyze_trade(
        trade: Any,
        candles_df: pd.DataFrame,
        htf_trend: str = "NEUTRAL"
    ) -> TradeDiagnosticResult:
        is_long = trade.is_long
        entry_px = trade.entry_price
        init_sl = getattr(trade, "initial_stop_loss", 0.0)
        sl = init_sl if init_sl > 0 else trade.stop_loss
        risk_dist = abs(entry_px - sl) if abs(entry_px - sl) > 0 else 1.0

        # Identifier les bougies parcourues pendant le trade
        start_t = trade.entry_time
        end_t = trade.exit_time
        trade_bars = candles_df[(candles_df['timestamp'] >= start_t) & (candles_df['timestamp'] <= end_t)]

        if trade_bars.empty:
            trade_bars = candles_df.tail(10)

        # Calcul MAE & MFE
        if is_long:
            lowest_price = trade_bars['low'].min()
            highest_price = trade_bars['high'].max()
            mae = (entry_px - lowest_price) / risk_dist if lowest_price < entry_px else 0.0
            mfe = (highest_price - entry_px) / risk_dist if highest_price > entry_px else 0.0
        else:
            lowest_price = trade_bars['low'].min()
            highest_price = trade_bars['high'].max()
            mae = (highest_price - entry_px) / risk_dist if highest_price > entry_px else 0.0
            mfe = (entry_px - lowest_price) / risk_dist if lowest_price < entry_px else 0.0

        mae = max(0.0, float(mae))
        mfe = max(0.0, float(mfe))

        # Vérification alignement HTF
        htf_aligned = (is_long and htf_trend == "BULLISH") or ((not is_long) and htf_trend == "BEARISH")

        # Classification médico-légale
        exit_reason = getattr(trade, "exit_reason", "SL")
        pnl = getattr(trade, "pnl_usd", 0.0)
        be_act = getattr(trade, "be_activated", False)

        if getattr(trade, "tp2_hit", False) or exit_reason == "RUNNER_TRAIL" or (pnl > 0 and mfe >= 3.0):
            cat = "RUNNER_BIG_WIN"
            label = "🚀 RUNNER DÉPLOYÉ (+3R à +11R)"
            color = "#00e676"
            diag = f"Extension institutionnelle capturée. MFE atteint de {mfe:.1f}R avec un R-multiple net de +{getattr(trade, 'r_multiple', 0.0):.2f}R."
            tip = "Configuration explosive. Le trailing stop a extrait l'alpha maximum du swing."

        elif exit_reason == "TP" or (pnl > 0 and mfe >= 1.8):
            cat = "TP2_CLEAN"
            label = "🎯 TP2 COMPLET (+3R)"
            color = "#00e676"
            diag = f"Trade gagnant propre. MFE atteint de {mfe:.1f}R avec un drawdown de {mae:.2f}R."
            tip = "Configuration optimale. Valider la persistance du signal sur ce timeframe."

        elif getattr(trade, "tp1_hit", False):
            cat = "TP1_THEN_TRUE_BE"
            label = "💰 TP1 SÉCURISÉ (+1.5R) + VRAI BE"
            color = "#00d2ff"
            diag = f"Prise partielle Tier 1 encaissée à +1.5R. Solde sorti au True BE. PnL net positif garanti ({pnl:.2f}$). MFE: {mfe:.1f}R."
            tip = "Le mécanisme de True Breakeven a rempli son rôle de verrouillage de trésorerie."

        elif exit_reason == "BE" or (be_act and abs(pnl) < 1.0):
            cat = "TRUE_BE_PROTECTED"
            label = "🛡️ VRAI BE (CAPITAL PROTÉGÉ)"
            color = "#ffd700"
            diag = f"Le cours est monté à +{mfe:.1f}R avant de se retourner. Le True BE a annulé la perte de -1R."
            tip = "Si de nombreux trades touchent le BE après +1R, tester un TP1 plus agressif ou un trailing ATR."

        elif not htf_aligned and exit_reason == "SL":
            cat = "COUNTER_TREND_SL"
            label = "⚠️ CONTRE-TENDANCE HTF"
            color = "#ff3d71"
            diag = f"Perte directe à contre-courant du biais HTF ({htf_trend}). Entrée prématurée sans confirmation macro."
            tip = "Activer le filtre strict de veto Palermo interdisant tout trade contre le biais 1H."

        elif exit_reason == "TIME_STOP":
            cat = "CHOP_STAGNATION"
            label = "⏳ STAGNATION RANGE"
            color = "#ba68c8"
            diag = f"Sortie par Time-Stop après {getattr(trade, 'bars_held', 0)} barres sans momentum (MFE: {mfe:.1f}R)."
            tip = "Le marché était en compression. Renforcer le filtre de volume expansion de Denver."

        elif mae > 1.0 and exit_reason == "SL":
            cat = "VOLATILITY_WICK"
            label = "⚡ MÈCHE DE LIQUIDITÉ (SL)"
            color = "#ff3d71"
            diag = f"Stop Loss déclenché par une mèche (MAE: {mae:.2f}R). Zone invalidée avant impulsion."
            tip = "Élargir légèrement le buffer ATR sous l'Order Block (passer de 0.10*ATR à 0.15*ATR)."

        else:
            cat = "SL_HIT"
            label = "🛑 STOP LOSS CLASSIC (-1R)"
            color = "#ff3d71"
            diag = f"Invalidation normale du setup SMC (Perte contenue à 1% strict, PnL: {pnl:.2f}$). MAE: {mae:.2f}R."
            tip = "Risque maîtrisé. Vérifier si l'OB était déjà mitigé sur le corps de la bougie."

        return TradeDiagnosticResult(
            trade_id=getattr(trade, "trade_id", 0),
            category=cat,
            badge_label=label,
            badge_color=color,
            mae_r=mae,
            mfe_r=mfe,
            htf_aligned=htf_aligned,
            diagnosis_summary=diag,
            ai_tuning_tip=tip
        )
