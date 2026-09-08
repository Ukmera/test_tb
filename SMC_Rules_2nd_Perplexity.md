# BTC Hyperliquid SMC Scalping Bot — Trading Rules V1

> Status: strategy specification for implementation and backtesting.  
> Market: Bitcoin perpetuals on Hyperliquid.  
> Style: SMC / ICT-inspired multi-timeframe scalping.  
> Important: all thresholds labelled **CONFIGURABLE** are parameters to optimize through backtests and paper trading. No live deployment should occur before order, stop-loss, data, and kill-switch behavior are validated end-to-end.

---

## 1. Core Principles

1. The bot trades a confluence of:
   - market structure,
   - liquidity,
   - Order Blocks (OB),
   - Fair Value Gaps (FVG),
   - Fibonacci Optimal Trade Entry (OTE),
   - multi-timeframe confirmation.
2. The bot must not trade a single signal in isolation. A raw FVG, candle pattern, or pivot alone is not a valid entry.
3. Higher timeframes define context and danger zones. Lower timeframes define timing and execution.
4. The bot treats an FVG entry and an OB entry from the same directional thesis as one trade idea with one shared risk cap.
5. All higher-timeframe decisions must use closed candles only. Never validate a BOS, CHoCH, FVG, OB, or HTF trend on an unclosed HTF candle.

---

## 2. Timeframe Hierarchy

| Layer | Timeframes | Purpose |
|---|---|---|
| Higher-timeframe context | H4, H1 | Primary trend/bias, external structure, major liquidity, powerful OB/FVG zones that can invalidate or materially degrade lower-timeframe setups |
| Intermediate setup | M30, M15 | Intermediate structure, major swing leg for Fib/OTE, setup OB/FVG zones, range and intermediate sweep analysis |
| Trigger / confirmation | M5, M3 | Precise confirmation, local liquidity sweep, micro-structure shift, BOS/CHoCH, reversal pattern, entry decision |
| Fine execution | M1 | Entry refinement, micro-confirmation, execution and active trade management; M1 must not create an independent thesis against higher-timeframe context |

### 2.1 Trend and bias

A timeframe has a bullish bias when:

- major filtered structure is HH/HL;
- the last significant structural break is bullish BOS;
- a rising support trendline, if available, remains intact.

A timeframe has a bearish bias when:

- major filtered structure is LH/LL;
- the last significant structural break is bearish BOS;
- a falling resistance trendline, if available, remains intact.

A timeframe is neutral/range when:

- structural dominance is absent or contradictory;
- price is contained between a recognized support and resistance range boundary;
- trendline and filtered structure materially disagree.

### 2.2 Trendline confluence

Trendlines are confirmation tools, not the sole source of bias.

- Bullish trendline: connect the two most recent confirmed major filtered HLs.
- Bearish trendline: connect the two most recent confirmed major filtered LHs.
- A wick through a trendline does not invalidate it by itself.
- A confirmed close beyond the trendline, combined with coherent structural evidence, is a trend-degradation or reversal signal.
- If structure and trendline disagree, downgrade the directional bias to `NEUTRAL` unless a high-quality setup has additional confirmation.

### 2.3 Range confluence

A range is defined from repeated major filtered highs and lows within a bounded price region.

- Plot/support: lower range boundary.
- Plot/resistance: upper range boundary.
- Compute equilibrium: 50% of the range.
- Avoid initiating ordinary trades in the range midpoint/equilibrium.
- A wick beyond a range boundary followed by a close back inside is a possible liquidity sweep, not automatically a breakout.
- A breakout requires a confirmed close outside the range, then structural/displacement confirmation; a retest may further improve confidence.

### 2.4 Alignment rules

- Standard long: H4/H1 bias bullish, M30/M15 setup broadly bullish or supportive, LTF trigger bullish.
- Standard short: H4/H1 bias bearish, M30/M15 setup broadly bearish or supportive, LTF trigger bearish.
- M5/M3 may create an OB/FVG/OTE setup, but it must align with the higher-timeframe bias and must not run directly into a powerful opposing H1/H4 zone.
- Countertrend setups are allowed only when there is a confirmed liquidity sweep plus reversal confirmation on H1 or M15.
- In HTF neutral/range conditions, ordinary continuation trades are not permitted unless the full high-quality confluence stack is present.

---

## 3. Market Structure

### 3.1 Major filtered structure

The bot must use a filtered/major swing engine rather than every raw pivot.

- Bullish structure: sequence of Higher Highs (HH) and Higher Lows (HL).
- Bearish structure: sequence of Lower Highs (LH) and Lower Lows (LL).
- Raw pivots are diagnostic inputs; filtered major swings drive trend, BOS/CHoCH, OTE anchors, liquidity levels, trendlines, and range boundaries.
- Filtering must be configurable by pivot settings, minimum bar distance, minimum percentage/ATR swing magnitude, and future structure-quality conditions.

### 3.2 BOS and CHoCH

- Bullish BOS: confirmed break of a relevant prior filtered swing high in an established bullish context.
- Bearish BOS: confirmed break of a relevant prior filtered swing low in an established bearish context.
- Bullish CHoCH: meaningful upside break against prior bearish structure.
- Bearish CHoCH: meaningful downside break against prior bullish structure.
- A BOS/CHoCH must be based on confirmed structure, not on a minor raw pivot.
- The exact close-versus-wick rule is **CONFIGURABLE** and must be backtested. Preferred V1: structural confirmation by candle close beyond the relevant level.

---

## 4. Order Blocks

### 4.1 Bullish Order Block

A bullish OB is the last bearish candle before a bullish displacement that simultaneously:

1. creates a bullish BOS; and
2. creates a bullish FVG / imbalance.

The full candle range defines the zone:

```text
Bullish OB = [low of the bearish OB candle, high of the bearish OB candle]
```

Required conditions:

- bullish BOS is mandatory;
- bullish FVG generated by the impulse is mandatory;
- displacement is mandatory conceptually; V1 uses BOS + FVG as the operational proxy until a numerical displacement filter is calibrated;
- the OB must be unmitigated / untouched before its one permitted first-test setup;
- OTE confluence is mandatory for an entry.

Optional confluences:

- CHoCH before the impulse;
- liquidity sweep before the impulse;
- volume above an average.

### 4.2 Bearish Order Block

Mirror rule:

- last bullish candle before a bearish displacement;
- the displacement creates bearish BOS and bearish FVG;
- zone is the full candle range:

```text
Bearish OB = [low of the bullish OB candle, high of the bullish OB candle]
```

### 4.3 OB first-touch / mitigation policy

This strategy uses a strict one-test policy:

1. An OB is initially `FRESH` after formation.
2. The first price touch of the entry-facing OB boundary opens a one-time setup window.
3. During that first test, the bot may wait for the required LTF reversal confirmation and execute a permitted entry.
4. When that first-test attempt ends—filled order, confirmation timeout, rejection, cancellation, or invalidation—the OB becomes `MITIGATED`.
5. A `MITIGATED` OB must never generate a new entry.

For a bullish OB, the first touch occurs when price returns downward and reaches the OB high. For a bearish OB, the first touch occurs when price returns upward and reaches the OB low.

The strict mitigation policy is strategy-specific: first revisit can be traded only through its one setup window; later revisits are ignored.

---

## 5. Fair Value Gaps

### 5.1 Bullish FVG detection

Use three consecutive closed candles:

- candle 1: `t-2`;
- candle 2: `t-1`, must be bullish;
- candle 3: `t`.

A bullish FVG exists when:

```text
low[t] > high[t-2]
```

Zone:

```text
Bullish FVG = [high[t-2], low[t]]
```

Candle 2 is the displacement candle that creates the imbalance.

### 5.2 Bearish FVG detection

Mirror rule:

- candle 2 must be bearish;
- bearish FVG exists when:

```text
high[t] < low[t-2]
```

Zone:

```text
Bearish FVG = [high[t], low[t-2]]
```

### 5.3 FVG quality and validity

- FVG entry quality: **4-star setup**.
- FVG may be traded as an autonomous setup if all other mandatory confluences are met.
- The FVG may be revisited multiple times while it remains valid.
- Full intrabar fill is tolerated.
- Bullish FVG invalidation: a candle closes below its lower boundary, `high[t-2]`.
- Bearish FVG invalidation: a candle closes above its upper boundary, `low[t-2]`.
- The FVG must be in the OTE zone for entry eligibility.
- FVG size must exceed a **CONFIGURABLE** minimum to avoid trading trivial gaps.

### 5.4 FVG entry modes

For bullish and bearish FVGs symmetrically:

- Aggressive mode: place entry at the 50% midpoint of the FVG.
- Conservative mode: wait for price to return into the FVG, then require LTF reversal confirmation.
- The chosen mode must be configurable, and historical results must be kept separately for aggressive vs conservative execution.

---

## 6. Fibonacci OTE

### 6.1 Anchors

Use confirmed major filtered swings:

- Long setup: draw Fib from the last major filtered HL to the last major filtered HH.
- Short setup: draw Fib from the last major filtered LH to the last major filtered LL.

### 6.2 OTE zone

OTE is mandatory for every FVG and OB entry.

```text
OTE zone = 61.8% to 79.0% retracement of the active impulse leg
Reference / sweet-spot level = 70.5% retracement
```

### 6.3 Confluence rule

A candidate OB or FVG is entry-eligible only if its entry level or a material part of its zone overlaps/intersects the active OTE range. Exact overlap requirements must be **CONFIGURABLE**:

- full zone contained in OTE;
- midpoint of OB/FVG inside OTE;
- any non-trivial geometric overlap;
- entry price specifically inside OTE.

Preferred V1 evaluation: the planned entry price must lie inside OTE, or the midpoint of the candidate OB/FVG must lie inside OTE.

---

## 7. Liquidity and Sweeps

### 7.1 Mandatory liquidity registry

The bot must continuously identify and track:

- major filtered swing highs and lows;
- equal highs and equal lows;
- Asia session high and low;
- London session high and low;
- New York session high and low;
- recognized range support and resistance boundaries.

Optional liquidity references:

- previous day high/low;
- previous week high/low.

### 7.2 Valid sell-side sweep for a long

A candidate bullish reversal / sweep is valid when:

1. price wicks or trades strictly below a registered liquidity low;
2. the same candle closes back above that liquidity level;
3. then LTF confirmation occurs through a reversal pattern and/or bullish micro-CHoCH/BOS.

### 7.3 Valid buy-side sweep for a short

Mirror rule:

1. price wicks or trades strictly above a registered liquidity high;
2. the same candle closes back below that liquidity level;
3. then bearish LTF confirmation occurs.

### 7.4 Sweep role

- Continuation trade aligned with HTF bias: sweep is optional confluence.
- Countertrend/reversal trade: sweep is mandatory.
- A simple wick beyond a level without reclaim is not a reversal sweep; it may be an accepted breakout / liquidity run.
- V1 penetration threshold: strict breach beyond the level is sufficient. ATR/tick penetration filters are **CONFIGURABLE** for backtesting.

---

## 8. LTF Reversal Confirmation

An OB or FVG contact does not automatically trigger an order. Price must also produce a valid LTF confirmation in the trade direction.

### 8.1 Accepted bullish confirmations

At M5/M3/M1 as applicable:

- bullish engulfing;
- hammer / inverted hammer according to context;
- doji followed by bullish confirmation;
- W / double-bottom structure;
- inverse head-and-shoulders;
- bullish micro-CHoCH or BOS;
- M5 bullish micro-CHoCH/BOS followed by M1 retest/confirmation;
- M5 reversal pattern plus M1 bullish micro-CHoCH/BOS;
- M1 reversal pattern plus M1 bullish micro-CHoCH/BOS.

Bearish confirmations are the exact mirror: bearish engulfing, shooting-star/inverted equivalent as defined, M/double-top, head-and-shoulders, bearish micro-CHoCH/BOS, and corresponding M5/M1 sequences.

### 8.2 Pattern definitions

All candle and chart patterns must be mechanical, not discretionary. The following are **CONFIGURABLE**:

- maximum doji body as % of total candle range;
- hammer/shooting-star body and wick ratios;
- engulfing body coverage and minimum body size;
- W/M tolerance, depth, spacing, and neckline break;
- head-and-shoulders symmetry, spacing, neckline, and break confirmation;
- micro-structure pivot lengths and close/wick break rule.

V1 preference: a pattern alone may be accepted only when explicitly listed as an allowed route; otherwise require pattern + micro-CHoCH/BOS for stronger confirmation.

---

## 9. Setup Scoring and Entry Logic

### 9.1 Setup grades

| Grade | Definition |
|---|---|
| 5 stars | Valid fresh OB created by BOS + FVG/displacement proxy, in OTE, compatible with HTF context, and LTF confirmation; optional confluences improve confidence but are not mandatory |
| 4 stars | Valid FVG in OTE, compatible with HTF context, with valid LTF confirmation; may be the first entry of the same directional thesis |

### 9.2 Standard eligibility checklist

A standard long must satisfy:

1. HTF bias bullish or context explicitly allows the trade.
2. An active HL→HH major filtered leg exists for Fib/OTE.
3. Planned entry lies in the 61.8%–79% OTE zone.
4. Candidate FVG or OB is valid and not invalidated/mitigated according to its own policy.
5. LTF bullish confirmation is present.
6. Nearest realistic TP provides the minimum required RR.
7. No session, news, risk, trading-halt, data, or execution guardrail is violated.
8. If the trade is countertrend, a valid sell-side liquidity sweep and H1/M15 reversal confirmation are mandatory.

The short checklist is symmetric.

### 9.3 Order method

- If the setup is valid and price remains in the relevant OB/FVG/OTE zone: use a limit order at the planned entry level.
- If confirmation closes outside the zone but the setup remains valid: a market order may be used to avoid missing the move.
- For a confirmed 5-star setup: create the planned OB/OTE limit order even if price has already moved, provided the setup remains valid, fresh/within its first-test window, and not invalidated.
- The pending order remains valid only while the active OTE + OB/FVG confluence remains valid. Cancel it on structural invalidation, mitigation, zone invalidation, bias invalidation, or session/news risk halt.

### 9.4 Two-entry policy

One directional thesis can have at most two entries:

1. FVG entry, quality 4 stars.
2. OB entry, quality 5 stars.

They are one trade idea and share one total risk budget. They must never be treated as independent 1% risks.

---

## 10. Risk, Stops, Targets, and Management

### 10.1 Total risk cap

```text
Maximum risk per trade idea = 1.00% of total account equity
```

This includes all FVG and OB entries in the same thesis.

Initial allocation for backtesting:

| Entry | Maximum risk allocation |
|---|---:|
| FVG 4-star | 0.30% of equity |
| OB 5-star | 0.70% of equity |
| Combined thesis | 1.00% of equity maximum |

The allocation is configurable and must be evaluated in backtesting.

### 10.2 Structural stop-loss selection

The stop-loss must be set beyond the level that invalidates the thesis, not blindly under/above a zone.

For a long, select the most relevant structural invalidation in this priority order:

1. below the extreme of the valid sell-side sweep, if the sweep is the basis of the trade;
2. below the low of the bullish OB, for an OB 5-star setup without a more relevant sweep extreme;
3. below the lower boundary of the bullish FVG, or below the confirming LTF HL/LL, for FVG 4-star setups;
4. below a more relevant confirmed LTF major HL/LL when it is the true invalidation of the thesis.

For a short, mirror all levels above the relevant buy-side sweep, bearish OB high, bearish FVG high, or confirming LTF LH/HH.

The bot must reject a setup where the structural stop makes the required RR impossible or violates max stop-distance constraints.

### 10.3 Stop buffer

Initial V1 proposal:

```text
stop buffer = max(2 * instrument tick size, 0.10 * ATR(M5, 14))
```

This parameter is configurable and must be optimized by backtest. The final stop is beyond the selected invalidation level by this buffer.

### 10.4 Position size

Position size is derived from the total allowable monetary risk and actual entry-to-stop distance.

```text
position_size = monetary_risk / abs(entry_price - stop_price)
```

Implementation must include contract specifications, fees, expected slippage, rounding/minimum order size, and the shared risk already consumed by an earlier FVG/OB entry.

### 10.5 Minimum reward/risk

- All setups: minimum projected RR to the first realistic target is **1R**.
- 5-star OB setups: minimum projected RR to the first realistic target is **2R**.
- Reject the trade if the next logical liquidity target is too close to meet these conditions.

### 10.6 Take-profit and partial exits

Initial V1 distribution:

| Exit | Rule |
|---|---|
| TP1 | Close 50% at +1R |
| Breakeven | After TP1 fills, move SL on remaining position to entry adjusted for fees and a small anti-slippage buffer |
| TP2 | Close 30% at the first realistic opposing liquidity objective |
| Runner | Keep 20% for a more ambitious structural target; trail under new HLs for longs / above new LHs for shorts |

Valid liquidity targets include:

- next major filtered swing high/low;
- range high/low;
- session high/low;
- opposing FVG;
- opposing OB.

The exact target selection must always honor the minimum RR rule.

### 10.7 Open-position management

- Positions remain protected by active SL/TP orders at all times.
- Positions may remain open through the Asian session; the Asian rule only blocks new entries.
- At daily-loss, daily-profit, or consecutive-loss halt, do not open new trades or add new risk. Existing positions remain managed by their stop, take-profit, partial exits, breakeven, and trailing rules.
- Use reduce-only flags for exit orders where supported, preventing a failed exit from reversing the position.

---

## 11. Session, News, and Operational Guardrails

### 11.1 Asian session

- No new positions may be opened during the Asian session.
- Existing positions remain open and actively managed.
- Session hours and timezone must be configurable. Store and evaluate all timestamps in UTC.

### 11.2 News filter

The trading bot receives a continuously updated status from a dedicated news/event bot.

Block new entries:

- 15 minutes before scheduled high-impact announcements;
- 30 minutes after scheduled high-impact announcements;
- immediately on a major unscheduled economic or geopolitical event alert;
- whenever the external news bot marks market conditions unsafe.

Additional execution/volatility blocks are configurable:

- abnormal M1/M5 ATR expansion;
- expected or observed slippage above threshold;
- spread/market-quality degradation;
- stale or missing market data;
- exchange/API error;
- unconfirmed protective stop-loss order.

### 11.3 Daily and consecutive-loss circuit breakers

- After 3 consecutive losing trade ideas, stop opening new entries until the next trading day / next allowed trading session.
- Daily hard stop: after net daily P&L reaches `-5R`, cancel all pending entry orders and disable new trade ideas until the daily reset.
- Daily profit cap: after net daily P&L reaches `+5R`, stop opening new trade ideas until the daily reset.
- Existing positions remain managed; do not automatically flatten them solely because a daily cap was reached.
- A FVG + OB sequence belonging to one thesis is one trade idea for loss-streak accounting.

### 11.4 Leverage and exposure

- V1 maximum nominal leverage: **10x**.
- Use isolated margin for V1.
- Leverage does not increase permitted risk: total risk remains capped at 1% per idea.
- The bot uses the minimum leverage required for the risk-calculated position size.
- 20x may be evaluated after backtesting, only where liquidation remains far beyond the actual structural SL and all exposure caps remain satisfied.
- Do not enable 50x in the initial autonomous live version.
- Permit only one BTC directional thesis at a time unless a later portfolio/exposure layer explicitly allows otherwise.

### 11.5 Kill switch

Immediately cancel pending entries and block new trades on any of the following:

- missing, stale, inconsistent, or corrupted market data;
- API authentication/execution failure;
- entry order status cannot be reconciled;
- protective SL is not acknowledged/confirmed after a fill;
- unexpected position size or direction;
- risk/exposure calculation failure;
- emergency manual stop command;
- external news bot unsafe-market flag.

Existing open positions require an explicit emergency policy. Preferred V1: attempt to restore/verify protective orders first; if protection cannot be ensured, reduce or close exposure according to a fail-safe execution policy.

---

## 12. Bot State Machine

```text
IDLE
  -> SCAN_CONTEXT
  -> HTF_BIAS_READY
  -> SETUP_ZONE_DETECTED
  -> OTE_VALIDATED
  -> SETUP_ARMED
  -> FIRST_TOUCH_WINDOW (OB only)
  -> WAIT_LTF_CONFIRMATION
  -> ORDER_SUBMITTED
  -> ENTRY_FILLED
  -> PROTECTION_CONFIRMED
  -> MANAGE_POSITION
      -> TP1_FILLED_AND_BE
      -> TP2_FILLED
      -> RUNNER_TRAIL
  -> POSITION_CLOSED
  -> UPDATE_RISK_AND_SESSION_STATS
  -> IDLE
```

### 12.1 Mandatory cancellation transitions

```text
SETUP_ARMED / WAIT_LTF_CONFIRMATION / ORDER_SUBMITTED
  -> CANCELLED
```

when any of the following occurs:

- OB mitigation / end of the OB first-touch setup window;
- OB/FVG invalidation;
- OTE no longer valid for the planned entry;
- HTF/M15 bias invalidation;
- countertrend sweep/reversal condition fails;
- setup expires because price exits the relevant confluence zone;
- Asian-session, news, risk, daily-cap, or kill-switch gate activates;
- order fails or cannot be safely reconciled.

---

## 13. Configurable Parameters for Backtesting

Do not hard-code these as permanent strategy truths. Expose them as config inputs and record performance per setting.

### Structure and trend

- Pivot left/right lengths per timeframe.
- Major-swing filtering: minimum bar spacing, percentage move, ATR move, and swing replacement rules.
- BOS/CHoCH close-versus-wick confirmation.
- Trend-dominance lookback and threshold.
- Trendline anchor count, tolerance, and break confirmation timeframe.
- Range detection: number of touches, tolerance, minimum duration, and breakout confirmation.

### OB and FVG

- OB lookback and last-opposite-candle selection rule.
- Definition/minimum threshold of displacement.
- FVG minimum size in ticks, percentage, or ATR.
- FVG midpoint versus conservative confirmation mode.
- Number of candles allowed from OB/FVG first touch to confirmation.
- Exact OTE overlap condition.
- OB/FVG maximum age and expiration.

### Liquidity and confirmation

- Equal high/low tolerance.
- Sweep penetration threshold in ticks / percentage / ATR.
- Reclaim close definition.
- Pattern thresholds: doji, hammer, shooting star, engulfing, W/M, head-and-shoulders.
- Micro-CHoCH/BOS pivot lengths and confirmation rule.

### Risk and execution

- FVG/OB risk allocation split.
- Stop buffer in ticks and ATR fraction.
- Maximum permissible stop distance.
- Minimum RR by setup grade.
- TP1/TP2/runner percentages.
- Trailing-stop structural rules.
- Fee and slippage assumptions.
- Limit-order expiry and reprice/cancel policy.
- Maximum notionals, leverage, and margin-distance-to-liquidation requirements.

### Operational controls

- Exact Asia-session window in UTC.
- News windows and event severity policy.
- Volatility and slippage thresholds.
- Daily reset time.
- Consecutive-loss cooldown duration.
- Daily hard stop and daily profit cap.

---

## 14. Implementation Priorities

Implement and test in this order:

1. Data ingestion, candle close handling, Hyperliquid order status reconciliation, and kill switch.
2. Market structure and major filtered swing engine.
3. BOS/CHoCH, liquidity registry, trendline, and range detection.
4. Fib/OTE anchors and zone calculation.
5. FVG detection/validity and FVG-only 4-star simulation.
6. OB detection/first-touch mitigation and OB-only 5-star simulation.
7. LTF confirmation engine with individually logged pattern routes.
8. Position sizing, SL/TP, partial exits, breakeven, and trailing logic.
9. Multi-entry shared-risk manager for FVG + OB.
10. Session/news/risk circuit breakers.
11. Historical backtests, out-of-sample testing, paper trading, then small-capital live deployment.

---

## 15. Logging Requirements

For every candidate and executed trade, persist:

- timestamp and all timeframe candle IDs;
- HTF/M15/M5/M1 bias and structural state;
- trendline/range state;
- liquidity level swept, if any;
- OB/FVG identifiers, bounds, source timeframe, age, mitigation/validity state;
- Fib anchors, OTE bounds, and planned entry relation to OTE;
- setup grade (4 or 5 stars);
- confirmation route and exact pattern metrics;
- intended and actual entry, stop, TP levels, fees, and slippage;
- risk allocated, total thesis risk, leverage, margin mode, and position size;
- order lifecycle/status and protection-order confirmation;
- exit reason, realized R, realized P&L, and circuit-breaker state.

This logging is mandatory to diagnose false positives, refine thresholds, and ensure the live bot behaves like the specification.
