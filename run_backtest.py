import json
import time
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from core.data_feed import HyperliquidDataFeed, CACHE_DIR
from backtester.engine import SMCBacktester
from backtester.metrics import BacktestReport



def run_model_simulation(feed: HyperliquidDataFeed, model_name: str, interval: str, limit: int = 500):
    print(f"\n⚡ Exécution {model_name} [Intervalle: {interval}]...")
    df = feed.fetch_candles(coin="BTC", interval=interval, limit_candles=limit)
    if df.empty:
        print(f"❌ Données non disponibles pour {interval}.")
        return None, None

    model_code = "A" if "A" in model_name else "B"
    backtester = SMCBacktester(initial_capital=100.0, risk_pct=0.01, min_rr=2.0, model=model_code)
    report = backtester.run(df)
    return report, df


def main():
    print("=" * 65)
    print("🚀 BENCHMARK COMPARATIF SMC : MODÈLE A (SCALP 1M) vs MODÈLE B (STRUCTURE 15M)")
    print("=" * 65)

    feed = HyperliquidDataFeed()

    # 1. Modèle B : Structurel 15m
    report_b, df_b = run_model_simulation(feed, "MODÈLE B (Structured)", "15m", limit=600)

    # 2. Modèle A : Fast Scalp 1m
    report_a, df_a = run_model_simulation(feed, "MODÈLE A (Fast Scalp)", "1m", limit=600)

    print("\n" + "=" * 65)
    print(f"{'MÉTRIQUE':<26} | {'MODÈLE A (1M)':<16} | {'MODÈLE B (15M)':<16}")
    print("=" * 65)

    if report_a and report_b:
        sum_a = report_a.summary_dict()
        sum_b = report_b.summary_dict()

        for key in ["total_trades", "win_rate_pct", "profit_factor", "total_net_pnl", "total_return_pct", "max_drawdown_pct"]:
            val_a = str(sum_a.get(key, "--"))
            val_b = str(sum_b.get(key, "--"))
            print(f"{key:<26} | {val_a:<16} | {val_b:<16}")
    print("=" * 65)

    # Sauvegarder par défaut le Modèle B dans latest_backtest.json pour le playback du dashboard
    if report_b and df_b is not None:
        result_data = {
            "summary": report_b.summary_dict(),
            "trades": [t.__dict__ for t in report_b.trades],
            "equity_curve": report_b.equity_curve,
            "candles": df_b.to_dict(orient="records"),
            "model": "B"
        }
        cache_file = CACHE_DIR / "latest_backtest.json"
        with open(cache_file, "w") as f:
            json.dump(result_data, f, indent=2)
        print(f"💾 Résultats du Modèle B sauvegardés dans {cache_file} (disponibles en Playback).")


if __name__ == "__main__":
    main()

