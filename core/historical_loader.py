import time
import requests
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, List
import pandas as pd

from config.settings import BASE_DIR

CACHE_DIR = BASE_DIR / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


class HistoricalDataLoader:
    """
    Gestionnaire de données historiques institutionnel Multi-Actifs.
    Permet d'extraire des mois entiers de marché en 5m / 1h pour :
    - BTC, ETH, SOL, BNB via Binance Futures / Spot
    - MNT via Bybit Linear Klines
    - Tous les actifs via Hyperliquid DEX L2
    Mise en cache automatique en CSV local optimisé.
    """
    def __init__(self):
        self.binance_fapi_url = "https://fapi.binance.com/fapi/v1/klines"
        self.binance_spot_url = "https://api.binance.com/api/v3/klines"
        self.bybit_kline_url = "https://api.bybit.com/v5/market/kline"
        self.hyperliquid_info_url = "https://api.hyperliquid.xyz/info"

    @staticmethod
    def sanitize_label(label: str) -> str:
        """Nettoie une étiquette pour créer un nom de fichier valide sur Windows."""
        cleaned = re.sub(r'[^a-zA-Z0-9_\-]', '_', label)
        cleaned = re.sub(r'_+', '_', cleaned).strip('_')
        return cleaned

    def fetch_binance_candles_range(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "5m",
        start_time_ms: int = 0,
        end_time_ms: int = 0,
        use_futures: bool = True
    ) -> pd.DataFrame:
        base_url = self.binance_fapi_url if use_futures else self.binance_spot_url
        all_rows: List[Dict[str, Any]] = []
        current_start = start_time_ms
        batch_count = 0

        interval_mins = 5
        if interval == "1m": interval_mins = 1
        elif interval == "3m": interval_mins = 3
        elif interval == "5m": interval_mins = 5
        elif interval == "15m": interval_mins = 15
        elif interval == "1h": interval_mins = 60
        elif interval == "4h": interval_mins = 240
        step_ms = interval_mins * 60 * 1000

        while current_start < end_time_ms and batch_count < 150:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "endTime": end_time_ms,
                "limit": 1000
            }
            try:
                resp = requests.get(base_url, params=params, timeout=10)
                if resp.status_code != 200:
                    resp = requests.get(self.binance_spot_url, params=params, timeout=10)
                    if resp.status_code != 200:
                        break

                data = resp.json()
                if not data or not isinstance(data, list):
                    break

                for k in data:
                    all_rows.append({
                        "timestamp": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    })

                last_ts = int(data[-1][0])
                if last_ts <= current_start:
                    break
                current_start = last_ts + step_ms
                batch_count += 1
                time.sleep(0.04)
            except Exception as e:
                time.sleep(0.5)
                batch_count += 1

        if not all_rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_rows)
        df.drop_duplicates(subset=["timestamp"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        df = df[(df['timestamp'] >= start_time_ms) & (df['timestamp'] <= end_time_ms)].copy().reset_index(drop=True)
        return df

    def fetch_bybit_candles_range(
        self,
        symbol: str = "MNTUSDT",
        interval: str = "5m",
        start_time_ms: int = 0,
        end_time_ms: int = 0
    ) -> pd.DataFrame:
        """Récupère les bougies historiques linéaires depuis Bybit."""
        bybit_interval = "5"
        interval_mins = 5
        if interval == "1m": bybit_interval, interval_mins = "1", 1
        elif interval == "3m": bybit_interval, interval_mins = "3", 3
        elif interval == "5m": bybit_interval, interval_mins = "5", 5
        elif interval == "15m": bybit_interval, interval_mins = "15", 15
        elif interval == "1h": bybit_interval, interval_mins = "60", 60
        elif interval == "4h": bybit_interval, interval_mins = "240", 240
        step_ms = interval_mins * 60 * 1000

        all_rows: List[Dict[str, Any]] = []
        cur_end = end_time_ms
        batch_count = 0

        while cur_end > start_time_ms and batch_count < 150:
            params = {
                "category": "linear",
                "symbol": symbol,
                "interval": bybit_interval,
                "start": start_time_ms,
                "end": cur_end,
                "limit": 1000
            }
            try:
                resp = requests.get(self.bybit_kline_url, params=params, timeout=10)
                if resp.status_code != 200:
                    break
                data = resp.json()
                klines = data.get("result", {}).get("list", [])
                if not klines:
                    break

                for k in klines:
                    all_rows.append({
                        "timestamp": int(k[0]),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5])
                    })

                oldest_in_batch = min(int(k[0]) for k in klines)
                if oldest_in_batch <= start_time_ms or oldest_in_batch >= cur_end:
                    break
                cur_end = oldest_in_batch - 1
                batch_count += 1
                time.sleep(0.04)
            except Exception:
                time.sleep(0.5)
                batch_count += 1

        if not all_rows:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_rows)
        df.drop_duplicates(subset=["timestamp"], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        df = df[(df['timestamp'] >= start_time_ms) & (df['timestamp'] <= end_time_ms)].copy().reset_index(drop=True)
        return df

    def fetch_hyperliquid_candles_range(
        self,
        coin: str = "BTC",
        interval: str = "5m",
        start_time_ms: int = 0,
        end_time_ms: int = 0
    ) -> pd.DataFrame:
        """Récupère les bougies natives depuis Hyperliquid L2."""
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms
            }
        }
        headers = {"Content-Type": "application/json"}
        try:
            resp = requests.post(self.hyperliquid_info_url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list):
                    rows = [{
                        "timestamp": int(c["t"]),
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c["v"])
                    } for c in data]
                    df = pd.DataFrame(rows)
                    df.sort_values("timestamp", inplace=True)
                    df.reset_index(drop=True, inplace=True)
                    return df
        except Exception:
            pass
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def get_month_data(
        self,
        month_label: str,
        start_date: str,
        end_date: str,
        symbol: str = "BTC",
        ltf_interval: str = "5m",
        htf_interval: str = "1h",
        use_cache: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Charge les DataFrames LTF et HTF pour le symbole et la période donnés.
        Supporte BTC, ETH, SOL, BNB, MNT.
        """
        clean_label = self.sanitize_label(month_label)
        clean_sym = symbol.upper().replace("USDT", "")
        ltf_cache_file = CACHE_DIR / f"{clean_sym}_{ltf_interval}_{clean_label}.csv"
        htf_cache_file = CACHE_DIR / f"{clean_sym}_{htf_interval}_{clean_label}.csv"

        if use_cache and ltf_cache_file.exists() and htf_cache_file.exists():
            ltf_df = pd.read_csv(ltf_cache_file)
            htf_df = pd.read_csv(htf_cache_file)
            if len(ltf_df) > 300:
                print(f"[{clean_sym} - {month_label}] Cache touché ({len(ltf_df)} {ltf_interval}, {len(htf_df)} {htf_interval})")
                return htf_df, ltf_df

        st = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        et = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        htf_st = st - (150 * 3600 * 1000)

        print(f"[{clean_sym} - {month_label}] Téléchargement de {start_date} à {end_date}...")

        if clean_sym == "MNT":
            ltf_df = self.fetch_bybit_candles_range("MNTUSDT", ltf_interval, st, et)
            htf_df = self.fetch_bybit_candles_range("MNTUSDT", htf_interval, htf_st, et)
            if ltf_df.empty:
                ltf_df = self.fetch_hyperliquid_candles_range("MNT", ltf_interval, st, et)
                htf_df = self.fetch_hyperliquid_candles_range("MNT", htf_interval, htf_st, et)
        else:
            binance_pair = f"{clean_sym}USDT"
            ltf_df = self.fetch_binance_candles_range(binance_pair, ltf_interval, st, et, use_futures=True)
            htf_df = self.fetch_binance_candles_range(binance_pair, htf_interval, htf_st, et, use_futures=True)

        if not ltf_df.empty:
            ltf_df.to_csv(ltf_cache_file, index=False)
        if not htf_df.empty:
            htf_df.to_csv(htf_cache_file, index=False)

        print(f"[{clean_sym} - {month_label}] OK: {len(ltf_df)} {ltf_interval}, {len(htf_df)} {htf_interval}")
        return htf_df, ltf_df
