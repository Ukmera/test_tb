from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd

from config.smc_params import (
    ATR_PERIOD,
    MIN_FVG_ATR_MULT,
    MIN_SWEEP_ATR_MULT,
    STOP_BUFFER_ATR_MULT,
    SWING_WINDOW,
    SWEEP_TO_SETUP_MAX_BARS,
    OTE_FIB_MIN,
    OTE_FIB_SWEET_SPOT,
    OTE_FIB_MAX,
    OB_VOLUME_MULTIPLIER,
    MAX_OB_AGE_BARS
)


class TrendDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StructureType(Enum):
    BOS = "BOS"      # Break of Structure (Continuation)
    CHOCH = "CHOCH"  # Change of Character (Reversal)


@dataclass
class SwingPoint:
    index: int
    timestamp: int
    price: float
    is_high: bool    # True = Swing High, False = Swing Low


@dataclass
class FairValueGap:
    index: int
    timestamp: int
    top: float
    bottom: float
    is_bullish: bool
    size: float
    atr_ratio: float
    mitigated: bool = False
    mitigated_at_index: Optional[int] = None

    @property
    def consequent_encroachment(self) -> float:
        """50% midpoint du FVG."""
        return (self.top + self.bottom) / 2.0


@dataclass
class OrderBlock:
    index: int
    timestamp: int
    top: float
    bottom: float
    is_bullish: bool
    volume: float
    associated_fvg: Optional[FairValueGap] = None
    has_bos: bool = False
    mitigated: bool = False
    mitigated_at_index: Optional[int] = None

    @property
    def entry_price(self) -> float:
        return self.top if self.is_bullish else self.bottom

    @property
    def mean_threshold(self) -> float:
        """50% midpoint de l'Order Block."""
        return (self.top + self.bottom) / 2.0

    @property
    def stop_loss(self) -> float:
        return self.bottom if self.is_bullish else self.top


@dataclass
class LiquiditySweep:
    index: int
    timestamp: int
    level: float
    wick_extreme: float
    sweep_distance: float
    is_high: bool   # True = Buy-side sweep (Short), False = Sell-side sweep (Long)
    reclaimed: bool = True


@dataclass
class OTEZone:
    is_bullish: bool
    swing_low: float
    swing_high: float
    fib_618: float
    fib_705: float
    fib_790: float

    def contains_price(self, price: float) -> bool:
        if self.is_bullish:
            return self.fib_790 <= price <= self.fib_618
        else:
            return self.fib_618 <= price <= self.fib_790


@dataclass
class SMCSetupCandidate:
    grade: str                   # "5_STAR_OB", "5_STAR_SWEEP_OB", "4_STAR_FVG"
    is_long: bool
    entry_price: float
    stop_loss: float
    take_profit_1r: float        # Tier 1 (+1.5R)
    take_profit_2r: float        # Tier 2 (+3.0R)
    take_profit_runner: float = 0.0  # Tier 3 (Runner indicatif)
    order_block: Optional[OrderBlock] = None
    fvg: Optional[FairValueGap] = None
    sweep: Optional[LiquiditySweep] = None
    ote_zone: Optional[OTEZone] = None
    has_prior_sweep: bool = False


@dataclass
class SMCAnalysisResult:
    trend: TrendDirection
    swings: List[SwingPoint] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvgs: List[FairValueGap] = field(default_factory=list)
    sweeps: List[LiquiditySweep] = field(default_factory=list)
    structures: List[Dict[str, Any]] = field(default_factory=list)
    active_ote: Optional[OTEZone] = None
    setups: List[SMCSetupCandidate] = field(default_factory=list)
    current_atr: float = 0.0
    range_info: Dict[str, Any] = field(default_factory=dict)
    trendlines: List[Dict[str, Any]] = field(default_factory=list)
    htf_trend: Optional[TrendDirection] = None
    htf_pois: List[Dict[str, Any]] = field(default_factory=list)
    is_choppy: bool = False



class SMCEngine:
    def __init__(
        self,
        swing_window: int = SWING_WINDOW,
        atr_period: int = ATR_PERIOD,
        min_fvg_atr_mult: float = MIN_FVG_ATR_MULT,
        min_sweep_atr_mult: float = MIN_SWEEP_ATR_MULT,
        stop_buffer_atr_mult: float = STOP_BUFFER_ATR_MULT,
        ob_volume_multiplier: float = OB_VOLUME_MULTIPLIER,
        min_fvg_size_pct: Optional[float] = None
    ):
        self.swing_window = swing_window
        self.atr_period = atr_period
        self.min_fvg_atr_mult = min_fvg_atr_mult
        self.min_sweep_atr_mult = min_sweep_atr_mult
        self.stop_buffer_atr_mult = stop_buffer_atr_mult
        self.ob_volume_multiplier = ob_volume_multiplier
        self.min_fvg_size_pct = min_fvg_size_pct

    def calculate_rsi(self, closes: pd.Series, period: int = 14) -> pd.Series:
        """Calcule le RSI de Wilder."""
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.bfill().fillna(50.0)

    def calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """Calcule l'Average True Range (Wilder ATR) sur 14 périodes."""
        if len(df) < 2:
            return pd.Series(0.0, index=df.index)

        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / self.atr_period, min_periods=self.atr_period).mean()
        return atr.bfill().fillna(0.0)

    def find_swing_points(self, df: pd.DataFrame) -> List[SwingPoint]:
        """Identifie les swings majeurs (fractales sur fenêtre de 5 barres)."""
        swings: List[SwingPoint] = []
        w = self.swing_window
        n = len(df)
        if n < 2 * w + 1:
            return swings

        highs = df['high'].values
        lows = df['low'].values
        times = df['timestamp'].values if 'timestamp' in df.columns else df.index.values

        for i in range(w, n - w):
            current_high = highs[i]
            current_low = lows[i]

            # Swing High
            if all(current_high > highs[i - j] for j in range(1, w + 1)) and \
               all(current_high >= highs[i + j] for j in range(1, w + 1)):
                swings.append(SwingPoint(
                    index=i,
                    timestamp=int(times[i]),
                    price=float(current_high),
                    is_high=True
                ))

            # Swing Low
            if all(current_low < lows[i - j] for j in range(1, w + 1)) and \
               all(current_low <= lows[i + j] for j in range(1, w + 1)):
                swings.append(SwingPoint(
                    index=i,
                    timestamp=int(times[i]),
                    price=float(current_low),
                    is_high=False
                ))

        return swings

    def calculate_ote_zone(self, swings: List[SwingPoint]) -> Optional[OTEZone]:
        """
        Calcule la zone Fibonacci OTE (61.8% à 79.0%) sur le swing le plus récent.
        """
        if len(swings) < 2:
            return None

        last_swing = swings[-1]
        prev_swing = swings[-2]

        # Mouvement haussier récent : du Swing Low vers le Swing High
        if not prev_swing.is_high and last_swing.is_high:
            low = prev_swing.price
            high = last_swing.price
            diff = high - low
            if diff <= 0:
                return None
            return OTEZone(
                is_bullish=True,
                swing_low=low,
                swing_high=high,
                fib_618=high - (diff * OTE_FIB_MIN),
                fib_705=high - (diff * OTE_FIB_SWEET_SPOT),
                fib_790=high - (diff * OTE_FIB_MAX)
            )

        # Mouvement baissier récent : du Swing High vers le Swing Low
        elif prev_swing.is_high and not last_swing.is_high:
            high = prev_swing.price
            low = last_swing.price
            diff = high - low
            if diff <= 0:
                return None
            return OTEZone(
                is_bullish=False,
                swing_low=low,
                swing_high=high,
                fib_618=low + (diff * OTE_FIB_MIN),
                fib_705=low + (diff * OTE_FIB_SWEET_SPOT),
                fib_790=low + (diff * OTE_FIB_MAX)
            )

        return None

    def detect_fvg(self, df: pd.DataFrame, atr_series: pd.Series) -> List[FairValueGap]:
        """
        Détecte les Fair Value Gaps selon la règle exacte à 3 bougies du Pine Script :
        - Bougie 1 baissière (pour bull), bougie 2 haussière (impulsion), gap low[0] > high[2].
        - Taille minimale >= 0.25 * ATR(14).
        """
        fvgs: List[FairValueGap] = []
        n = len(df)
        if n < 3:
            return fvgs

        opens = df['open'].values
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        times = df['timestamp'].values if 'timestamp' in df.columns else df.index.values
        atrs = atr_series.values

        for i in range(2, n):
            c1_open, c1_close, c1_high, c1_low = opens[i - 2], closes[i - 2], highs[i - 2], lows[i - 2]
            c2_open, c2_close = opens[i - 1], closes[i - 1]
            c3_high, c3_low = highs[i], lows[i]
            current_atr = atrs[i] if atrs[i] > 0 else 1.0

            # ─── Bullish FVG ───
            # Bougie 1 rouge (c1_close < c1_open), Bougie 2 verte d'impulsion (c2_close > c2_open)
            is_bull_pattern = (c1_close < c1_open) and (c2_close > c2_open)
            if is_bull_pattern and (c3_low > c1_high):
                gap_size = c3_low - c1_high
                atr_ratio = gap_size / current_atr
                if atr_ratio >= self.min_fvg_atr_mult:
                    fvg = FairValueGap(
                        index=i - 1,
                        timestamp=int(times[i - 1]),
                        top=float(c3_low),
                        bottom=float(c1_high),
                        is_bullish=True,
                        size=gap_size,
                        atr_ratio=round(atr_ratio, 2)
                    )
                    # Vérifier mitigation par les bougies suivantes (1ère touche)
                    for j in range(i + 1, n):
                        if lows[j] <= fvg.bottom:
                            fvg.mitigated = True
                            fvg.mitigated_at_index = j
                            break
                    fvgs.append(fvg)

            # ─── Bearish FVG ───
            # Bougie 1 verte (c1_close > c1_open), Bougie 2 rouge d'impulsion (c2_close < c2_open)
            is_bear_pattern = (c1_close > c1_open) and (c2_close < c2_open)
            if is_bear_pattern and (c3_high < c1_low):
                gap_size = c1_low - c3_high
                atr_ratio = gap_size / current_atr
                if atr_ratio >= self.min_fvg_atr_mult:
                    fvg = FairValueGap(
                        index=i - 1,
                        timestamp=int(times[i - 1]),
                        top=float(c1_low),
                        bottom=float(c3_high),
                        is_bullish=False,
                        size=gap_size,
                        atr_ratio=round(atr_ratio, 2)
                    )
                    for j in range(i + 1, n):
                        if highs[j] >= fvg.top:
                            fvg.mitigated = True
                            fvg.mitigated_at_index = j
                            break
                    fvgs.append(fvg)

        return fvgs

    def detect_order_blocks(
        self,
        df: pd.DataFrame,
        fvgs: List[FairValueGap]
    ) -> List[OrderBlock]:
        """
        Détecte les Order Blocks créés par la bougie 1 qui a généré un FVG valide (Pine Script v6).
        Zone délimitée par la mèche haute et la mèche basse de la bougie 1.
        """
        obs: List[OrderBlock] = []
        n = len(df)
        if n < 5:
            return obs

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        volumes = df['volume'].values if 'volume' in df.columns else np.ones(n)
        times = df['timestamp'].values if 'timestamp' in df.columns else df.index.values

        for fvg in fvgs:
            # L'OB est la bougie 1 qui se trouve à l'index fvg.index - 1
            ob_idx = fvg.index - 1
            if ob_idx < 0:
                continue

            ob = OrderBlock(
                index=ob_idx,
                timestamp=int(times[ob_idx]),
                top=float(highs[ob_idx]),
                bottom=float(lows[ob_idx]),
                is_bullish=fvg.is_bullish,
                volume=float(volumes[ob_idx]),
                associated_fvg=fvg
            )

            # Invalidation/mitigation institutionnelle : l'OB est invalidé si une clôture
            # de bougie franchit son Mean Threshold (50% midpoint). Les mèches de retest sont acceptées.
            for j in range(fvg.index + 2, n):
                if ob.is_bullish and closes[j] < ob.mean_threshold:
                    ob.mitigated = True
                    ob.mitigated_at_index = j
                    break
                elif not ob.is_bullish and closes[j] > ob.mean_threshold:
                    ob.mitigated = True
                    ob.mitigated_at_index = j
                    break

            obs.append(ob)

        return obs

    def detect_liquidity_sweeps(
        self,
        df: pd.DataFrame,
        swings: List[SwingPoint],
        atr_series: pd.Series
    ) -> List[LiquiditySweep]:
        """
        Détecte les prises de liquidité avec pénétration minimale >= 0.05 * ATR(14)
        et réintégration immédiate par clôture de bougie.
        """
        sweeps: List[LiquiditySweep] = []
        if not swings:
            return sweeps

        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        times = df['timestamp'].values if 'timestamp' in df.columns else df.index.values
        atrs = atr_series.values
        n = len(df)

        for swing in swings:
            # On cherche les sweeps dans les barres suivant le swing
            for i in range(swing.index + 1, min(swing.index + 50, n)):
                current_atr = atrs[i] if atrs[i] > 0 else 1.0
                min_sweep_dist = self.min_sweep_atr_mult * current_atr

                if swing.is_high:
                    # Buy-side sweep : mèche dépasse le swing high d'au moins min_sweep_dist mais clôture en-dessous
                    penetration = highs[i] - swing.price
                    if penetration >= min_sweep_dist and closes[i] <= swing.price:
                        sweeps.append(LiquiditySweep(
                            index=i,
                            timestamp=int(times[i]),
                            level=swing.price,
                            wick_extreme=float(highs[i]),
                            sweep_distance=penetration,
                            is_high=True,
                            reclaimed=True
                        ))
                        break
                else:
                    # Sell-side sweep : mèche passe sous le swing low mais clôture au-dessus
                    penetration = swing.price - lows[i]
                    if penetration >= min_sweep_dist and closes[i] >= swing.price:
                        sweeps.append(LiquiditySweep(
                            index=i,
                            timestamp=int(times[i]),
                            level=swing.price,
                            wick_extreme=float(lows[i]),
                            sweep_distance=penetration,
                            is_high=False,
                            reclaimed=True
                        ))
                        break

        return sweeps

    def detect_market_structure(
        self,
        swings: List[SwingPoint]
    ) -> Tuple[TrendDirection, List[Dict[str, Any]]]:
        """Détermine la structure de marché (BOS / CHoCH) et la tendance."""
        if len(swings) < 4:
            return TrendDirection.NEUTRAL, []

        structures: List[Dict[str, Any]] = []
        current_trend = TrendDirection.NEUTRAL
        last_high: Optional[SwingPoint] = None
        last_low: Optional[SwingPoint] = None

        for s in swings:
            if s.is_high:
                if last_high is not None:
                    if s.price > last_high.price:
                        stype = StructureType.BOS if current_trend == TrendDirection.BULLISH else StructureType.CHOCH
                        current_trend = TrendDirection.BULLISH
                        structures.append({
                            "type": stype.value,
                            "direction": "BULLISH",
                            "index": s.index,
                            "timestamp": s.timestamp,
                            "level": last_high.price
                        })
                last_high = s
            else:
                if last_low is not None:
                    if s.price < last_low.price:
                        stype = StructureType.BOS if current_trend == TrendDirection.BEARISH else StructureType.CHOCH
                        current_trend = TrendDirection.BEARISH
                        structures.append({
                            "type": stype.value,
                            "direction": "BEARISH",
                            "index": s.index,
                            "timestamp": s.timestamp,
                            "level": last_low.price
                        })
                last_low = s

        return current_trend, structures

    def generate_setups(
        self,
        trend: TrendDirection,
        obs: List[OrderBlock],
        fvgs: List[FairValueGap],
        sweeps: List[LiquiditySweep],
        ote: Optional[OTEZone],
        current_atr: float,
        n_bars: int = -1
    ) -> List[SMCSetupCandidate]:
        """
        Génère les setups institutionnels à haute espérance mathématique :
        - Anti-Fee Drag : Distance de Stop Loss minimale (>= 0.20% du cours ou 0.40 * ATR).
        - Confluence 'Sweep First' : Détecte si la liquidité a été balayée avant l'entrée (Turtle Soup).
        - Configuration 3 Paliers : Tier 1 (+1.5R), Tier 2 (+3.0R), Tier 3 (Runner indicatif +5.0R).
        """
        setups: List[SMCSetupCandidate] = []
        stop_buffer = self.stop_buffer_atr_mult * current_atr

        # Vérifier si des balayages de liquidité récents ont eu lieu
        has_ssl_sweep = False  # Sell-side sweep (favorable pour Long)
        has_bsl_sweep = False  # Buy-side sweep (favorable pour Short)
        last_ssl_sweep: Optional[LiquiditySweep] = None
        last_bsl_sweep: Optional[LiquiditySweep] = None

        if sweeps:
            recent_sweeps = [s for s in sweeps if (n_bars <= 0 or (n_bars - s.index <= 35))]
            for s in recent_sweeps:
                if not s.is_high and not has_ssl_sweep:
                    has_ssl_sweep = True
                    last_ssl_sweep = s
                elif s.is_high and not has_bsl_sweep:
                    has_bsl_sweep = True
                    last_bsl_sweep = s

        # ─── Setups Order Blocks (5 Étoiles) ───
        for ob in reversed(obs):
            if ob.mitigated and (n_bars > 0 and ob.mitigated_at_index != n_bars - 1):
                continue
            if n_bars > 0 and (n_bars - 1 - ob.index > 120):
                continue

            if ob.is_bullish and trend == TrendDirection.BULLISH:
                in_ote = ote.contains_price(ob.top) if ote else True
                if in_ote:
                    entry = ob.top
                    sl = ob.bottom - stop_buffer
                    risk_dist = entry - sl

                    # Filtre Anti-Fee Drag : Stop Loss minimum viable
                    min_risk_dist = max(entry * 0.0020, 0.40 * current_atr)
                    if risk_dist < min_risk_dist:
                        sl = entry - min_risk_dist
                        risk_dist = min_risk_dist

                    if risk_dist > 0:
                        has_sweep = has_ssl_sweep
                        grade = "5_STAR_SWEEP_OB" if has_sweep else "5_STAR_OB"
                        setups.append(SMCSetupCandidate(
                            grade=grade,
                            is_long=True,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1r=entry + (risk_dist * 1.0),
                            take_profit_2r=entry + (risk_dist * 3.0),
                            take_profit_runner=entry + (risk_dist * 5.0),
                            order_block=ob,
                            sweep=last_ssl_sweep,
                            ote_zone=ote,
                            has_prior_sweep=has_sweep
                        ))
                        break

            elif not ob.is_bullish and trend == TrendDirection.BEARISH:
                in_ote = ote.contains_price(ob.bottom) if ote else True
                if in_ote:
                    entry = ob.bottom
                    sl = ob.top + stop_buffer
                    risk_dist = sl - entry

                    min_risk_dist = max(entry * 0.0020, 0.40 * current_atr)
                    if risk_dist < min_risk_dist:
                        sl = entry + min_risk_dist
                        risk_dist = min_risk_dist

                    if risk_dist > 0:
                        has_sweep = has_bsl_sweep
                        grade = "5_STAR_SWEEP_OB" if has_sweep else "5_STAR_OB"
                        setups.append(SMCSetupCandidate(
                            grade=grade,
                            is_long=False,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1r=entry - (risk_dist * 1.0),
                            take_profit_2r=entry - (risk_dist * 3.0),
                            take_profit_runner=entry - (risk_dist * 5.0),
                            order_block=ob,
                            sweep=last_bsl_sweep,
                            ote_zone=ote,
                            has_prior_sweep=has_sweep
                        ))
                        break

        # ─── Setups Fair Value Gaps (4 Étoiles) ───
        for fvg in reversed(fvgs):
            if fvg.mitigated and (n_bars > 0 and fvg.mitigated_at_index != n_bars - 1):
                continue
            if n_bars > 0 and (n_bars - 1 - fvg.index > 120):
                continue

            if fvg.is_bullish and trend == TrendDirection.BULLISH:
                in_ote = ote.contains_price(fvg.bottom) if ote else True
                if in_ote:
                    entry = fvg.consequent_encroachment
                    sl = fvg.bottom - stop_buffer
                    risk_dist = entry - sl

                    min_risk_dist = max(entry * 0.0020, 0.40 * current_atr)
                    if risk_dist < min_risk_dist:
                        sl = entry - min_risk_dist
                        risk_dist = min_risk_dist

                    if risk_dist > 0:
                        has_sweep = has_ssl_sweep
                        grade = "5_STAR_SWEEP_FVG" if has_sweep else "4_STAR_FVG"
                        setups.append(SMCSetupCandidate(
                            grade=grade,
                            is_long=True,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1r=entry + (risk_dist * 1.0),
                            take_profit_2r=entry + (risk_dist * 3.0),
                            take_profit_runner=entry + (risk_dist * 5.0),
                            fvg=fvg,
                            sweep=last_ssl_sweep,
                            ote_zone=ote,
                            has_prior_sweep=has_sweep
                        ))
                        break

            elif not fvg.is_bullish and trend == TrendDirection.BEARISH:
                in_ote = ote.contains_price(fvg.top) if ote else True
                if in_ote:
                    entry = fvg.consequent_encroachment
                    sl = fvg.top + stop_buffer
                    risk_dist = sl - entry

                    min_risk_dist = max(entry * 0.0020, 0.40 * current_atr)
                    if risk_dist < min_risk_dist:
                        sl = entry + min_risk_dist
                        risk_dist = min_risk_dist

                    if risk_dist > 0:
                        has_sweep = has_bsl_sweep
                        grade = "5_STAR_SWEEP_FVG" if has_sweep else "4_STAR_FVG"
                        setups.append(SMCSetupCandidate(
                            grade=grade,
                            is_long=False,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1r=entry - (risk_dist * 1.0),
                            take_profit_2r=entry - (risk_dist * 3.0),
                            take_profit_runner=entry - (risk_dist * 5.0),
                            fvg=fvg,
                            sweep=last_bsl_sweep,
                            ote_zone=ote,
                            has_prior_sweep=has_sweep
                        ))
                        break

        # Prioriser les setups ayant bénéficié d'un Liquidity Sweep préalable
        setups.sort(key=lambda s: (1 if s.has_prior_sweep else 0, 1 if "OB" in s.grade else 0), reverse=True)
        return setups

    def calculate_range(self, df: pd.DataFrame, swings: List[SwingPoint], current_atr: float = 0.0) -> Dict[str, Any]:
        """Calcule la zone de consolidation / range récente (Premium, Discount, Equilibrium 50%) et détecte la compression."""
        if len(df) < 10:
            return {}
        if swings and len(swings) >= 2:
            recent_swings = swings[-6:]
            range_high = max(s.price for s in recent_swings)
            range_low = min(s.price for s in recent_swings)
        else:
            window = df.tail(min(50, len(df)))
            range_high = float(window['high'].max())
            range_low = float(window['low'].min())

        eq = (range_high + range_low) / 2.0
        range_height = range_high - range_low
        is_choppy = bool(range_height < 1.2 * current_atr) if current_atr > 0 else False
        return {
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "range_height": round(range_height, 2),
            "equilibrium": round(eq, 2),
            "premium_min": round(eq, 2),
            "premium_max": round(range_high, 2),
            "discount_min": round(range_low, 2),
            "discount_max": round(eq, 2),
            "is_choppy": is_choppy
        }

    def calculate_trendlines(self, swings: List[SwingPoint]) -> List[Dict[str, Any]]:
        """Génère les segments reliant les swings consécutifs pour visualiser la dynamique de structure."""
        lines = []
        if len(swings) < 2:
            return lines
        recent = swings[-10:]
        for idx in range(len(recent) - 1):
            s1 = recent[idx]
            s2 = recent[idx + 1]
            lines.append({
                "from_time": int(s1.timestamp) // 1000,
                "from_price": s1.price,
                "to_time": int(s2.timestamp) // 1000,
                "to_price": s2.price,
                "is_from_high": s1.is_high,
                "is_to_high": s2.is_high
            })
        return lines

    def analyze(self, df: pd.DataFrame) -> SMCAnalysisResult:
        """Exécute l'analyse SMC complète avec filtres ATR, OTE, OBs, FVGs, Range et Trendlines."""
        if len(df) < self.swing_window * 2 + 1:
            return SMCAnalysisResult(trend=TrendDirection.NEUTRAL)

        atr_series = self.calculate_atr(df)
        current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0

        swings = self.find_swing_points(df)
        trend, structures = self.detect_market_structure(swings)
        ote = self.calculate_ote_zone(swings)
        fvgs = self.detect_fvg(df, atr_series)
        obs = self.detect_order_blocks(df, fvgs)
        sweeps = self.detect_liquidity_sweeps(df, swings, atr_series)
        range_info = self.calculate_range(df, swings, current_atr=current_atr)
        is_choppy = range_info.get("is_choppy", False)
        trendlines = self.calculate_trendlines(swings)

        setups = self.generate_setups(trend, obs, fvgs, sweeps, ote, current_atr, n_bars=len(df))
        if is_choppy:
            setups = [s for s in setups if s.has_prior_sweep]

        return SMCAnalysisResult(
            trend=trend,
            swings=swings,
            order_blocks=obs,
            fvgs=fvgs,
            sweeps=sweeps,
            structures=structures,
            active_ote=ote,
            setups=setups,
            current_atr=current_atr,
            range_info=range_info,
            trendlines=trendlines,
            is_choppy=is_choppy
        )

    def analyze_mtf(
        self,
        htf_df: Optional[pd.DataFrame],
        ltf_df: pd.DataFrame
    ) -> SMCAnalysisResult:
        """
        Analyse Multi-Timeframe institutionnelle (HTF 1H Macro Bias + LTF 15m/5m/3m Trigger).
        - Détermine la tendance macro HTF et extrait les POIs majeurs (OBs et FVGs HTF).
        - Exécute l'analyse microstructurelle sur LTF (Swings, FVGs, OBs, OTE).
        - Filtre impérativement les signaux d'entrée pour ne retenir que ceux alignés
          avec la tendance macro HTF ou rebondissant sur un POI HTF.
        """
        if ltf_df is None or len(ltf_df) < self.swing_window * 2 + 1:
            return SMCAnalysisResult(trend=TrendDirection.NEUTRAL)

        # Si HTF non disponible ou trop court, repli sur l'analyse LTF mono-timeframe
        if htf_df is None or len(htf_df) < 15:
            return self.analyze(ltf_df)

        # 1. Analyse Macro HTF
        htf_atr_series = self.calculate_atr(htf_df)
        htf_swings = self.find_swing_points(htf_df)
        htf_struct_trend, _ = self.detect_market_structure(htf_swings)

        # Biais HTF : Priorité à la structure de marché (BOS/CHoCH HTF), complétée par l'EMA 100/50
        last_htf_close = float(htf_df['close'].iloc[-1])
        ema_period = min(100, len(htf_df))
        htf_ema = float(htf_df['close'].ewm(span=ema_period, adjust=False).mean().iloc[-1])

        if htf_struct_trend != TrendDirection.NEUTRAL:
            htf_trend = htf_struct_trend
        else:
            htf_trend = TrendDirection.BULLISH if last_htf_close >= htf_ema else TrendDirection.BEARISH

        # Détection des POIs HTF (Zones institutionnelles d'intérêt majeur)
        htf_fvgs = self.detect_fvg(htf_df, htf_atr_series)
        htf_obs = self.detect_order_blocks(htf_df, htf_fvgs)
        htf_pois = []
        for ob in htf_obs[-5:]:
            if not ob.mitigated:
                htf_pois.append({
                    "type": "HTF_OB",
                    "is_bullish": ob.is_bullish,
                    "top": ob.top,
                    "bottom": ob.bottom,
                    "mean_threshold": ob.mean_threshold
                })
        for f in htf_fvgs[-5:]:
            if not f.mitigated:
                htf_pois.append({
                    "type": "HTF_FVG",
                    "is_bullish": f.is_bullish,
                    "top": f.top,
                    "bottom": f.bottom,
                    "consequent_encroachment": f.consequent_encroachment
                })

        # 2. Analyse Microstructurelle LTF
        ltf_atr_series = self.calculate_atr(ltf_df)
        current_atr = float(ltf_atr_series.iloc[-1]) if not ltf_atr_series.empty else 0.0
        ltf_swings = self.find_swing_points(ltf_df)
        ltf_trend, ltf_structures = self.detect_market_structure(ltf_swings)
        ltf_ote = self.calculate_ote_zone(ltf_swings)
        ltf_fvgs = self.detect_fvg(ltf_df, ltf_atr_series)
        ltf_obs = self.detect_order_blocks(ltf_df, ltf_fvgs)
        ltf_sweeps = self.detect_liquidity_sweeps(ltf_df, ltf_swings, ltf_atr_series)
        range_info = self.calculate_range(ltf_df, ltf_swings, current_atr=current_atr)
        is_choppy = range_info.get("is_choppy", False)
        trendlines = self.calculate_trendlines(ltf_swings)

        # 3. Génération des setups LTF strictement filtrés par le biais macro HTF
        setups = self.generate_setups(
            trend=htf_trend,
            obs=ltf_obs,
            fvgs=ltf_fvgs,
            sweeps=ltf_sweeps,
            ote=ltf_ote,
            current_atr=current_atr,
            n_bars=len(ltf_df)
        )
        if is_choppy:
            setups = [s for s in setups if s.has_prior_sweep]

        return SMCAnalysisResult(
            trend=htf_trend,
            swings=ltf_swings,
            order_blocks=ltf_obs,
            fvgs=ltf_fvgs,
            sweeps=ltf_sweeps,
            structures=ltf_structures,
            active_ote=ltf_ote,
            setups=setups,
            current_atr=current_atr,
            range_info=range_info,
            trendlines=trendlines,
            htf_trend=htf_trend,
            htf_pois=htf_pois,
            is_choppy=is_choppy
        )


