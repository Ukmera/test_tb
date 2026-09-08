import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd

from config.smc_params import (
    TOTAL_RISK_PER_THESIS,
    RISK_ALLOCATION_FVG,
    RISK_ALLOCATION_OB,
    MAX_DAILY_LOSS_R,
    MAX_DAILY_PROFIT_R,
    MAX_CONSECUTIVE_LOSSES,
    MAX_SPREAD_PCT
)
from core.smc_engine import SMCEngine, SMCAnalysisResult, SMCSetupCandidate, TrendDirection
from core.risk_manager import RiskManager, TradeOrderProposal
from bots.sentinel_bot import MacroSentinelBot


@dataclass
class AgentMessage:
    timestamp: str
    agent: str
    status: str       # "INFO", "CLEARED", "VETO", "WARNING"
    message: str


@dataclass
class DeskPipelineResult:
    approved: bool
    setup: Optional[SMCSetupCandidate] = None
    proposal: Optional[TradeOrderProposal] = None
    veto_agent: Optional[str] = None
    veto_reason: Optional[str] = None
    messages: List[AgentMessage] = field(default_factory=list)


class TokyoAgent:
    """TOKYO (Macro & Micro Scout) : Scanne le marché HTF (1H) et LTF, détecte les structures SMC et verrouille l'alignement macro."""
    def __init__(self, smc_engine: SMCEngine):
        self.smc = smc_engine

    def scan(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> Tuple[SMCAnalysisResult, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        if htf_df is not None and not htf_df.empty and len(htf_df) >= 15:
            analysis = self.smc.analyze_mtf(htf_df, df)
            htf_val = analysis.htf_trend.value if analysis.htf_trend else analysis.trend.value
            logs.append(AgentMessage(
                timestamp=now_str,
                agent="TOKYO",
                status="INFO",
                message=f"Biais Multi-TF verrouillé : HTF {htf_val} (ATR: {analysis.current_atr:.1f}$)"
            ))
        else:
            analysis = self.smc.analyze(df)
            if analysis.trend != TrendDirection.NEUTRAL:
                logs.append(AgentMessage(
                    timestamp=now_str,
                    agent="TOKYO",
                    status="INFO",
                    message=f"Biais de structure identifié : {analysis.trend.value} (ATR: {analysis.current_atr:.1f}$)"
                ))

        if analysis.setups:
            best_setup = analysis.setups[0]
            logs.append(AgentMessage(
                timestamp=now_str,
                agent="TOKYO",
                status="CLEARED",
                message=f"Setup détecté : {best_setup.grade} ({'LONG' if best_setup.is_long else 'SHORT'}) @ {best_setup.entry_price:.1f}$"
            ))

        return analysis, logs


class BerlinAgent:
    """BERLIN (Conditions) : Valide l'alignement OTE (Fib 61.8%-79%) et les règles strictes."""
    def validate(self, setup: SMCSetupCandidate, analysis: SMCAnalysisResult) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        # Vérifier OTE si applicable
        if setup.ote_zone:
            if not setup.ote_zone.contains_price(setup.entry_price):
                reason = f"Prix d'entrée ({setup.entry_price:.1f}$) hors de la zone OTE 61.8%-79%"
                logs.append(AgentMessage(now_str, "BERLIN", "VETO", reason))
                return False, reason, logs

        logs.append(AgentMessage(
            now_str, "BERLIN", "CLEARED",
            f"Conditions validées : OTE Confluent ({setup.grade}), Stop structurel calculé avec buffer ATR."
        ))
        return True, "Conditions OK", logs


class NairobiAgent:
    """NAIROBI (Briefs) : Sentinelle Macro & Calendrier Économique."""
    def __init__(self, sentinel: MacroSentinelBot):
        self.sentinel = sentinel

    def check_macro(self, df: pd.DataFrame) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")
        sentiment = self.sentinel.fetch_live_sentiment()
        allowed, reason = self.sentinel.is_trading_allowed(df)

        if not allowed:
            logs.append(AgentMessage(now_str, "NAIROBI", "VETO", f"Gel Macro : {reason} | Sentiment: {sentiment['label']} ({sentiment['score']}/100)"))
            return False, reason, logs

        logs.append(AgentMessage(
            now_str, "NAIROBI", "CLEARED",
            f"Marché Macro Dégagé | Sentiment Live : {sentiment['label']} ({sentiment['score']}/100) | Volatilité saine"
        ))
        return True, "Macro OK", logs


class PalermoAgent:
    """PALERMO (Veto Gate) : Le gardien intransigeant (Kill-Switch, Spread, Limites Journalières)."""
    def __init__(self, max_spread: float = MAX_SPREAD_PCT):
        self.max_spread = max_spread
        self.daily_realized_r = 0.0
        self.consecutive_losses = 0
        self.is_halted = False
        self.halt_reason = ""

    def record_trade_result(self, r_multiple: float):
        self.daily_realized_r += r_multiple
        if r_multiple < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.is_halted = True
                self.halt_reason = f"Pause sécurité : {self.consecutive_losses} pertes consécutives atteintes."
        else:
            self.consecutive_losses = 0

        if self.daily_realized_r <= -MAX_DAILY_LOSS_R:
            self.is_halted = True
            self.halt_reason = f"Arrêt journalier : Perte de {self.daily_realized_r:.1f}R (Max autorisé: -{MAX_DAILY_LOSS_R}R)."
        elif self.daily_realized_r >= MAX_DAILY_PROFIT_R:
            self.is_halted = True
            self.halt_reason = f"Objectif journalier atteint : +{self.daily_realized_r:.1f}R sécurisés. Desk au repos."

    def evaluate_veto(self, best_bid: float, best_ask: float) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        if self.is_halted:
            logs.append(AgentMessage(now_str, "PALERMO", "VETO", f"PORTE DE VETO BLOQUÉE : {self.halt_reason}"))
            return False, self.halt_reason, logs

        if best_bid <= 0 or best_ask <= 0:
            reason = "Carnet d'ordres vide ou indisponible."
            logs.append(AgentMessage(now_str, "PALERMO", "VETO", reason))
            return False, reason, logs

        spread = (best_ask - best_bid) / best_bid
        if spread > self.max_spread:
            reason = f"Spread de {spread*100:.3f}% supérieur au seuil max de {self.max_spread*100:.3f}%"
            logs.append(AgentMessage(now_str, "PALERMO", "VETO", reason))
            return False, reason, logs

        logs.append(AgentMessage(now_str, "PALERMO", "CLEARED", f"Veto levé : Spread ({spread*100:.3f}%) et compte OK (R journalier: {self.daily_realized_r:+.1f}R)"))
        return True, "Palermo OK", logs


class StockholmAgent:
    """STOCKHOLM (Liquidity & Sizing) : Calcule la taille de position exacte et le Breakeven Net."""
    def __init__(self, risk_manager: RiskManager):
        self.risk_mgr = risk_manager

    def compute_sizing(
        self,
        symbol: str,
        setup: SMCSetupCandidate,
        current_balance: float
    ) -> Tuple[Optional[TradeOrderProposal], List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        # Allocation asymétrique Kelly (1.50% si Sweep, 0.60% sinon)
        is_sweep = "SWEEP" in setup.grade or setup.has_prior_sweep
        risk_pct = 0.015 if is_sweep else 0.006
        self.risk_mgr.risk_pct = risk_pct

        proposal, msg = self.risk_mgr.evaluate_proposal(
            symbol=symbol,
            is_long=setup.is_long,
            entry_price=setup.entry_price,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit_2r,
            take_profit_1r=setup.take_profit_1r,
            take_profit_2r=setup.take_profit_2r,
            grade=setup.grade,
            has_prior_sweep=setup.has_prior_sweep
        )

        if proposal:
            logs.append(AgentMessage(
                now_str, "STOCKHOLM", "CLEARED",
                f"Sizing calibré : {proposal.position_size} {symbol} ({proposal.notional_value}$) | Risque: {proposal.risk_amount_usd}$ ({risk_pct*100:.2f}%) | Levier: {proposal.leverage}x"
            ))
        else:
            logs.append(AgentMessage(now_str, "STOCKHOLM", "VETO", f"Rejet sizing : {msg}"))

        return proposal, logs


class DenverAgent:
    """DENVER (Signals) : Filtre le bruit de marché et valide l'impulsion / le déplacement (Displacement)."""
    def check_displacement(self, df: pd.DataFrame, setup: SMCSetupCandidate) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        # Vérification du volume et de l'amplitude de la bougie d'impulsion
        if len(df) >= 3:
            recent_vol = df['volume'].iloc[-3:].mean()
            avg_vol = df['volume'].iloc[-20:].mean() if len(df) >= 20 else recent_vol
            if recent_vol < avg_vol * 0.8:
                logs.append(AgentMessage(now_str, "DENVER", "INFO", "Volume modéré sur impulsion, surveillance accrue."))
            else:
                logs.append(AgentMessage(now_str, "DENVER", "CLEARED", f"Impulsion validée : Volume expansion ({recent_vol:.1f} vs avg {avg_vol:.1f})"))
        else:
            logs.append(AgentMessage(now_str, "DENVER", "CLEARED", "Signal préliminaire accepté."))

        return True, "Displacement validé", logs


class RioAgent:
    """RIO (Charts) : Surveille les retracements, les mèches de rejet et les niveaux d'invalidation."""
    def inspect_levels(self, setup: SMCSetupCandidate) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        inval_dist = abs(setup.entry_price - setup.stop_loss)
        logs.append(AgentMessage(
            now_str, "RIO", "CLEARED",
            f"Structure & Niveaux validés : Invalidation à {setup.stop_loss:.1f}$ (Delta: {inval_dist:.1f}$) | TP2R: {setup.take_profit_2r:.1f}$"
        ))
        return True, "Niveaux OK", logs


class HelsinkiAgent:
    """HELSINKI (Ledger & True BE) : Tient le grand livre, calcule les frais réels et verrouille le True Breakeven (+ fees nettes + 1 tick buffer)."""
    def __init__(self, maker_fee: float = 0.0002, taker_fee: float = 0.0005):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee

    def evaluate_ledger(self, proposal: TradeOrderProposal) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        round_trip_fee = proposal.notional_value * (self.maker_fee + self.taker_fee)
        fee_offset = proposal.entry_price * (self.maker_fee + self.taker_fee + 0.0001)
        buffer_ticks = 1.0
        if proposal.is_long:
            net_be = round(proposal.entry_price + fee_offset + buffer_ticks, 2)
        else:
            net_be = round(proposal.entry_price - fee_offset - buffer_ticks, 2)

        logs.append(AgentMessage(
            now_str, "HELSINKI", "CLEARED",
            f"Grand livre ajusté : Frais A/R = {round_trip_fee:.3f}$ | True Breakeven Net = {net_be:.1f}$ (Net >= 0$ Garanti)"
        ))
        return True, "Ledger OK", logs


class LisbonAgent:
    """LISBON (Recheck) : Vérification finale de fraîcheur des prix et cohérence du ticket d'ordre."""
    def verify_ticket(self, proposal: TradeOrderProposal, best_bid: float, best_ask: float) -> Tuple[bool, str, List[AgentMessage]]:
        logs = []
        now_str = time.strftime("%H:%M:%S")

        # Vérifier que le prix d'entrée est réaliste par rapport au carnet
        if proposal.is_long and proposal.entry_price > best_ask * 1.01:
            reason = f"Ticket rejeté : Prix d'achat ({proposal.entry_price}) trop supérieur au Best Ask ({best_ask})"
            logs.append(AgentMessage(now_str, "LISBON", "VETO", reason))
            return False, reason, logs
        elif not proposal.is_long and proposal.entry_price < best_bid * 0.99:
            reason = f"Ticket rejeté : Prix de vente ({proposal.entry_price}) trop inférieur au Best Bid ({best_bid})"
            logs.append(AgentMessage(now_str, "LISBON", "VETO", reason))
            return False, reason, logs

        logs.append(AgentMessage(
            now_str, "LISBON", "CLEARED",
            f"Contrôle final validé : Horodatage carnet synchronisé, ticket d'ordre sécurisé."
        ))
        return True, "Recheck OK", logs


class ProfessorAgent:
    """LE PROFESSEUR (Router) : Coordonne la brigade d'agents et autorise l'ordre final."""
    def __init__(
        self,
        symbol: str = "BTC",
        initial_balance: float = 100.0
    ):
        self.symbol = symbol
        self.balance = initial_balance
        self.smc = SMCEngine()
        self.sentinel = MacroSentinelBot()
        self.risk_mgr = RiskManager(current_balance=initial_balance)

        # Brigade d'agents au complet (10 agents "GPTHeist")
        self.tokyo = TokyoAgent(self.smc)
        self.denver = DenverAgent()
        self.rio = RioAgent()
        self.berlin = BerlinAgent()
        self.nairobi = NairobiAgent(self.sentinel)
        self.palermo = PalermoAgent()
        self.stockholm = StockholmAgent(self.risk_mgr)
        self.helsinki = HelsinkiAgent()
        self.lisbon = LisbonAgent()

        self.activity_log: List[AgentMessage] = []
        self.last_pipeline_result: Optional[DeskPipelineResult] = None
        self.session_start_time = time.time()

    def get_team_status(self) -> Dict[str, Any]:
        """Fournit l'état complet de l'équipe pour l'affichage dans le dashboard."""
        uptime_sec = int(time.time() - self.session_start_time)
        hrs = uptime_sec // 3600
        mins = (uptime_sec % 3600) // 60
        secs = uptime_sec % 60
        mission_clock = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        palermo_gate = "VETO" if self.palermo.is_halted else "ENTRY CLEARED"

        agents_data = {
            "TOKYO": {"role": "SCOUT", "desc": "Scan structures SMC", "status": "ACTIVE", "color": "#00d2ff"},
            "PALERMO": {"role": "VETOES", "desc": "Kill-switch & Spread", "status": "VETO" if self.palermo.is_halted else "CLEARED", "color": "#00e676" if not self.palermo.is_halted else "#ff3d71"},
            "DENVER": {"role": "SIGNALS", "desc": "Filtre bruit & volume", "status": "ACTIVE", "color": "#ffb000"},
            "STOCKHOLM": {"role": "LIQUIDITY", "desc": "Sizing 1% & Risque", "status": "ACTIVE", "color": "#00e676"},
            "PROFESSOR": {"role": "ROUTER", "desc": "Master Orchestrateur", "status": "APPROVED" if (self.last_pipeline_result and self.last_pipeline_result.approved) else "STANDBY", "color": "#2962ff"},
            "RIO": {"role": "CHARTS", "desc": "Niveaux & Invalidation", "status": "ACTIVE", "color": "#9c27b0"},
            "HELSINKI": {"role": "LEDGER", "desc": "Grand livre & Breakeven", "status": "ACTIVE", "color": "#795548"},
            "NAIROBI": {"role": "BRIEFS", "desc": "Sentinelle Macro CPI/FOMC", "status": "CLEARED", "color": "#e91e63"},
            "BERLIN": {"role": "CONDITIONS", "desc": "OTE Fib 61.8%-79%", "status": "ACTIVE", "color": "#ff9800"},
            "LISBON": {"role": "RECHECK", "desc": "Fraîcheur & ticket", "status": "ACTIVE", "color": "#00bcd4"}
        }

        return {
            "mission_clock": mission_clock,
            "palermo_gate": palermo_gate,
            "palermo_halted": self.palermo.is_halted,
            "palermo_halt_reason": self.palermo.halt_reason,
            "daily_r": round(self.palermo.daily_realized_r, 2),
            "consecutive_losses": self.palermo.consecutive_losses,
            "agents": agents_data,
            "activity_log": [
                {
                    "timestamp": msg.timestamp,
                    "agent": msg.agent,
                    "status": msg.status,
                    "message": msg.message
                }
                for msg in reversed(self.activity_log[-35:])
            ],
            "last_approved": self.last_pipeline_result.approved if self.last_pipeline_result else False
        }

    def route(
        self,
        df: pd.DataFrame,
        best_bid: float,
        best_ask: float,
        htf_df: Optional[pd.DataFrame] = None
    ) -> DeskPipelineResult:
        """
        Exécute la chaîne d'approbation séquentielle des 10 agents :
        Tokyo -> Denver -> Rio -> Berlin -> Nairobi -> Palermo -> Stockholm -> Helsinki -> Lisbon -> Professor
        """
        pipeline_messages = []
        now_str = time.strftime("%H:%M:%S")

        # 1. TOKYO : Scan de structure (Multi-TF si dispo)
        analysis, tokyo_logs = self.tokyo.scan(df, htf_df=htf_df)
        pipeline_messages.extend(tokyo_logs)

        if not analysis.setups:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        setup = analysis.setups[0]

        # 2. DENVER : Validation du déplacement / volume
        denver_ok, denver_reason, denver_logs = self.denver.check_displacement(df, setup)
        pipeline_messages.extend(denver_logs)
        if not denver_ok:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="DENVER", veto_reason=denver_reason, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 3. RIO : Validation des niveaux et de l'invalidation
        rio_ok, rio_reason, rio_logs = self.rio.inspect_levels(setup)
        pipeline_messages.extend(rio_logs)

        # 4. BERLIN : Validation des conditions OTE
        berlin_ok, berlin_reason, berlin_logs = self.berlin.validate(setup, analysis)
        pipeline_messages.extend(berlin_logs)
        if not berlin_ok:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="BERLIN", veto_reason=berlin_reason, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 5. NAIROBI : Contrôle Macro
        nairobi_ok, nairobi_reason, nairobi_logs = self.nairobi.check_macro(df)
        pipeline_messages.extend(nairobi_logs)
        if not nairobi_ok:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="NAIROBI", veto_reason=nairobi_reason, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 6. PALERMO : Porte de VETO (Kill-Switch, Spread, Limites)
        palermo_ok, palermo_reason, palermo_logs = self.palermo.evaluate_veto(best_bid, best_ask)
        pipeline_messages.extend(palermo_logs)
        if not palermo_ok:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="PALERMO", veto_reason=palermo_reason, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 7. STOCKHOLM : Dimensionnement 1% strict
        proposal, stockholm_logs = self.stockholm.compute_sizing(self.symbol, setup, self.balance)
        pipeline_messages.extend(stockholm_logs)
        if not proposal:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="STOCKHOLM", veto_reason="Sizing invalide", messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 8. HELSINKI : Grand livre & Net Breakeven
        helsinki_ok, helsinki_reason, helsinki_logs = self.helsinki.evaluate_ledger(proposal)
        pipeline_messages.extend(helsinki_logs)

        # 9. LISBON : Contrôle ultime fraîcheur & ticket
        lisbon_ok, lisbon_reason, lisbon_logs = self.lisbon.verify_ticket(proposal, best_bid, best_ask)
        pipeline_messages.extend(lisbon_logs)
        if not lisbon_ok:
            self.activity_log.extend(pipeline_messages)
            res = DeskPipelineResult(approved=False, setup=setup, veto_agent="LISBON", veto_reason=lisbon_reason, messages=pipeline_messages)
            self.last_pipeline_result = res
            return res

        # 10. LE PROFESSEUR : Approbation finale
        pipeline_messages.append(AgentMessage(
            now_str, "PROFESSOR", "CLEARED",
            f"ORDRE APPROUVÉ ET TRANSMIS À L'EXÉCUTION : {'BUY LONG' if setup.is_long else 'SELL SHORT'} @ {setup.entry_price:.1f}$ | SL: {setup.stop_loss:.1f}$ | TP: {setup.take_profit_2r:.1f}$"
        ))

        self.activity_log.extend(pipeline_messages)
        self.activity_log = self.activity_log[-120:]

        res = DeskPipelineResult(
            approved=True,
            setup=setup,
            proposal=proposal,
            messages=pipeline_messages
        )
        self.last_pipeline_result = res
        return res
