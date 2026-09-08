import tempfile
from pathlib import Path
import pandas as pd
from backtester.metrics import BacktestReport, TradeRecord
from backtester.report_manager import BacktestReportManager


def test_report_manager_save_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_dir = Path(tmpdir)
        mgr = BacktestReportManager(storage_dir=storage_dir)

        trade1 = TradeRecord(
            trade_id=1,
            symbol="BTC",
            is_long=True,
            entry_time=1700000000000,
            exit_time=1700001000000,
            entry_price=60000.0,
            exit_price=60500.0,
            stop_loss=59800.0,
            take_profit=60400.0,
            position_size=0.01,
            pnl_usd=5.0,
            pnl_pct=5.0,
            exit_reason="TP",
            fees_usd=0.2,
            risk_reward=2.0,
            grade="5_STAR_OB",
            be_activated=True,
            r_multiple=2.0,
            bars_held=5
        )

        report = BacktestReport(
            initial_capital=100.0,
            final_capital=104.8,
            total_net_pnl=4.8,
            total_return_pct=4.8,
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            win_rate_pct=100.0,
            profit_factor=999.0,
            max_drawdown_pct=0.0,
            max_drawdown_usd=0.0,
            expectancy_usd=4.8,
            total_fees_paid=0.2,
            sharpe_ratio=2.5,
            calmar_ratio=1.0,
            avg_r_multiple=2.0,
            breakdown_by_grade={"5_STAR_OB": {"count": 1, "win_rate": 100.0, "net_pnl": 4.8}},
            breakdown_by_direction={"LONG": {"count": 1, "win_rate": 100.0, "net_pnl": 4.8}},
            breakdown_by_exit={"TP": 1},
            trades=[trade1],
            equity_curve=[{"timestamp": 1700000000000, "balance": 100.0}, {"timestamp": 1700001000000, "balance": 104.8}]
        )

        candles = [
            {"timestamp": 1700000000000, "open": 60000.0, "high": 60600.0, "low": 59700.0, "close": 60500.0, "volume": 10}
        ]

        run_id = mgr.save_run(report, candles, coin="BTC", interval="15m", model="B")
        assert run_id.startswith("run_")

        # Vérifier l'index
        history = mgr.get_history()
        assert len(history) == 1
        assert history[0]["run_id"] == run_id
        assert history[0]["total_net_pnl"] == 4.8
        assert history[0]["win_rate_pct"] == 100.0

        # Vérifier la récupération du run complet
        loaded_run = mgr.get_run(run_id)
        assert loaded_run is not None
        assert loaded_run["run_id"] == run_id
        assert len(loaded_run["trades"]) == 1
        assert loaded_run["trades"][0]["grade"] == "5_STAR_OB"
        assert loaded_run["trades"][0]["be_activated"] is True
