import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import (
    BASE_DIR,
    DEFAULT_SYMBOL,
    INITIAL_CAPITAL_USD,
    RISK_PER_TRADE_PCT,
    MAX_SPREAD_PCT
)
from core.data_feed import HyperliquidDataFeed, CACHE_DIR
from core.smc_engine import SMCEngine
from core.risk_manager import RiskManager
from backtester.engine import SMCBacktester
from bots.agents.desk_team import ProfessorAgent
from bots.paper_trading_daemon import PaperTradingDaemon

app = FastAPI(title="SMC Institutional Trading Desk", version="1.0.0")

# Autoriser CORS pour les requêtes locales
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

data_feed = HyperliquidDataFeed()
smc_engine = SMCEngine()
risk_mgr = RiskManager()
import threading

professor = ProfessorAgent(symbol=DEFAULT_SYMBOL, initial_balance=INITIAL_CAPITAL_USD)
paper_trader = PaperTradingDaemon(symbol=DEFAULT_SYMBOL, model="B", initial_capital=INITIAL_CAPITAL_USD)

def _paper_trading_background_loop():
    """Worker en arrière-plan autonome pour ne jamais bloquer les requêtes HTTP de l'utilisateur."""
    print("[Paper Trading Background Worker] Démon temps réel autonome actif (cycle 8s).")
    # Premier cycle immédiat
    try:
        if paper_trader.is_running:
            paper_trader.step()
    except Exception as e:
        print(f"[Paper Trading Initial Step Error] {e}")

    while True:
        time.sleep(8)
        try:
            if paper_trader.is_running:
                paper_trader.step()
        except Exception as e:
            print(f"[Paper Trading Worker Error] {e}")

_bg_thread = threading.Thread(target=_paper_trading_background_loop, daemon=True)
_bg_thread.start()

STATIC_DIR = BASE_DIR / "dashboard" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def get_dashboard_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI not found.")
    return FileResponse(index_path)


@app.get("/api/paper-trading")
def get_paper_trading_state() -> Dict[str, Any]:
    """Retourne instantanément l'état en mémoire du Paper Trading (< 1ms, zéro lag UI)."""
    return paper_trader.get_state()


@app.post("/api/paper-trading/toggle")
def toggle_paper_trading() -> Dict[str, Any]:
    """Active ou désactive l'exécution automatique du Paper Trading."""
    paper_trader.is_running = not paper_trader.is_running
    return {"is_running": paper_trader.is_running}


@app.post("/api/paper-trading/model")
def set_paper_trading_model(model: str = "B") -> Dict[str, Any]:
    """Change le modèle actif (A: 1m Scalp vs B: 15m Structurel)."""
    model_code = model.upper()
    if model_code not in ["A", "B"]:
        raise HTTPException(status_code=400, detail="Modèle invalide. Utilisez 'A' ou 'B'.")
    paper_trader.model = model_code
    paper_trader.interval = "1m" if model_code == "A" else "5m"
    return {"status": "success", "model": paper_trader.model, "interval": paper_trader.interval}


@app.post("/api/paper-trading/basket")
def set_paper_trading_basket(basket: str = "alpha") -> Dict[str, Any]:
    """Change le panier actif visualisé dans le dashboard (alpha, quad, core)."""
    b_key = basket.lower()
    if b_key not in paper_trader.baskets:
        raise HTTPException(status_code=400, detail=f"Panier invalide '{basket}'. Choix: {list(paper_trader.baskets.keys())}")
    paper_trader.set_active_basket(b_key)
    return {
        "status": "success",
        "active_basket_key": paper_trader.active_basket_key,
        "active_basket_name": paper_trader.active_basket.name,
        "symbols": paper_trader.active_basket.symbols
    }


@app.post("/api/paper-trading/strategy")
def set_paper_trading_strategy(basket: str = "alpha", strategy: str = "scalp") -> Dict[str, Any]:
    """Change la sous-stratégie active visualisée pour un panier (scalp, intraday, day)."""
    b_key = basket.lower()
    if b_key not in paper_trader.baskets:
        raise HTTPException(status_code=400, detail=f"Panier invalide '{basket}'. Choix: {list(paper_trader.baskets.keys())}")
    b = paper_trader.baskets[b_key]
    s_key = strategy.lower()
    if s_key not in b.strategies:
        raise HTTPException(status_code=400, detail=f"Stratégie invalide '{strategy}'. Choix: {list(b.strategies.keys())}")
    b.active_strategy_id = s_key
    paper_trader.set_active_basket(b_key)
    paper_trader.save_state()
    return {
        "status": "success",
        "active_basket_key": b_key,
        "active_strategy_id": s_key,
        "interval": b.primary_track.interval,
        "symbols": b.symbols
    }


@app.post("/api/paper-trading/reset")
def reset_paper_trading() -> Dict[str, Any]:
    """Réinitialise les portefeuilles de simulation à 100$ et efface l'historique persistant."""
    return paper_trader.reset_state()


class TelegramDetectRequest(BaseModel):
    token: str


class TelegramTestRequest(BaseModel):
    token: Optional[str] = None
    chat_id: Optional[str] = None


class TelegramSaveRequest(BaseModel):
    token: str
    chat_id: str


@app.get("/api/notifications/status")
def get_notifications_status() -> Dict[str, Any]:
    """Retourne l'état de configuration des alertes push (Telegram & Discord)."""
    return paper_trader.notifier.get_status()


@app.post("/api/notifications/telegram/detect")
def detect_telegram_chat_id(req: TelegramDetectRequest) -> Dict[str, Any]:
    """Détecte automatiquement le chat_id de l'utilisateur via l'API getUpdates de Telegram."""
    return paper_trader.notifier.detect_chat_id(token=req.token)


@app.post("/api/notifications/telegram/test")
def test_telegram_notification(req: TelegramTestRequest) -> Dict[str, Any]:
    """Envoie une notification de test immédiate sur le smartphone de l'utilisateur."""
    return paper_trader.notifier.send_test_message(token=req.token, chat_id=req.chat_id)


@app.post("/api/notifications/telegram/save")
def save_telegram_config(req: TelegramSaveRequest) -> Dict[str, Any]:
    """Enregistre les identifiants Telegram dans le fichier .env et met à jour l'instance active."""
    token = req.token.strip()
    chat_id = req.chat_id.strip()
    paper_trader.notifier.update_telegram_credentials(token, chat_id)

    # Sauvegarde persistante dans .env local
    env_path = BASE_DIR / ".env"
    existing_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    keys_to_set = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}
    new_lines = []
    for line in existing_lines:
        line_clean = line.strip()
        if "=" in line_clean and not line_clean.startswith("#"):
            k = line_clean.split("=", 1)[0].strip()
            if k in keys_to_set:
                new_lines.append(f"{k}={keys_to_set[k]}\n")
                del keys_to_set[k]
                continue
        new_lines.append(line)

    for k, v in keys_to_set.items():
        new_lines.append(f"{k}={v}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {
        "status": "success",
        "message": "Identifiants Telegram enregistrés avec succès.",
        "notifier_status": paper_trader.notifier.get_status()
    }





@app.get("/api/agents")
def get_agents_status() -> Dict[str, Any]:
    """Retourne l'état de la brigade d'agents, la porte de veto Palermo et le flux d'activité en temps réel."""
    return paper_trader.professor.get_team_status()




@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Retourne l'état du système, le prix actuel, le spread et le statut des garde-fous."""
    best_bid, best_ask, spread = data_feed.fetch_order_book("BTC")
    guard_check = risk_mgr.check_guardrails(best_bid, best_ask)

    basket_cap = paper_trader.active_basket.total_balance if hasattr(paper_trader.active_basket, "total_balance") else risk_mgr.current_balance

    return {
        "symbol": "BTC",
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_pct": round(spread * 100, 4),
        "spread_allowed": guard_check.allowed,
        "guardrail_message": guard_check.reason,
        "kill_switch_active": risk_mgr.kill_switch_active,
        "consecutive_losses": risk_mgr.consecutive_losses,
        "capital_usd": round(basket_cap, 2),
        "risk_per_trade_pct": round(risk_mgr.risk_pct * 100, 2)
    }


from backtester.report_manager import BacktestReportManager

report_manager = BacktestReportManager()


@app.get("/api/candles")
def get_candles(coin: str = "BTC", interval: str = "15m", limit: int = 300) -> Dict[str, Any]:
    """
    Récupère les bougies récentes et exécute l'analyse SMC en direct
    avec tous les composants visuels (OB, FVG + 50% CE, Swings, Trendlines,
    BOS/CHoCH, Range 50% Eq, Fib OTE, et Brackets).
    """
    df = data_feed.fetch_candles(coin=coin, interval=interval, limit_candles=limit)
    if df.empty:
        cached = data_feed.load_cached_data(coin, interval)
        if cached is not None and not cached.empty:
            df = cached.tail(limit).reset_index(drop=True)
        else:
            return {"candles": [], "smc": {}}

    analysis = smc_engine.analyze(df)

    candles_data = []
    for _, row in df.iterrows():
        candles_data.append({
            "time": int(row["timestamp"]) // 1000,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"])
        })

    # OTE Sérialisé
    ote_dict = None
    if analysis.active_ote is not None:
        ote = analysis.active_ote
        ote_dict = {
            "is_bullish": ote.is_bullish,
            "swing_low": round(ote.swing_low, 2),
            "swing_high": round(ote.swing_high, 2),
            "fib_618": round(ote.fib_618, 2),
            "fib_705": round(ote.fib_705, 2),
            "fib_790": round(ote.fib_790, 2)
        }

    smc_data = {
        "trend": analysis.trend.value,
        "htf_trend": analysis.htf_trend.value if analysis.htf_trend else analysis.trend.value,
        "current_atr": round(analysis.current_atr, 2),
        "order_blocks": [
            {
                "index": ob.index,
                "time": int(ob.timestamp) // 1000,
                "top": round(ob.top, 2),
                "bottom": round(ob.bottom, 2),
                "mean_threshold": round(ob.mean_threshold, 2),
                "is_bullish": ob.is_bullish,
                "mitigated": ob.mitigated
            }
            for ob in analysis.order_blocks
        ],
        "fvgs": [
            {
                "index": f.index,
                "time": int(f.timestamp) // 1000,
                "top": round(f.top, 2),
                "bottom": round(f.bottom, 2),
                "consequent_encroachment": round(f.consequent_encroachment, 2),
                "is_bullish": f.is_bullish,
                "mitigated": f.mitigated
            }
            for f in analysis.fvgs
        ],
        "swings": [
            {
                "index": s.index,
                "time": int(s.timestamp) // 1000,
                "price": round(s.price, 2),
                "is_high": s.is_high
            }
            for s in analysis.swings
        ],
        "structures": [
            {
                "type": st["type"],
                "direction": st["direction"],
                "time": int(st.get("timestamp", 0)) // 1000,
                "level": round(st["level"], 2)
            }
            for st in analysis.structures
        ],
        "range_info": analysis.range_info,
        "trendlines": analysis.trendlines,
        "active_ote": ote_dict,
        "setups": [
            {
                "grade": c.grade,
                "is_long": c.is_long,
                "entry_price": round(c.entry_price, 2),
                "stop_loss": round(c.stop_loss, 2),
                "take_profit_1r": round(c.take_profit_1r, 2),
                "take_profit_2r": round(c.take_profit_2r, 2),
                "breakeven_level": round(c.entry_price, 2)
            }
            for c in analysis.setups
        ]
    }

    return {
        "candles": candles_data,
        "smc": smc_data
    }


@app.get("/api/backtest")
def get_backtest_data() -> Dict[str, Any]:
    """Renvoie les données du dernier backtest pour le moteur de Playback."""
    cache_file = CACHE_DIR / "latest_backtest.json"
    if not cache_file.exists():
        raise HTTPException(status_code=404, detail="Aucun résultat de backtest trouvé. Lancez un backtest d'abord.")

    with open(cache_file, "r") as f:
        data = json.load(f)
    return data


@app.get("/api/backtest/history")
def get_backtest_history() -> List[Dict[str, Any]]:
    """Retourne l'historique complet de tous les backtests sauvegardés pour le tableau comparatif."""
    return report_manager.get_history()


@app.get("/api/backtest/run/{run_id}")
def load_historical_run(run_id: str) -> Dict[str, Any]:
    """Charge un backtest historique spécifique pour réexamen et rejeu Playback."""
    run_data = report_manager.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run {run_id} non trouvé dans l'historique.")

    # Synchroniser comme backtest courant pour le playback
    cache_file = CACHE_DIR / "latest_backtest.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(run_data, f, indent=2)

    return run_data


@app.post("/api/run-backtest")
def trigger_backtest(
    coin: str = "BTC",
    interval: str = "15m",
    model: str = "B",
    limit: int = 3000,
    days_back: Optional[int] = None,
    start_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Déclenche un calcul de backtest sur un large historique (3 000+ bougies) avec synchronisation Multi-Timeframe.
    Archivage persistant automatique dans BacktestReportManager pour comparaison continue.
    """
    target = limit if limit >= 500 else 3000
    htf_interval = "1h"

    # Récupération des données synchronisées MTF (HTF 1H + LTF)
    try:
        htf_df, ltf_df = data_feed.fetch_mtf_data(
            coin=coin,
            htf_interval=htf_interval,
            ltf_interval=interval,
            target_ltf_candles=target,
            use_cache=True
        )
    except Exception as e:
        print(f"[Backtest MTF Warning] Erreur MTF: {e}, repli sur mono-timeframe.")
        htf_df = None
        ltf_df = data_feed.fetch_large_historical_data(coin=coin, interval=interval, target_candles=target, use_cache=True)

    if ltf_df.empty:
        raise HTTPException(status_code=500, detail="Impossible de récupérer les bougies de marché pour cette période.")

    df = ltf_df
    backtester = SMCBacktester(initial_capital=INITIAL_CAPITAL_USD, risk_pct=RISK_PER_TRADE_PCT, model=model)
    report = backtester.run(df, htf_df=htf_df)

    # Archivage persistant immuable
    run_id = report_manager.save_run(
        report=report,
        candles_df_or_dict=df,
        coin=coin,
        interval=interval,
        model=model
    )

    # Synchronisation latest pour le playback
    latest_data = {
        "run_id": run_id,
        "summary": report.summary_dict(),
        "trades": [t.__dict__ for t in report.trades],
        "equity_curve": report.equity_curve,
        "candles": df.to_dict(orient="records"),
        "period": {
            "start_time": int(df['timestamp'].iloc[0]) if not df.empty else 0,
            "end_time": int(df['timestamp'].iloc[-1]) if not df.empty else 0,
            "interval": interval,
            "candle_count": len(df)
        }
    }
    cache_file = CACHE_DIR / "latest_backtest.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(latest_data, f, indent=2)

    return {
        "status": "success",
        "run_id": run_id,
        "summary": report.summary_dict(),
        "candles_loaded": len(df)
    }

