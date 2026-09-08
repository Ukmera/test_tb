import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from config.settings import BASE_DIR

JOURNAL_FILE = BASE_DIR / "data_cache" / "trade_journal.json"


@dataclass
class TradeCritique:
    trade_id: int
    timestamp: int
    symbol: str
    is_long: bool
    pnl_usd: float
    exit_reason: str  # "TP" ou "SL"
    category: str
    diagnosis: str
    recommendation: str


class AICriticBot:
    """
    Bot 4 : Agent d'Auto-Critique et Journal de Trading Intelligent
    Analyse chaque trade clôturé de façon asynchrone pour distinguer
    la variance statistique des véritables erreurs techniques.
    """
    def __init__(self, journal_path: Path = JOURNAL_FILE):
        self.journal_path = journal_path
        self.journal: List[Dict[str, Any]] = []
        self._load_journal()

    def _load_journal(self):
        if self.journal_path.exists():
            try:
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    self.journal = json.load(f)
            except Exception:
                self.journal = []

    def _save_journal(self):
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_path, "w", encoding="utf-8") as f:
            json.dump(self.journal, f, indent=2, ensure_ascii=False)

    def analyze_trade(
        self,
        trade_id: int,
        symbol: str,
        is_long: bool,
        entry_price: float,
        exit_price: float,
        stop_loss: float,
        take_profit: float,
        pnl_usd: float,
        exit_reason: str,
        trend_at_entry: str,
        had_rsi_div: bool
    ) -> TradeCritique:
        """
        Génère une analyse experte post-mortem du trade.
        """
        now_ts = int(time.time())

        if pnl_usd > 0:
            category = "PERFECT_EXECUTION"
            diagnosis = "Trade gagnant clôturé sur Take Profit avec respect strict du Risk/Reward 1:2+."
            recommendation = "Continuer d'appliquer les mêmes critères de sélection d'Order Blocks."
        else:
            # Diagnostic en cas de perte
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price

            if (is_long and trend_at_entry != "BULLISH") or (not is_long and trend_at_entry != "BEARISH"):
                category = "COUNTER_TREND_ERROR"
                diagnosis = "Entrée contre le biais directionnel HTF. La probabilité d'échec d'un OB à contre-tendance est très élevée."
                recommendation = "Durcir le filtre de tendance : ne prendre que les signaux alignés avec la tendance 15m/1h."
            elif sl_distance_pct < 0.0015:  # Moins de 0.15% de distance
                category = "STOP_TOO_TIGHT"
                diagnosis = f"Stop Loss trop serré ({sl_distance_pct*100:.2f}% du prix). Le trade a été sorti par une simple fluctuation de liquidité."
                recommendation = "Laisser une marge de sécurité minimale sous l'Order Block (au moins 1x ATR ou 0.20%)."
            elif not had_rsi_div:
                category = "LACK_OF_EXHAUSTION"
                diagnosis = "Entrée sur OB sans confirmation par divergence de momentum (RSI). Le flux d'ordres institutionnel n'était pas encore épuisé."
                recommendation = "Attendre systématiquement une divergence RSI ou un double sweep avant de poser l'ordre limite."
            else:
                category = "NORMAL_STATISTICAL_VARIANCE"
                diagnosis = "Toutes les règles SMC étaient respectées (Tendance, OB clair, Divergence, SL respecté). Perte normale attribuable à la variance."
                recommendation = "Ne pas altérer les paramètres. Conserver la discipline du 1% de risque."

        critique = TradeCritique(
            trade_id=trade_id,
            timestamp=now_ts,
            symbol=symbol,
            is_long=is_long,
            pnl_usd=pnl_usd,
            exit_reason=exit_reason,
            category=category,
            diagnosis=diagnosis,
            recommendation=recommendation
        )

        self.journal.append(asdict(critique))
        self._save_journal()
        return critique

    def get_summary_insights(self) -> Dict[str, Any]:
        """Agrège les statistiques des erreurs pour guider l'optimisation."""
        if not self.journal:
            return {"total_critiques": 0, "categories": {}}

        categories: Dict[str, int] = {}
        for item in self.journal:
            cat = item.get("category", "UNKNOWN")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_critiques": len(self.journal),
            "categories": categories,
            "latest_critique": self.journal[-1] if self.journal else None
        }
