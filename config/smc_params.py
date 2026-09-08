"""
Paramètres quantitatifs avancés de la stratégie SMC (Smart Money Concepts).
Alignés avec les spécifications institutionnelles (Gemini Spec v1, Perplexity Rules v1, Pine Script v6).
"""

# --- ATR & VOLATILITÉ ---
ATR_PERIOD = 14
MIN_FVG_ATR_MULT = 0.25        # FVG minimum size >= 0.25 * ATR(14)
MIN_SWEEP_ATR_MULT = 0.05      # Sweep minimum penetration distance >= 0.05 * ATR(14)
STOP_BUFFER_ATR_MULT = 0.10    # Stop buffer added to structural level = 0.10 * ATR(14)

# --- SWING HIGHS / LOWS (FRACTALES) ---
SWING_WINDOW = 5               # Barres de chaque côté pour confirmer un swing majeur
SWEEP_TO_SETUP_MAX_BARS = 5    # Délai maximal entre le sweep et la création du FVG (en barres)

# --- FIBONACCI OPTIMAL TRADE ENTRY (OTE) ---
OTE_FIB_MIN = 0.618            # 61.8% de retracement
OTE_FIB_SWEET_SPOT = 0.705     # 70.5% (Niveau optimal de réaction)
OTE_FIB_MAX = 0.790            # 79.0% de retracement

# --- ORDER BLOCKS (OB) ---
OB_VOLUME_MULTIPLIER = 1.2     # Volume minimal sur bougie opposée
MAX_OB_AGE_BARS = 200          # Expiration de l'OB en barres si non testé
OB_ZONE_TYPE = "full_candle"   # "full_candle" (mèche à mèche) ou "body_only"

# --- MODÈLES INDÉPENDANTS ---
MODEL_A_FAST = {
    "name": "Model A — Fast Scalping",
    "bias_tf": "1h",
    "setup_tf": "5m",
    "exec_tf": "1m",
    "cooldown_minutes": 30,
    "time_stop_bars": 20       # Sortie après 20 barres M1 si SL/TP non atteint
}

MODEL_B_STRUCTURED = {
    "name": "Model B — Structured Scalping",
    "bias_tf": "4h",
    "setup_tf": "15m",
    "exec_tf": "3m",
    "cooldown_minutes": 60,
    "time_stop_bars": 10       # Sortie après 10 barres M3 si SL/TP non atteint
}

# --- ALLOCATION DU RISQUE PARTAGÉ (1% TOTAL PAR THÈSE) ---
TOTAL_RISK_PER_THESIS = 0.01   # 1.00% max d'equity par idée de trade
RISK_ALLOCATION_FVG = 0.003    # 0.30% sur entrée FVG (Setup 4 étoiles)
RISK_ALLOCATION_OB = 0.007     # 0.70% sur entrée OB (Setup 5 étoiles)

# --- CIRCUIT BREAKERS & GESTION DU RISQUE (PALERMO GATE) ---
MAX_DAILY_LOSS_R = 2.0         # Arrêt journalier après -2R de perte nette
MAX_DAILY_PROFIT_R = 3.0       # Verrouillage des gains après +2R à +3R
MAX_CONSECUTIVE_LOSSES = 2     # Pause obligatoire après 2 pertes consécutives
MAX_SPREAD_PCT = 0.0004        # 0.04% max de spread autorisé

# --- HORAIRES & SESSIONS ---
ASIA_SESSION_RESTRICT_ENTRIES = True  # Pas de nouvelles entrées en session asiatique
MACRO_NEWS_FREEZE_MIN_BEFORE = 15     # Gel 15 min avant news rouge
MACRO_NEWS_FREEZE_MIN_AFTER = 30      # Gel 30 min après news rouge
MACRO_NEWS_FREEZE_MINUTES_BEFORE = MACRO_NEWS_FREEZE_MIN_BEFORE
MACRO_NEWS_FREEZE_MINUTES_AFTER = MACRO_NEWS_FREEZE_MIN_AFTER
