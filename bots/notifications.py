import os
import time
import requests
from typing import Dict, Any, List, Optional
from config.settings import DISCORD_WEBHOOK_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class NotificationManager:
    """
    Gestionnaire unifié d'alertes temps réel pour Telegram et Discord.
    Notifie instantanément sur smartphone les ordres, exécutions, TP, SL et bilans.
    Gère gracieusement l'absence de clé ou les coupures réseau sans bloquer le desk.
    """
    def __init__(
        self,
        discord_webhook_url: Optional[str] = None,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None
    ):
        self.discord_url = discord_webhook_url if discord_webhook_url is not None else DISCORD_WEBHOOK_URL
        self.tg_token = telegram_token if telegram_token is not None else TELEGRAM_BOT_TOKEN
        self.tg_chat_id = telegram_chat_id if telegram_chat_id is not None else TELEGRAM_CHAT_ID
        self.enabled = bool(self.discord_url or (self.tg_token and self.tg_chat_id))

    def _send_discord(self, title: str, description: str, color_hex: int = 0x2962FF, fields: Optional[List[Dict[str, str]]] = None):
        if not self.discord_url:
            return
        payload = {
            "username": "SMC Desk Sentinel",
            "avatar_url": "https://raw.githubusercontent.com/Ukmera/test_tb/main/dashboard/static/logo.png",
            "embeds": [{
                "title": title,
                "description": description,
                "color": color_hex,
                "fields": fields or [],
                "footer": {"text": f"SMC Institutional Trading Desk • {time.strftime('%H:%M:%S UTC', time.gmtime())}"}
            }]
        }
        try:
            requests.post(self.discord_url, json=payload, timeout=3)
        except Exception as e:
            print(f"[Notifications Warning] Discord webhook error: {e}")

    def _send_telegram(self, text: str):
        if not (self.tg_token and self.tg_chat_id):
            return
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": self.tg_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload, timeout=3)
        except Exception as e:
            print(f"[Notifications Warning] Telegram error: {e}")

    def notify_order_placed(self, basket_name: str, order: Dict[str, Any]):
        """Notifie le placement d'un nouvel ordre limite Maker."""
        sym = order.get("symbol", "")
        is_long = order.get("is_long", True)
        side = "BUY LONG" if is_long else "SELL SHORT"
        px = order.get("entry_price", 0.0)
        sl = order.get("stop_loss", 0.0)
        tp = order.get("take_profit", 0.0)
        risk_usd = order.get("notional_usd", 10.0) * 0.01

        title = f"⏳ NOUVEL ORDRE LIMIT [{basket_name}]"
        desc = f"**{side} {sym}** posé au carnet Hyperliquid."

        fields = [
            {"name": "Prix d'entrée", "value": f"${px}", "inline": True},
            {"name": "Stop Loss", "value": f"${sl}", "inline": True},
            {"name": "Take Profit (3R)", "value": f"${tp}", "inline": True},
            {"name": "Risque engagé", "value": f"${risk_usd:.2f} (1.0%)", "inline": True},
            {"name": "Grade Setup", "value": f"{order.get('grade', '5_STAR_OB')}", "inline": True}
        ]
        self._send_discord(title, desc, color_hex=0xFFB000, fields=fields)

        tg_msg = (
            f"⏳ <b>NOUVEL ORDRE [{basket_name}]</b>\n"
            f"<b>{side} {sym}</b> @ ${px}\n"
            f"🛑 Stop Loss: ${sl}\n"
            f"🎯 Take Profit: ${tp}\n"
            f"🛡️ Risque: ${risk_usd:.2f} (1%)\n"
            f"⭐ Grade: {order.get('grade', 'SMC')}"
        )
        self._send_telegram(tg_msg)

    def notify_position_filled(self, basket_name: str, pos: Dict[str, Any]):
        """Notifie l'exécution d'un ordre limite et l'entrée en position."""
        sym = pos.get("symbol", "")
        side = "BUY LONG" if pos.get("is_long", True) else "SELL SHORT"
        px = pos.get("entry_price", 0.0)
        sz = pos.get("size", 0.0)

        title = f"⚡ ORDRE EXÉCUTÉ (FILLED) [{basket_name}]"
        desc = f"Position ouverte sur **{side} {sz} {sym}** @ ${px}"

        fields = [
            {"name": "Prix d'entrée", "value": f"${px}", "inline": True},
            {"name": "Taille notionnelle", "value": f"${pos.get('notional_usd', 0):.2f}", "inline": True},
            {"name": "Stop Loss", "value": f"${pos.get('stop_loss', 0)}", "inline": True}
        ]
        self._send_discord(title, desc, color_hex=0x00D2FF, fields=fields)

        tg_msg = (
            f"⚡ <b>POSITION OUVERTE [{basket_name}]</b>\n"
            f"<b>{side} {sym}</b> exécuté @ ${px}\n"
            f"Taille: {sz} ({pos.get('notional_usd', 0):.1f}$)\n"
            f"SL initial: ${pos.get('stop_loss', 0)}"
        )
        self._send_telegram(tg_msg)

    def notify_breakeven_activated(self, basket_name: str, pos: Dict[str, Any]):
        """Notifie l'activation du True Breakeven (+ frais garantis)."""
        sym = pos.get("symbol", "")
        be_px = pos.get("true_be_price", pos.get("entry_price", 0.0))

        title = f"🛡️ TRUE BREAKEVEN ACTIVÉ [{basket_name}]"
        desc = f"Le Stop Loss de **{sym}** a été déplacé à ${be_px} (trade sans risque, frais couverts)."
        self._send_discord(title, desc, color_hex=0xFFD700)

        tg_msg = (
            f"🛡️ <b>TRUE BREAKEVEN ACTIVÉ [{basket_name}]</b>\n"
            f"Asset: <b>{sym}</b>\n"
            f"Le Stop Loss est désormais sécurisé à <b>${be_px}</b>\n"
            f"<i>Risque résiduel = 0.00$ (frais d'échange inclus).</i>"
        )
        self._send_telegram(tg_msg)

    def notify_trade_closed(self, basket_name: str, trade: Dict[str, Any]):
        """Notifie la clôture d'un trade avec PnL et multiple R."""
        sym = trade.get("symbol", "")
        pnl = trade.get("pnl_usd", 0.0)
        r_mult = trade.get("r_multiple", 0.0)
        reason = trade.get("exit_reason", "EXIT")
        is_win = pnl >= 0
        bal = trade.get("closed_balance", 0.0)

        emoji = "💰" if is_win else "🛑"
        title = f"{emoji} TRADE CLÔTURÉ [{basket_name}] : {'PROFIT' if is_win else 'PERTE'}"
        color = 0x00E676 if is_win else 0xFF3D71

        desc = f"Sortie **[{reason}]** sur **{sym}** : **{pnl:+.2f}$ ({r_mult:+.1f}R)**"

        fields = [
            {"name": "Résultat PnL", "value": f"{pnl:+.2f}$", "inline": True},
            {"name": "Multiple R", "value": f"{r_mult:+.1f}R", "inline": True},
            {"name": "Nouveau Solde", "value": f"${bal:.2f}", "inline": True},
            {"name": "Prix d'entrée", "value": f"${trade.get('entry_price', 0)}", "inline": True},
            {"name": "Prix de sortie", "value": f"${trade.get('exit_price', 0)}", "inline": True}
        ]
        self._send_discord(title, desc, color_hex=color, fields=fields)

        tg_msg = (
            f"{emoji} <b>TRADE CLÔTURÉ [{basket_name}]</b>\n"
            f"Asset: <b>{sym}</b> [{reason}]\n"
            f"PnL: <b>{pnl:+.2f}$ ({r_mult:+.1f}R)</b>\n"
            f"Nouveau solde: <b>${bal:.2f}</b>\n"
            f"Entrée: ${trade.get('entry_price', 0)} | Sortie: ${trade.get('exit_price', 0)}"
        )
        self._send_telegram(tg_msg)
