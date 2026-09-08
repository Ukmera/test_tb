import os
import json
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import requests
import pandas as pd
from config.settings import HYPERLIQUID_MAINNET_API, BASE_DIR

CACHE_DIR = BASE_DIR / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


class HyperliquidDataFeed:
    def __init__(self, api_url: str = HYPERLIQUID_MAINNET_API):
        self.api_url = api_url.rstrip("/")
        self.info_url = f"{self.api_url}/info"

    def fetch_candles(
        self,
        coin: str = "BTC",
        interval: str = "15m",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit_candles: int = 300
    ) -> pd.DataFrame:
        """
        Récupère les bougies historiques depuis Hyperliquid.
        Convertit les données en DataFrame standardisé (timestamp, open, high, low, close, volume).
        """
        now_ms = int(time.time() * 1000)
        if end_time_ms is None:
            end_time_ms = now_ms

        if start_time_ms is None:
            # Estimation en fonction de l'intervalle
            interval_minutes = 15
            if interval == "1m":
                interval_minutes = 1
            elif interval == "3m":
                interval_minutes = 3
            elif interval == "5m":
                interval_minutes = 5
            elif interval == "15m":
                interval_minutes = 15
            elif interval == "1h":
                interval_minutes = 60
            elif interval == "4h":
                interval_minutes = 240
            start_time_ms = end_time_ms - (limit_candles * interval_minutes * 60 * 1000)

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
            resp = requests.post(self.info_url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data or not isinstance(data, list):
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

            rows = []
            for c in data:
                rows.append({
                    "timestamp": int(c["t"]),
                    "open": float(c["o"]),
                    "high": float(c["h"]),
                    "low": float(c["l"]),
                    "close": float(c["c"]),
                    "volume": float(c["v"])
                })

            df = pd.DataFrame(rows)
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
        except Exception as e:
            print(f"[DataFeed Error] Échec de la récupération des bougies {coin} ({interval}): {e}")
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def fetch_order_book(self, coin: str = "BTC") -> Tuple[float, float, float]:
        """
        Récupère le carnet d'ordres L2 et renvoie (best_bid, best_ask, spread_pct).
        """
        payload = {
            "type": "l2Book",
            "coin": coin
        }
        try:
            resp = requests.post(self.info_url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
            resp.raise_for_status()
            book = resp.json()
            levels = book.get("levels", [])
            if len(levels) >= 2 and len(levels[0]) > 0 and len(levels[1]) > 0:
                best_bid = float(levels[0][0]["px"])
                best_ask = float(levels[1][0]["px"])
                spread_pct = (best_ask - best_bid) / best_bid if best_bid > 0 else 0.0
                return best_bid, best_ask, spread_pct
        except Exception as e:
            print(f"[DataFeed Error] Impossible de lire le carnet d'ordres pour {coin}: {e}")
        return 0.0, 0.0, 1.0

    def cache_historical_data(self, df: pd.DataFrame, coin: str, interval: str, suffix: str = "historical") -> Path:
        """Sauvegarde les bougies en cache local CSV pour les backtests hors ligne."""
        file_path = CACHE_DIR / f"{coin}_{interval}_{suffix}.csv"
        df.to_csv(file_path, index=False)
        return file_path

    def load_cached_data(self, coin: str, interval: str, suffix: str = "historical") -> Optional[pd.DataFrame]:
        file_path = CACHE_DIR / f"{coin}_{interval}_{suffix}.csv"
        if file_path.exists():
            df = pd.read_csv(file_path)
            return df
        return None

    def fetch_large_historical_data(
        self,
        coin: str = "BTC",
        interval: str = "15m",
        target_candles: int = 3000,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Récupère un historique massif de bougies (3 000+ bougies) en effectuant
        si nécessaire des requêtes par lots successifs vers l'arrière dans le temps.
        Met en cache les données localement pour une exécution ultra-rapide sans latence API.
        """
        cache_key = f"{target_candles}bars"
        if use_cache:
            cached_df = self.load_cached_data(coin, interval, suffix=cache_key)
            if cached_df is not None and len(cached_df) >= target_candles * 0.95:
                print(f"[DataFeed] Chargement depuis le cache local ({len(cached_df)} bougies {coin} {interval})")
                return cached_df

        # Calcul de la durée par bougie en ms
        interval_ms = 15 * 60 * 1000
        if interval == "1m": interval_ms = 60 * 1000
        elif interval == "3m": interval_ms = 3 * 60 * 1000
        elif interval == "5m": interval_ms = 5 * 60 * 1000
        elif interval == "15m": interval_ms = 15 * 60 * 1000
        elif interval == "1h": interval_ms = 60 * 60 * 1000
        elif interval == "4h": interval_ms = 4 * 60 * 60 * 1000

        all_dfs = []
        current_end_ms = int(time.time() * 1000)
        remaining = target_candles
        batch_size = min(4500, target_candles)
        max_batches = 10
        batches_done = 0

        print(f"[DataFeed] Début du téléchargement multi-lots de {target_candles} bougies {coin} ({interval})...")

        while remaining > 0 and batches_done < max_batches:
            batch_candles = min(4500, remaining + 100)
            start_ms = current_end_ms - (batch_candles * interval_ms)

            batch_df = self.fetch_candles(
                coin=coin,
                interval=interval,
                start_time_ms=start_ms,
                end_time_ms=current_end_ms,
                limit_candles=batch_candles
            )

            if batch_df.empty:
                break

            all_dfs.append(batch_df)
            batches_done += 1
            oldest_ts = int(batch_df['timestamp'].iloc[0])
            current_end_ms = oldest_ts - 1
            remaining = target_candles - sum(len(d) for d in all_dfs)

            # Si le lot retourné a moins de 50 bougies, on a atteint le début de l'historique dispo
            if len(batch_df) < 50:
                break

            time.sleep(0.1)  # Respect de cadence d'API Hyperliquid

        if not all_dfs:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        merged = pd.concat(all_dfs, ignore_index=True)
        merged.drop_duplicates(subset=["timestamp"], inplace=True)
        merged.sort_values("timestamp", inplace=True)
        merged.reset_index(drop=True, inplace=True)

        if len(merged) > target_candles:
            merged = merged.iloc[-target_candles:].copy().reset_index(drop=True)

        print(f"[DataFeed] Téléchargement terminé : {len(merged)} bougies obtenues. Mise en cache.")
        self.cache_historical_data(merged, coin, interval, suffix=cache_key)
        self.cache_historical_data(merged, coin, interval, suffix="historical")
        return merged

    def fetch_mtf_data(
        self,
        coin: str = "BTC",
        htf_interval: str = "1h",
        ltf_interval: str = "15m",
        target_ltf_candles: int = 3000,
        use_cache: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Récupère simultanément les données LTF et HTF synchronisées sur la même période temporelle.
        """
        ltf_df = self.fetch_large_historical_data(
            coin=coin,
            interval=ltf_interval,
            target_candles=target_ltf_candles,
            use_cache=use_cache
        )
        if ltf_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        start_time_ms = int(ltf_df['timestamp'].iloc[0])
        end_time_ms = int(ltf_df['timestamp'].iloc[-1])

        htf_mins = 60 if htf_interval == "1h" else 240
        duration_ms = end_time_ms - start_time_ms
        needed_htf_candles = int(duration_ms / (htf_mins * 60 * 1000)) + 120

        htf_df = self.fetch_large_historical_data(
            coin=coin,
            interval=htf_interval,
            target_candles=needed_htf_candles,
            use_cache=use_cache
        )

        return htf_df, ltf_df


