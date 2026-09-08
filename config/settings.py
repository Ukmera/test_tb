import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- SYMBOLS & ASSETS ---
DEFAULT_SYMBOL = "BTC"  # Hyperliquid uses raw base asset symbol 'BTC'
AVAILABLE_SYMBOLS = ["BTC", "ETH", "SOL", "BNB", "MNT"]

# --- ACCOUNT & RISK MANAGEMENT (1% STRICT) ---
INITIAL_CAPITAL_USD = 100.0
RISK_PER_TRADE_PCT = 0.01  # Strict 1% risk per trade ($1 on $100)
MAX_LEVERAGE_CAP = 10.0    # Hard ceiling to prevent excessive liquidation risk
MIN_RISK_REWARD = 2.0      # Strict minimum 1:2 Risk/Reward ratio
MAX_DAILY_DRAWDOWN_PCT = 0.05  # 5% max daily drawdown -> Kill-switch activates
MAX_CONSECUTIVE_LOSSES = 3     # Pause trading after 3 consecutive stop-losses

# --- EXECUTION & SLIPPAGE / SPREAD GUARDRAILS ---
MAX_SPREAD_PCT = 0.0004     # 0.04% max bid-ask spread permitted
MAX_SLIPPAGE_PCT = 0.0005   # 0.05% max acceptable slippage
MAKER_ONLY = True           # Use Limit/Maker orders to minimize exchange fees
ORDER_TIMEOUT_SECONDS = 2700 # Délai limite par défaut : 45 minutes (au lieu des 3 min initiales)

# Délais d'expiration adaptés au timeframe et au cycle de pullback SMC
ORDER_TIMEOUT_MAP = {
    "1m": 900,     # Scalp 1m : 15 minutes (15 bougies)
    "3m": 1800,    # Scalp 3m : 30 minutes (10 bougies)
    "5m": 2700,    # Intraday 5m : 45 minutes (9 bougies)
    "15m": 5400,   # Day 15m : 90 minutes (6 bougies)
    "1h": 14400    # Swing 1h : 4 heures
}

# --- TIMEFRAMES ---
HTF_TIMEFRAME = "1h"        # Higher Timeframe: Market Trend & Primary Key Levels
LTF_TIMEFRAME = "5m"        # Lower Timeframe: Entry triggers, sweeps, micro OB/FVG

# --- HYPERLIQUID CONFIGURATION ---
HYPERLIQUID_TESTNET = os.getenv("HYPERLIQUID_TESTNET", "true").lower() == "true"
HYPERLIQUID_WALLET_ADDRESS = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
HYPERLIQUID_PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")

# API Endpoints
HYPERLIQUID_MAINNET_API = "https://api.hyperliquid.xyz"
HYPERLIQUID_TESTNET_API = "https://api.hyperliquid-testnet.xyz"
HYPERLIQUID_API_URL = HYPERLIQUID_TESTNET_API if HYPERLIQUID_TESTNET else HYPERLIQUID_MAINNET_API

# WebSocket Endpoints
HYPERLIQUID_MAINNET_WS = "wss://api.hyperliquid.xyz/ws"
HYPERLIQUID_TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws"
HYPERLIQUID_WS_URL = HYPERLIQUID_TESTNET_WS if HYPERLIQUID_TESTNET else HYPERLIQUID_MAINNET_WS

# --- DASHBOARD & WEB SERVER ---
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 8088

# --- NOTIFICATIONS (DISCORD & TELEGRAM) ---
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

