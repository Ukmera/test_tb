import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from config.settings import BASE_DIR
from backtester.metrics import BacktestReport

BACKTESTS_DIR = BASE_DIR / "data_cache" / "backtests"
BACKTESTS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = BACKTESTS_DIR / "history_index.json"


class BacktestReportManager:
    """
    Gère la persistance, l'indexation et l'analyse comparative des bilans de backtesting.
    Chaque run est archivé de manière immuable avec ses métriques institutionnelles
    pour permettre le suivi de performance au fil des optimisations.
    """

    def __init__(self, storage_dir: Path = BACKTESTS_DIR):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "history_index.json"
        if not self.index_file.exists():
            self._write_index([])

    def _read_index(self) -> List[Dict[str, Any]]:
        if not self.index_file.exists():
            return []
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_index(self, index_data: List[Dict[str, Any]]):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2)

    def save_run(
        self,
        report: BacktestReport,
        candles_df_or_dict: Any,
        coin: str = "BTC",
        interval: str = "15m",
        model: str = "B",
        run_name: Optional[str] = None
    ) -> str:
        """
        Enregistre un nouveau run de backtest complet et met à jour l'index d'historique.
        """
        timestamp_now = int(time.time())
        date_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(timestamp_now))
        run_id = f"run_{date_str}_{model}_{interval}"
        if run_name:
            run_id = f"{run_id}_{run_name}"

        # Formater les bougies
        if hasattr(candles_df_or_dict, "to_dict"):
            candles = candles_df_or_dict.to_dict(orient="records")
        else:
            candles = candles_df_or_dict

        run_data = {
            "run_id": run_id,
            "created_at": timestamp_now,
            "created_date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp_now)),
            "coin": coin,
            "interval": interval,
            "model": model,
            "candles_count": len(candles),
            "summary": report.summary_dict(),
            "trades": [t.__dict__ for t in report.trades],
            "equity_curve": report.equity_curve,
            "candles": candles,
            "period": {
                "start_time": int(candles[0]["timestamp"]) if candles else 0,
                "end_time": int(candles[-1]["timestamp"]) if candles else 0,
                "interval": interval,
                "candle_count": len(candles)
            }
        }

        # Écriture du fichier du run
        run_file = self.storage_dir / f"{run_id}.json"
        with open(run_file, "w", encoding="utf-8") as f:
            json.dump(run_data, f, indent=2)

        # Mise à jour de l'index résumé
        index = self._read_index()
        summary_entry = {
            "run_id": run_id,
            "created_date": run_data["created_date"],
            "coin": coin,
            "interval": interval,
            "model": model,
            "candles_count": len(candles),
            "initial_capital": report.initial_capital,
            "final_capital": report.final_capital,
            "total_net_pnl": report.total_net_pnl,
            "total_return_pct": report.total_return_pct,
            "total_trades": report.total_trades,
            "win_rate_pct": report.win_rate_pct,
            "profit_factor": report.profit_factor,
            "max_drawdown_pct": report.max_drawdown_pct,
            "sharpe_ratio": report.sharpe_ratio,
            "calmar_ratio": report.calmar_ratio,
            "avg_r_multiple": report.avg_r_multiple,
            "breakdown_by_grade": report.breakdown_by_grade,
            "breakdown_by_exit": report.breakdown_by_exit
        }

        # Remplacer si même ID, sinon ajouter en tête
        index = [e for e in index if e.get("run_id") != run_id]
        index.insert(0, summary_entry)
        self._write_index(index)

        print(f"[ReportManager] Run {run_id} archivé avec succès dans l'historique ({report.total_trades} trades, Return: {report.total_return_pct:.2f}%).")
        return run_id

    def get_history(self) -> List[Dict[str, Any]]:
        """Retourne la liste résumée de tous les runs pour le tableau comparatif."""
        return self._read_index()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Charge l'intégralité d'un run passé pour rejeu dans le playback."""
        run_file = self.storage_dir / f"{run_id}.json"
        if not run_file.exists():
            return None
        try:
            with open(run_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ReportManager Error] Échec de lecture de {run_id}: {e}")
            return None
