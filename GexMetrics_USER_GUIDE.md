# 🔮 GexMetrics — User Guide
## Institutional Options Intelligence for Retail Traders

---

## 🚀 Getting Started

```powershell
cd C:\Users\yshob\Documents\Oracle
.venv\Scripts\Activate.ps1
streamlit run oracle_app.py
```

Opens at http://localhost:8501

---

## 📊 Tab 1 — GEX / VEX Heatmap

### What is GEX (Gamma Exposure)?

When you buy an option, a market maker (dealer) takes the other side.
To stay neutral, dealers constantly hedge their position by buying/selling shares.

**GEX tells you HOW MUCH hedging dealers need to do at each strike.**

```
Positive GEX (green bars) = Dealers are LONG gamma
→ They buy when price falls, sell when price rises
→ Acts like a SHOCK ABSORBER — price gets pinned near this strike
→ Low volatility environment

Negative GEX (red bars) = Dealers are SHORT gamma
→ They sell when price falls, buy when price rises
→ Acts like a FUEL INJECTOR — amplifies moves
→ High volatility environment
```

### How to Trade with GEX

| Scenario | What it means | Trade idea |
|---|---|---|
| Price near large GREEN bar | Strong pin zone — expect chop | Sell premium (spreads) |
| Price near large RED bar | Volatility explosion likely | Buy options, expect big move |
| GEX flips negative | Regime change — vol expansion | Reduce short premium positions |
| Large positive GEX above spot | Ceiling — hard to break through | Consider put spreads |
| Large positive GEX below spot | Floor — hard to break below | Consider call spreads |

### What is VEX (Vanna Exposure)?

Vanna measures how much Delta changes when IV changes.

```
When IV rises → positive VEX = dealers BUY shares → supportive
When IV falls → positive VEX = dealers SELL shares → headwind
```

VEX matters most during IV events (FOMC, earnings, CPI).
High VEX + falling IV = selling pressure from dealer hedging.

---

## 🐋 Tab 2 — Whale Flow Detector

### What counts as a whale trade?

- Premium paid > **$500,000**
- Strike within **10% of current price** (not deep ITM/OTM hedges)
- Detected from unusual volume vs open interest

### SWEEP vs BLOCK

| Trade Type | Vol/OI Ratio | What it means |
|---|---|---|
| 🔥 **SWEEP** | > 3x | Aggressive fresh buying across multiple exchanges. Someone wants in NOW. High conviction directional bet. |
| 📦 **BLOCK** | < 3x | Large single trade. Could be a hedge, roll, or institution adding to existing position. Less directional signal. |

### How to interpret whale flow

```
✅ Strong signal:
- SWEEP on calls = someone aggressively buying upside
- Multiple sweeps on same ticker same day = institutional conviction
- Premium > $1M = serious money

⚠️ Weaker signal:
- BLOCK with low Vol/OI = likely a hedge, not directional
- Deep OTM strikes = could be lottery tickets or tail hedges
- Puts on indices = often portfolio protection, not bearish bets
```

### Real example
```
NVDA  CALL  Strike $220  Expiry 2025-05-16
Premium: $1,250,000  Vol: 5,200  OI: 800  Vol/OI: 6.5x  🔥 SWEEP
→ Someone paid $1.25M aggressively buying NVDA calls
→ Vol/OI of 6.5x = fresh positioning, not a roll
→ Bullish signal — institution expects NVDA to move up before May 16
```

---

## 📋 Tab 3 — Contract Intelligence

### Open Interest (OI) Chart

The horizontal bar chart shows how many contracts are open at each strike.

```
Tall green bar = many call contracts open at that strike
Tall red bar   = many put contracts open at that strike
```

**Large OI = magnetic level** — price tends to gravitate toward high-OI strikes
at expiration (related to max pain theory).

### Max Pain

The strike where the **maximum number of options expire worthless**.
Market makers are incentivized to push price toward max pain at expiration.

```
If spot = $550 and max pain = $540
→ Expect some downward pressure heading into expiry
→ Strongest near expiry (last 2-3 days of the week)
```

### Put/Call Ratio (PCR)

```
PCR < 0.7  = Excessive bullishness (contrarian bearish signal)
PCR 0.7-1.0 = Neutral
PCR > 1.0  = Fear/hedging (contrarian bullish signal)
PCR > 1.5  = Extreme fear — often marks bottoms
```

### IV Skew Chart

Shows implied volatility across strikes.

```
Normal skew: Put IV > Call IV (market pays more for downside protection)
Skew flattening: Bullish — call demand increasing
Reverse skew: Rare — extreme bullish sentiment or squeeze conditions
```

### Liquidity (Bid/Ask Spread)

```
✅ Tight (< 5% spread)   = Easy to enter/exit. Use market orders are okay.
🟡 Moderate (5-15%)      = Use limit orders at midpoint.
🔴 Wide (> 15%)          = Illiquid. Avoid unless conviction is very high.
                            You lose money just entering the trade.
```

---

## 💼 Tab 4 — Portfolio Greeks

### The Greeks Explained Simply

| Greek | What it measures | Rule of thumb |
|---|---|---|
| **Delta** | How much your portfolio gains/loses per $1 move in the underlying | Delta 50 = you gain $50 if stock moves up $1 |
| **Gamma** | How fast Delta changes | High gamma = your delta changes quickly — good if right, bad if wrong |
| **Theta** | Daily time decay in dollars | Theta -$200 = you lose $200/day just from time passing |
| **Vega** | Gain/loss per 1% IV change | Vega $500 = you gain $500 if IV rises 1% |

### Portfolio Risk Interpretation

**Delta:**
```
Positive net delta = Long bias — you profit when market goes UP
Negative net delta = Short bias — you profit when market goes DOWN
Near zero delta    = Market neutral — you profit from other factors (time, vol)
```

**Gamma:**
```
Positive gamma (long options) = You WANT big moves in either direction
Negative gamma (short options) = You WANT the market to stay still
```

**Theta:**
```
Negative theta (long options) = Time works AGAINST you — need the move fast
Positive theta (short options) = Time works FOR you — collect premium daily
```

**Vega:**
```
Positive vega (long options) = You WANT IV to rise (buy before earnings/events)
Negative vega (short options) = You WANT IV to fall (sell after earnings/events)
```

### Example Portfolio Reading

```
Net Delta:  +45   → Moderately bullish — profits if market up
Net Gamma:  +2.3  → Long gamma — benefits from big moves
Net Theta: -$180  → Paying $180/day in time decay
Net Vega:  +$320  → Gains $320 if IV rises 1%

Interpretation:
You have a directional long bias with long volatility exposure.
Best case: Market makes a large move up with rising IV.
Risk: If market stays flat, you lose $180/day.
Action: Set a stop-loss or consider reducing position if no move in 3-5 days.
```

---

## ⚡ Quick Reference Card

```
GEX GREEN bar near price  → Pin zone, sell premium
GEX RED bar near price    → Volatility ahead, buy options
🔥 SWEEP on calls         → Bullish institutional bet
🔥 SWEEP on puts          → Bearish institutional bet
📦 BLOCK on puts          → Likely just a hedge, not directional
Max Pain above spot       → Slight bearish expiry pressure
Max Pain below spot       → Slight bullish expiry pressure
PCR > 1.3                 → Contrarian bullish (too much fear)
PCR < 0.6                 → Contrarian bearish (too complacent)
IV Skew flattening        → Calls being bought, bullish sentiment
Net Theta negative        → Time is your enemy, need move soon
Net Vega positive         → Buy before IV events, sell after
```

---

## ⚠️ Important Limitations

1. **GEX is approximated** — Real GEX requires tick-level options data. Our calculation uses EOD OI + Black-Scholes which is directionally accurate but not precise.

2. **Whale detection uses EOD data** — Real-time sweep detection requires Polygon.io ($29/mo). Current detection identifies high-volume strikes from daily chain.

3. **Max pain is theoretical** — Price does not always converge to max pain. Most reliable in the last 2-3 days before expiry.

4. **Greeks are estimates** — Black-Scholes assumes constant IV and no dividends. Real Greeks from your broker may differ slightly.

5. **Not financial advice** — This tool provides market intelligence to inform your own analysis. Always manage risk appropriately.

---

*Oracle · Built on yfinance · Educational use only*
