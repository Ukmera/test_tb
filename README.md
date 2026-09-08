# Desk de Trading Algorithmique Multi-Bots SMC (Hyperliquid)

Plateforme de trading quantitatif modulaire et autonome pour **Bitcoin (BTC)** sur le DEX perpétuel **Hyperliquid**, combinant les concepts SMC (*Smart Money Concepts*), un Risk Management institutionnel strict (1% par trade), des barrières anti-slippage/frais et un **dashboard visuel interactif avec mode Playback**.

---

## 🏛️ Architecture Multi-Bots

```
┌────────────────────────────────────────────────────────┐
│             BOT 2 : SENTINELLE MACRO                   │
│   (Surveillance FOMC/CPI, pics de volatilité anormale) │
│            └──> Active le Kill-Switch de sécurité      │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│               BOT 1 : SCANNER SMC                      │
│   (Calcul WebSockets/REST : BOS, CHoCH, OB, FVG, RSI)  │
│            └──> Détecte les zones de retest valides    │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│         BOT 3 : RISK & EXECUTION MANAGER               │
│  (Calcul strict du 1% de risque, ordres limites maker, │
│        vérification spread < 0.04% & RR >= 1:2)        │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│             BOT 4 : AUTO-CRITIQUE IA                   │
│  (Analyse post-mortem des trades, journalisation des   │
│     causes de perte : variance vs erreur technique)    │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Démarrage Rapide

### 1. Installation des dépendances
```powershell
pip install -r requirements.txt
```

### 2. Exécuter un Backtest avec données réelles Hyperliquid
Récupère les données réelles en direct du carnet Hyperliquid, simule l'exécution avec frais maker/taker, et génère le fichier de simulation pour le playback :
```powershell
python run_backtest.py
```

### 3. Lancer le Dashboard Visuel & Mode Playback
Ouvre l'interface graphique locale dans votre navigateur :
```powershell
python run_dashboard.py
```
Accédez à : **`http://127.0.0.1:8088`** (ou le port alternatif détecté automatiquement)

- **Graphique TradingView Lightweight Charts** interactif.
- **Contrôleur de Playback** : bouton Play, avance/recul pas-à-pas bougie par bougie, vitesse ajustable (1x, 2x, 5x), barre de défilement temporelle.
- **Marqueurs de trades** : Flèches d'entrée (Buy/Sell), lignes de Stop Loss et Take Profit.
- **Métriques en direct** : Prix BTC en temps réel, spread du carnet, statut du Kill-Switch.

### 4. Lancer les Tests Unitaires
```powershell
python -m pytest -v
```

---

## 🛡️ Règles de Gestion du Risque Implémentées
1. **Risque 1% par trade** : Aucune position ne peut risquer plus de 1% du capital total (1 $ sur 100 $).
2. **Plafond de levier** : Plafonné à 10x maximum pour éviter le risque de liquidation.
3. **Ordres Maker prioritaires** : Les ordres sont postés en limites sur retest d'Order Block pour bénéficier des frais réduits d'Hyperliquid.
4. **Filtre Anti-Spread** : Annulation automatique si le spread du carnet d'ordres dépasse 0.04%.
5. **Circuit Breakers** :
   - Pause automatique après 3 pertes consécutives.
   - Kill-Switch activé si la perte journalière cumulée atteint 5%.
