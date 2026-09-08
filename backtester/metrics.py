from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import numpy as np


@dataclass
class TradeRecord:
    trade_id: int
    symbol: str
    is_long: bool
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str  # "TP", "SL", "BE", "TIME_STOP"
    fees_usd: float
    risk_reward: float
    grade: str = "5_STAR_OB"
    be_activated: bool = False
    r_multiple: float = 0.0
    bars_held: int = 0
    tp1_hit: bool = False
    tp2_hit: bool = False
    partial_pnl_usd: float = 0.0
    initial_stop_loss: float = 0.0
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass
class BacktestReport:
    initial_capital: float
    final_capital: float
    total_net_pnl: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    expectancy_usd: float
    total_fees_paid: float
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    avg_r_multiple: float = 0.0
    breakdown_by_grade: Dict[str, Any] = field(default_factory=dict)
    breakdown_by_direction: Dict[str, Any] = field(default_factory=dict)
    breakdown_by_exit: Dict[str, Any] = field(default_factory=dict)
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": round(self.initial_capital, 2),
            "final_capital": round(self.final_capital, 2),
            "total_net_pnl": round(self.total_net_pnl, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "max_drawdown_usd": round(self.max_drawdown_usd, 2),
            "expectancy_usd": round(self.expectancy_usd, 2),
            "total_fees_paid": round(self.total_fees_paid, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "avg_r_multiple": round(self.avg_r_multiple, 2),
            "breakdown_by_grade": self.breakdown_by_grade,
            "breakdown_by_direction": self.breakdown_by_direction,
            "breakdown_by_exit": self.breakdown_by_exit
        }


def calculate_backtest_metrics(
    initial_capital: float,
    trades: List[TradeRecord],
    equity_curve: List[Dict[str, Any]]
) -> BacktestReport:
    if not trades:
        return BacktestReport(
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_net_pnl=0.0,
            total_return_pct=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_usd=0.0,
            expectancy_usd=0.0,
            total_fees_paid=0.0,
            sharpe_ratio=0.0,
            calmar_ratio=0.0,
            avg_r_multiple=0.0,
            breakdown_by_grade={},
            breakdown_by_direction={},
            breakdown_by_exit={},
            trades=[],
            equity_curve=equity_curve
        )

    winning_trades = [t for t in trades if t.pnl_usd > 0]
    losing_trades = [t for t in trades if t.pnl_usd <= 0]

    gross_profit = sum(t.pnl_usd for t in winning_trades)
    gross_loss = abs(sum(t.pnl_usd for t in losing_trades))
    total_fees = sum(t.fees_usd for t in trades)
    net_pnl = sum(t.pnl_usd for t in trades)
    final_capital = initial_capital + net_pnl

    win_rate = (len(winning_trades) / len(trades)) * 100.0 if trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    # Calcul Max Drawdown sur l'equity curve
    balances = [pt["balance"] for pt in equity_curve] if equity_curve else [initial_capital, final_capital]
    peak = balances[0]
    max_dd_pct = 0.0
    max_dd_usd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd_usd = peak - b
        dd_pct = (dd_usd / peak) * 100.0 if peak > 0 else 0.0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_usd = dd_usd

    avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0.0
    avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0.0
    win_prob = len(winning_trades) / len(trades) if trades else 0.0
    loss_prob = len(losing_trades) / len(trades) if trades else 0.0
    expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)

    # Sharpe ratio
    returns = np.array([t.pnl_usd for t in trades])
    if len(returns) > 1 and np.std(returns) > 1e-8:
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(len(trades)))
    else:
        sharpe = 0.0

    # Calmar ratio
    calmar = (net_pnl / max_dd_usd) if max_dd_usd > 0 else 0.0

    # Average R multiple
    avg_r = float(np.mean([t.r_multiple for t in trades])) if trades else 0.0

    # Breakdown by Grade (5-Star OB vs 4-Star FVG)
    grade_dict = {}
    for grade in ["5_STAR_OB", "4_STAR_FVG"]:
        g_trades = [t for t in trades if t.grade == grade]
        if g_trades:
            g_wins = [t for t in g_trades if t.pnl_usd > 0]
            grade_dict[grade] = {
                "count": len(g_trades),
                "win_rate": round(len(g_wins) / len(g_trades) * 100.0, 1),
                "net_pnl": round(sum(t.pnl_usd for t in g_trades), 2)
            }

    # Breakdown by Direction (Long vs Short)
    dir_dict = {}
    for is_long in [True, False]:
        lbl = "LONG" if is_long else "SHORT"
        d_trades = [t for t in trades if t.is_long == is_long]
        if d_trades:
            d_wins = [t for t in d_trades if t.pnl_usd > 0]
            dir_dict[lbl] = {
                "count": len(d_trades),
                "win_rate": round(len(d_wins) / len(d_trades) * 100.0, 1),
                "net_pnl": round(sum(t.pnl_usd for t in d_trades), 2)
            }

    # Breakdown by Exit Reason
    exit_dict = {}
    for r in ["TP", "SL", "BE", "TIME_STOP"]:
        r_trades = [t for t in trades if t.exit_reason == r]
        exit_dict[r] = len(r_trades)

    return BacktestReport(
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_net_pnl=net_pnl,
        total_return_pct=((final_capital - initial_capital) / initial_capital) * 100.0,
        total_trades=len(trades),
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_usd=max_dd_usd,
        expectancy_usd=expectancy,
        total_fees_paid=total_fees,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        avg_r_multiple=avg_r,
        breakdown_by_grade=grade_dict,
        breakdown_by_direction=dir_dict,
        breakdown_by_exit=exit_dict,
        trades=trades,
        equity_curve=equity_curve
    )

