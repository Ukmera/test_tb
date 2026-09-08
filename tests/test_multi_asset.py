import pytest
import pandas as pd
from core.multi_asset_engine import MultiAssetPortfolioEngine


def test_multi_asset_engine_init():
    engine = MultiAssetPortfolioEngine(
        initial_capital=100.0,
        max_concurrent_positions=3,
        risk_per_trade_sweep=0.007,
        risk_per_trade_cont=0.004,
        session_filter=True
    )
    assert engine.max_concurrent_positions == 3
    assert engine.initial_capital == 100.0
    assert engine.session_filter is True
    assert engine.risk_sweep == 0.007
    assert engine.risk_cont == 0.004


def test_multi_asset_simulation_empty():
    engine = MultiAssetPortfolioEngine(initial_capital=100.0)
    res = engine.run({"BTC": {"ltf": pd.DataFrame(), "htf": pd.DataFrame()}})
    assert "error" in res


def test_multi_asset_synthetic_feed():
    engine = MultiAssetPortfolioEngine(initial_capital=100.0, max_concurrent_positions=2)
    times = [1700000000000 + i * 300000 for i in range(80)]
    df_btc = pd.DataFrame({
        "timestamp": times,
        "open": [60000.0 + i * 10 for i in range(80)],
        "high": [60050.0 + i * 10 for i in range(80)],
        "low": [59950.0 + i * 10 for i in range(80)],
        "close": [60010.0 + i * 10 for i in range(80)],
        "volume": [100.0] * 80
    })
    df_eth = pd.DataFrame({
        "timestamp": times,
        "open": [3000.0 + i * 2 for i in range(80)],
        "high": [3020.0 + i * 2 for i in range(80)],
        "low": [2980.0 + i * 2 for i in range(80)],
        "close": [3005.0 + i * 2 for i in range(80)],
        "volume": [500.0] * 80
    })

    market_data = {
        "BTC": {"ltf": df_btc, "htf": pd.DataFrame()},
        "ETH": {"ltf": df_eth, "htf": pd.DataFrame()}
    }

    res = engine.run(market_data, warmup_candles=40)
    assert "summary" in res
    assert "per_symbol" in res
    assert "BTC" in res["per_symbol"]
    assert "ETH" in res["per_symbol"]
    assert "all_trades" in res

