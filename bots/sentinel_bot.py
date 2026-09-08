import time
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any, Optional
import requests
import pandas as pd
from config.smc_params import (
    MACRO_NEWS_FREEZE_MINUTES_BEFORE,
    MACRO_NEWS_FREEZE_MINUTES_AFTER
)


class MacroSentinelBot:
    """
    Bot 2 : Sentinelle Macroéconomique & Volatilité Extrême (Agent NAIROBI)
    Surveille le calendrier macroéconomique en direct (CPI, FOMC, NFP, Décisions Taux),
    l'indice Crypto Fear & Greed et les cascades de liquidations pour protéger le capital
    contre les mèches de manipulation.
    """
    def __init__(
        self,
        freeze_before_min: int = MACRO_NEWS_FREEZE_MINUTES_BEFORE,
        freeze_after_min: int = MACRO_NEWS_FREEZE_MINUTES_AFTER
    ):
        self.freeze_before_sec = freeze_before_min * 60
        self.freeze_after_sec = freeze_after_min * 60
        self.scheduled_events: List[Dict[str, Any]] = []
        self.last_sentiment_fetch: float = 0.0
        self.cached_sentiment: Dict[str, Any] = {"score": 50, "label": "Neutral"}
        self._last_cal_sync: float = 0.0

    def sync_economic_calendar(self) -> int:
        """
        Synchronise le calendrier macroéconomique hebdomadaire (FairEconomy / ForexFactory API).
        Charge les événements 'High Impact' pour USD et EUR. Cache mémoire de 6 heures.
        """
        now = time.time()
        if self._last_cal_sync > 0 and (now - self._last_cal_sync < 21600) and self.scheduled_events:
            return len(self.scheduled_events)

        try:
            resp = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=4)
            if resp.status_code == 200:
                events = resp.json()
                new_events = []
                for item in events:
                    if item.get("impact") == "High" and item.get("country") in ["USD", "EUR"]:
                        dt_str = item.get("date")
                        if dt_str:
                            try:
                                dt = datetime.fromisoformat(dt_str)
                                ts = int(dt.timestamp())
                                new_events.append({
                                    "name": f"{item.get('title')} ({item.get('country')})",
                                    "timestamp": ts,
                                    "impact": "HIGH",
                                    "country": item.get("country")
                                })
                            except Exception:
                                continue
                if new_events:
                    self.scheduled_events = new_events
                    self._last_cal_sync = now
        except Exception as e:
            print(f"[MacroSentinel Warning] Erreur synchro calendrier économique: {e}")

        return len(self.scheduled_events)

    def fetch_live_sentiment(self) -> Dict[str, Any]:
        """Récupère l'indice Crypto Fear & Greed en direct avec cache mémoire de 15 minutes."""
        now = time.time()
        if now - self.last_sentiment_fetch < 900 and self.cached_sentiment.get("score") != 50:
            return self.cached_sentiment

        try:
            resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    self.cached_sentiment = {
                        "score": int(item["value"]),
                        "label": item["value_classification"],
                        "timestamp": int(item.get("timestamp", now))
                    }
                    self.last_sentiment_fetch = now
        except Exception:
            pass
        return self.cached_sentiment

    def add_scheduled_event(self, name: str, event_timestamp_sec: int, impact: str = "HIGH", country: str = "USD"):
        self.scheduled_events.append({
            "name": name,
            "timestamp": event_timestamp_sec,
            "impact": impact,
            "country": country
        })

    def check_macro_freeze(self, current_time_sec: int) -> Tuple[bool, str]:
        """Vérifie si le trading doit être gelé en raison d'une annonce macro majeure."""
        if not self.scheduled_events and self._last_cal_sync == 0:
            self.sync_economic_calendar()

        for event in self.scheduled_events:
            event_time = event["timestamp"]
            diff = current_time_sec - event_time

            # Période avant l'événement
            if -self.freeze_before_sec <= diff < 0:
                mins_left = abs(diff) // 60
                return False, f"Gel Macro : {event['name']} dans {mins_left} min. Entrées suspendues."

            # Période après l'événement
            if 0 <= diff <= self.freeze_after_sec:
                mins_ago = diff // 60
                return False, f"Gel Macro : {event['name']} il y a {mins_ago} min. Volatilité extrême résiduelle."

        return True, "Conditions Macro favorables"

    def get_next_high_impact_event(self) -> Optional[Dict[str, Any]]:
        """Retourne la prochaine annonce macroéconomique majeure programmée."""
        if not self.scheduled_events and self._last_cal_sync == 0:
            self.sync_economic_calendar()

        now = time.time()
        upcoming = [e for e in self.scheduled_events if e["timestamp"] > now]
        if upcoming:
            upcoming.sort(key=lambda x: x["timestamp"])
            nxt = upcoming[0]
            mins_until = int((nxt["timestamp"] - now) // 60)
            return {
                "name": nxt["name"],
                "timestamp": nxt["timestamp"],
                "mins_until": mins_until,
                "country": nxt.get("country", "USD")
            }
        return None

    def check_volatility_spike(self, df_recent: pd.DataFrame, threshold_multiplier: float = 3.5) -> Tuple[bool, str]:
        """
        Détecte si la dernière bougie présente une amplitude anormale (cascade de liquidations)
        par rapport à la moyenne récente.
        """
        if len(df_recent) < 15:
            return True, "Données insuffisantes pour le filtre de volatilité."

        ranges = df_recent['high'] - df_recent['low']
        avg_range = ranges.iloc[-15:-1].mean()
        last_range = ranges.iloc[-1]

        if avg_range > 0 and last_range > avg_range * threshold_multiplier:
            return False, f"Pic de volatilité extrême détecté ({last_range:.1f}$ vs moy {avg_range:.1f}$). Gel temporaire."

        return True, "Volatilité dans les normes"

    def is_trading_allowed(self, df_recent: pd.DataFrame) -> Tuple[bool, str]:
        now_sec = int(time.time())
        macro_ok, macro_reason = self.check_macro_freeze(now_sec)
        if not macro_ok:
            return False, macro_reason

        vol_ok, vol_reason = self.check_volatility_spike(df_recent)
        if not vol_ok:
            return False, vol_reason

        return True, "Trading autorisé par la Sentinelle"
