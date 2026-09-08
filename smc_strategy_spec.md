# Spécification Stratégique SMC (Smart Money Concepts) & Scalping

Ce document sert de cahier des charges pour paramétrer et programmer vos règles d'entrée personnalisées dans le bot de trading.
Vous pouvez soit le remplir directement, soit utiliser le prompt d'interview fourni pour échanger avec une IA qui le complètera pour vous.

---

## 1. Définition et Détection des Order Blocks (OB)

- **1.1. Nature de la bougie d'OB :**
  - [ ] La toute dernière bougie opposée avant l'impulsion (ex: dernière bougie rouge avant mouvement haussier)
  - [ ] Tout le bloc de consolidation précédant la rupture
  - [ ] Autre précision : 

- **1.2. Prise en compte de la zone de l'OB :**
  - [ ] Tout le range de la bougie (Wick High à Wick Low)
  - [ ] Uniquement le corps de la bougie (Open à Close)
  - [ ] Le 50% de la bougie (*Mean Threshold*)

- **1.3. Validation institutionnelle :**
  - Pour être validé, l'OB doit-il obligatoirement :
    - Casser une structure (**BOS** ou **CHoCH**) ? Oui / Non
    - Créer un **Fair Value Gap (FVG)** juste après ? Oui / Non
    - Avoir un volume supérieur à la moyenne ? Oui / Non (si oui, combien de fois la moyenne ?)

---

## 2. Fair Value Gaps (FVG) & Déséquilibres

- **2.1. Rôle du FVG dans votre entrée :**
  - [ ] L'entrée se fait directement sur le FVG
  - [ ] Le FVG sert uniquement de confirmation pour valider la puissance de l'OB
  - [ ] On entre au retest combiné OB + FVG

- **2.2. Profondeur de comblement :**
  - [ ] Dès l'entrée dans le FVG (retest du bord)
  - [ ] À 50% du FVG (*Consequent Encroachment*)
  - [ ] Comblement complet (100%)

---

## 3. Prise de Liquidité (Liquidity Sweeps)

- **3.1. Prérequis avant entrée :**
  - Faut-il obligatoirement un balayage de liquidité (*Sweep* d'un ancien High/Low ou d'un range asiatique) avant de chercher une entrée ?
  - [ ] Obligatoire (pas de sweep = pas de trade)
  - [ ] Optionnel (augmente simplement la probabilité/confiance)

- **3.2. Forme du sweep :**
  - [ ] Mèche qui dépasse le niveau mais clôture en-dessous/au-dessus (*Liquidity Grab*)
  - [ ] Cassure franche puis retour immédiat dans le range

---

## 4. Stratégie Multi-Timeframe (MTF) & Scalping

- **4.1. Répartition des unités de temps :**
  - Timeframe de tendance / zones clés (HTF) : `15m` ou `1h` ?
  - Timeframe d'entrée / scalping (LTF) : `1m` ou `5m` ?

- **4.2. Séquence exacte d'un déclenchement d'entrée :**
  *(Décrivez ici l'enchaînement idéal étape par étape)*
  *Exemple classique :*
  1. Le prix arrive dans un OB / FVG sur le 15m.
  2. Sur le 1m, on attend un sweep de liquidité suivi d'un CHoCH (changement de caractère).
  3. On place un ordre limite sur le retest de l'OB/FVG 1m créé par ce CHoCH.

---

## 5. Confluences & Filtres de Confirmation

- **5.1. Divergences RSI / MACD :**
  - [ ] Obligatoire au moment du sweep / de l'entrée
  - [ ] Utilisé comme bonus de confirmation
  - [ ] Inutile

- **5.2. Heures de trading (Sessions / Killzones) :**
  - [ ] 24h/24 sans distinction
  - [ ] Uniquement pendant les sessions actives (Londres : 09h-12h UTC / New York : 13h-17h UTC)
  - [ ] Éviter certaines heures creuses :

---

## 6. Gestion du Trade (SL, TP, Breakeven)

- **6.1. Placement du Stop Loss :**
  - [ ] Juste derrière la mèche de l'Order Block (avec combien de pips/dollars de marge ?)
  - [ ] Derrière le dernier Swing High / Swing Low
  - [ ] Distance basée sur l'ATR (volatilité)

- **6.2. Objectif de Take Profit (TP) :**
  - [ ] Ratio fixe (ex: RR 1:2, 1:3)
  - [ ] Liquidité opposée (prochain Swing High/Low majeur)
  - [ ] Prise partielle (ex: 50% sécurisés à 1:1.5 RR, le reste laissé à courir)

- **6.3. Mise à Breakeven (BE) :**
  - [ ] Déplacer le SL au point d'entrée dès que le prix atteint 1:1 RR
  - [ ] Ne jamais toucher au SL (Soit TP, soit SL)

---

## 7. Votre Indicateur d'Order Blocks existant

*(Vous pouvez coller ici le script Pine Script, le code Python ou la logique exacte de votre indicateur pour que je l'intègre directement)*:

```pinescript
// Collez votre indicateur ici si vous le souhaitez
```
