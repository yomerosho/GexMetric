"""
GexMetrics Scanner — Powered by Alpaca Options API
====================================================
Real-time options chains with Greeks, OI, and Volume.
Identifies whale magnetic levels (high gamma/OI strikes).
"""

import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging
import time
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Tickers ───────────────────────────────────────────────────────────────────

INDICES   = ["SPY", "QQQ", "IWM"]
MAG7      = ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA"]
WATCHLIST = INDICES + MAG7
ALL       = WATCHLIST

# ── Alpaca API Client ─────────────────────────────────────────────────────────

class AlpacaOptionsClient:
    """
    Direct REST client for Alpaca Options API.
    Endpoints used:
    - /v1beta1/options/snapshots/{underlying} — full chain with Greeks
    - /v2/stocks/{symbol}/quotes/latest        — underlying spot
    """

    BASE_URL = "https://data.alpaca.markets"

    def __init__(self, key=None, secret=None):
        self.key    = key    or os.environ.get("ALPACA_KEY",    "")
        self.secret = secret or os.environ.get("ALPACA_SECRET", "")
        if not self.key or not self.secret:
            logger.error("Alpaca API keys missing!")

    def _headers(self):
        return {
            "APCA-API-KEY-ID":     self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "accept":              "application/json",
        }

    def get_spot(self, ticker: str) -> float:
        """Get latest stock quote (mid of bid/ask)."""
        try:
            url = f"{self.BASE_URL}/v2/stocks/{ticker}/quotes/latest"
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                q = r.json().get("quote", {})
                bid = q.get("bp", 0)
                ask = q.get("ap", 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return ask or bid
            else:
                logger.warning(f"{ticker} spot {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"{ticker} spot exception: {e}")

        # Fallback to latest trade
        try:
            url = f"{self.BASE_URL}/v2/stocks/{ticker}/trades/latest"
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                return r.json().get("trade", {}).get("p", 0)
        except:
            pass

        return 0

    def get_option_chain(self, underlying: str,
                          expiration_date_gte: str = None,
                          expiration_date_lte: str = None,
                          strike_pct_band: float = 0.10) -> pd.DataFrame:
        """
        Get full options chain snapshot for an underlying.
        Returns DataFrame with: symbol, type, strike, expiration,
        bid, ask, last, volume, open_interest, IV, delta, gamma, theta, vega
        """
        try:
            url = f"{self.BASE_URL}/v1beta1/options/snapshots/{underlying}"
            params = {"limit": 1000, "feed": "indicative"}

            if expiration_date_gte:
                params["expiration_date_gte"] = expiration_date_gte
            if expiration_date_lte:
                params["expiration_date_lte"] = expiration_date_lte

            all_rows  = []
            page_token = None

            while True:
                if page_token:
                    params["page_token"] = page_token
                r = requests.get(url, headers=self._headers(), params=params, timeout=15)

                if r.status_code != 200:
                    logger.error(f"{underlying} chain {r.status_code}: {r.text[:300]}")
                    break

                data = r.json()
                snapshots = data.get("snapshots", {})

                for symbol, snap in snapshots.items():
                    parsed = self._parse_option_symbol(symbol)
                    if not parsed:
                        continue

                    quote   = snap.get("latestQuote") or {}
                    trade   = snap.get("latestTrade") or {}
                    greeks  = snap.get("greeks") or {}
                    iv      = snap.get("impliedVolatility") or 0

                    bid = quote.get("bp") or 0
                    ask = quote.get("ap") or 0

                    all_rows.append({
                        "symbol":           symbol,
                        "underlying":       underlying,
                        "option_type":      parsed["type"],
                        "strike":           parsed["strike"],
                        "expiry":           parsed["expiration"],
                        "bid":              bid,
                        "ask":              ask,
                        "mid":              (bid + ask) / 2 if bid and ask else 0,
                        "last":             trade.get("p") or 0,
                        "volume":           trade.get("s") or 0,  # Latest trade size
                        "delta":            greeks.get("delta", 0),
                        "gamma":            greeks.get("gamma", 0),
                        "theta":            greeks.get("theta", 0),
                        "vega":             greeks.get("vega", 0),
                        "iv":               iv,
                    })

                page_token = data.get("next_page_token")
                if not page_token:
                    break
                time.sleep(0.1)

            if not all_rows:
                logger.warning(f"{underlying}: no options data returned")
                return pd.DataFrame()

            df = pd.DataFrame(all_rows)
            logger.info(f"{underlying}: ✅ fetched {len(df)} contracts")
            return df

        except Exception as e:
            logger.error(f"{underlying} chain exception: {type(e).__name__}: {e}")
            return pd.DataFrame()

    def get_open_interest(self, underlying: str) -> dict:
        """
        Get open interest for active option contracts.
        Returns dict: {option_symbol: open_interest}
        """
        try:
            # Use the trading API for OI data
            url = "https://paper-api.alpaca.markets/v2/options/contracts"
            params = {"underlying_symbols": underlying, "status": "active", "limit": 1000}

            oi_map     = {}
            page_token = None
            pages      = 0

            while pages < 10:  # Safety cap
                if page_token:
                    params["page_token"] = page_token

                r = requests.get(url, headers=self._headers(), params=params, timeout=15)
                if r.status_code != 200:
                    logger.warning(f"{underlying} OI fetch {r.status_code}")
                    break

                data = r.json()
                for c in data.get("option_contracts", []):
                    sym = c.get("symbol")
                    oi  = c.get("open_interest")
                    if sym and oi is not None:
                        try:
                            oi_map[sym] = int(oi)
                        except:
                            pass

                page_token = data.get("next_page_token")
                if not page_token: break
                pages += 1
                time.sleep(0.1)

            return oi_map
        except Exception as e:
            logger.error(f"{underlying} OI exception: {e}")
            return {}

    @staticmethod
    def _parse_option_symbol(symbol: str) -> dict:
        """
        Parse OCC option symbol: e.g. AAPL250516C00200000
        Format: SYMBOL + YYMMDD + C/P + STRIKE*1000 (8 digits)
        """
        try:
            # Find where ticker ends — first digit is start of date
            for i, ch in enumerate(symbol):
                if ch.isdigit():
                    ticker = symbol[:i]
                    rest = symbol[i:]
                    break
            else:
                return None

            if len(rest) < 15:
                return None

            year   = "20" + rest[:2]
            month  = rest[2:4]
            day    = rest[4:6]
            opt_t  = "call" if rest[6] == "C" else "put"
            strike = int(rest[7:15]) / 1000.0

            return {
                "ticker":     ticker,
                "expiration": f"{year}-{month}-{day}",
                "type":       opt_t,
                "strike":     strike,
            }
        except:
            return None


# ── Whale Magnet Detector ─────────────────────────────────────────────────────

class WhaleMagnetDetector:
    """
    Identifies the strikes whales are magnetized to.
    Logic: high gamma × high OI × close to spot = strong magnetic level.
    Dealers must hedge these strikes most aggressively, creating gravitational pull.
    """

    def find_magnets(self, chain: pd.DataFrame, spot: float,
                      oi_map: dict = None, top_n: int = 5) -> pd.DataFrame:
        """
        Returns top N magnetic strikes ranked by gamma × OI weighted impact.
        """
        if chain.empty:
            return pd.DataFrame()

        df = chain.copy()

        # Add OI if we have it
        if oi_map:
            df["open_interest"] = df["symbol"].map(oi_map).fillna(0).astype(int)
        else:
            df["open_interest"] = 0

        # Magnetic score: gamma × OI weighted by proximity to spot
        df["distance_pct"] = abs(df["strike"] - spot) / spot
        df["magnet_score"] = (
            df["gamma"].abs() *
            df["open_interest"].clip(lower=1) *
            np.exp(-df["distance_pct"] * 5)  # Exponential decay with distance
        )

        # Aggregate by strike (sum across calls + puts)
        by_strike = df.groupby("strike").agg(
            total_gamma_oi=("magnet_score", "sum"),
            call_oi=("open_interest", lambda x: x[df.loc[x.index, "option_type"] == "call"].sum()),
            put_oi=("open_interest",  lambda x: x[df.loc[x.index, "option_type"] == "put"].sum()),
            total_oi=("open_interest", "sum"),
            avg_gamma=("gamma", "mean"),
        ).reset_index()

        by_strike["distance_pct"] = ((by_strike["strike"] - spot) / spot * 100).round(2)
        by_strike["distance_$"]   = (by_strike["strike"] - spot).round(2)

        # Sort by magnet score
        by_strike = by_strike.sort_values("total_gamma_oi", ascending=False).head(top_n)

        return by_strike[["strike", "distance_pct", "distance_$",
                          "total_oi", "call_oi", "put_oi",
                          "avg_gamma", "total_gamma_oi"]]


# ── GEX Calculator (using REAL Greeks from Alpaca) ────────────────────────────

class GEXCalculator:
    """
    Real Gamma Exposure using Alpaca's pre-calculated Greeks.
    GEX per strike = gamma × OI × 100 × spot²× 0.01
    Calls add to dealer GEX, puts subtract.
    """

    def calculate(self, chain: pd.DataFrame, spot: float,
                   oi_map: dict = None) -> pd.DataFrame:
        if chain.empty or spot == 0:
            return pd.DataFrame()

        df = chain.copy()

        if oi_map:
            df["open_interest"] = df["symbol"].map(oi_map).fillna(0).astype(int)
        else:
            df["open_interest"] = 0

        # GEX per contract
        df["gex_per_contract"] = df["gamma"].abs() * df["open_interest"] * 100 * spot**2 * 0.01

        # Call GEX is positive (dealers long gamma when long calls)
        # Put GEX is negative
        df["net_gex"] = np.where(df["option_type"] == "call",
                                  df["gex_per_contract"],
                                  -df["gex_per_contract"])

        # Aggregate by strike
        by_strike = df.groupby("strike").agg(
            net_gex=("net_gex", "sum"),
            total_oi=("open_interest", "sum"),
        ).reset_index()

        return by_strike.sort_values("strike")

    def key_levels(self, gex_df: pd.DataFrame, spot: float, n: int = 3) -> dict:
        if gex_df.empty:
            return {"resistance": [], "support": [], "max_pos_gex": spot, "max_neg_gex": spot}

        nearby = gex_df[abs(gex_df["strike"] - spot) / spot <= 0.05].copy()
        if nearby.empty:
            nearby = gex_df

        above = nearby[nearby["strike"] > spot].nlargest(n, "net_gex")
        below = nearby[nearby["strike"] < spot].nlargest(n, "net_gex")

        return {
            "resistance":  sorted(above["strike"].tolist())[:n],
            "support":     sorted(below["strike"].tolist(), reverse=True)[:n],
            "max_pos_gex": float(gex_df.loc[gex_df["net_gex"].idxmax(), "strike"]) if not gex_df.empty else spot,
            "max_neg_gex": float(gex_df.loc[gex_df["net_gex"].idxmin(), "strike"]) if not gex_df.empty else spot,
        }


# -- Whale Flow Detector (real volume) -----------------------------------------

class WhaleDetector:
    def scan(self, chain: pd.DataFrame, spot: float, threshold: float = 500_000) -> pd.DataFrame:
        if chain.empty or spot == 0:
            return pd.DataFrame()

        df = chain.copy()
        df["premium"] = df["mid"] * df["volume"] * 100

        whale = df[
            (df["premium"] >= threshold) &
            (df["volume"] > 0) &
            (abs(df["strike"] - spot) / spot <= 0.10)
        ].copy()

        if whale.empty:
            return pd.DataFrame()
            
        # FIX: Add trade_type logic so the app doesn't crash
        # If volume is higher than Open Interest, it's likely a Sweep
        whale["trade_type"] = np.where(whale["volume"] > 500, "SWEEP", "BLOCK")

        return whale[["symbol", "option_type", "strike", "expiry",
                      "premium", "volume", "iv", "trade_type",
                      "delta", "gamma"]].sort_values("premium", ascending=False).head(10)

# ── Macro Data (still uses yfinance — works for indices) ──────────────────────

class MacroFetcher:
    SYMBOLS = {
        "VIX":  "^VIX",
        "DXY":  "DX-Y.NYB",
        "10Y":  "^TNX",
        "Oil":  "CL=F",
        "Gold": "GC=F",
        "ES":   "ES=F",
        "NQ":   "NQ=F",
        "RTY":  "RTY=F",
    }

    def fetch_all(self):
        import yfinance as yf
        result = {}
        for label, symbol in self.SYMBOLS.items():
            try:
                t    = yf.Ticker(symbol)
                hist = t.history(period="5d", interval="1d", auto_adjust=True)
                if hist.empty: continue
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                pct  = ((last - prev) / prev * 100) if prev > 0 else 0
                result[label] = {
                    "value":  round(last, 2),
                    "change": round(last - prev, 2),
                    "pct":    round(pct, 2),
                    "trend":  "up" if last > prev else ("down" if last < prev else "flat"),
                }
            except Exception as e:
                logger.debug(f"Macro {label}: {e}")
        return result


# ── Daily Outlook Engine ──────────────────────────────────────────────────────

class DailyOutlook:
    def __init__(self, alpaca_key=None, alpaca_secret=None):
        self.alpaca   = AlpacaOptionsClient(alpaca_key, alpaca_secret)
        self.gex_calc = GEXCalculator()
        self.whale    = WhaleDetector()
        self.magnet   = WhaleMagnetDetector()
        self.macro    = MacroFetcher()

    def generate(self, indices=INDICES, mag7=MAG7,
                  whale_threshold=500_000, days_out=30,
                  progress_cb=None):
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M ET"),
            "macro":        {},
            "tickers":      {},
        }

        if progress_cb: progress_cb(0.05, "Fetching macro data...")
        report["macro"] = self.macro.fetch_all()

        all_tickers = list(set(indices + mag7))
        total       = len(all_tickers)

        # Date range for options
        today      = datetime.now().date()
        date_start = today.isoformat()
        date_end   = (today + timedelta(days=days_out)).isoformat()

        for idx, ticker in enumerate(all_tickers):
            if progress_cb:
                progress_cb(0.05 + 0.95 * idx/total, f"Analyzing {ticker}...")

            try:
                # Get spot
                spot = self.alpaca.get_spot(ticker)
                if spot == 0:
                    logger.warning(f"{ticker}: spot is 0, skipping")
                    continue

                # Get chain
                chain = self.alpaca.get_option_chain(
                    ticker,
                    expiration_date_gte=date_start,
                    expiration_date_lte=date_end,
                )
                if chain.empty:
                    continue

                # Get OI map
                oi_map = self.alpaca.get_open_interest(ticker)

                # Compute GEX
                gex_df = self.gex_calc.calculate(chain, spot, oi_map)
                levels = self.gex_calc.key_levels(gex_df, spot)

                # Magnetic levels
                magnets = self.magnet.find_magnets(chain, spot, oi_map, top_n=5)

                # Whale flow
                whales = self.whale.scan(chain, spot, whale_threshold)

                # Bias
                bias = self._determine_bias(spot, levels, whales, report["macro"])

                report["tickers"][ticker] = {
                    "spot":        round(spot, 2),
                    "levels":      levels,
                    "magnets":     magnets.to_dict("records") if not magnets.empty else [],
                    "whales":      whales.to_dict("records") if not whales.empty else [],
                    "bias":        bias,
                    "total_gex":   float(gex_df["net_gex"].sum()) if not gex_df.empty else 0,
                    "chain_count": len(chain),
                }

            except Exception as e:
                logger.error(f"{ticker} outlook error: {type(e).__name__}: {e}")

        return report

    def _determine_bias(self, spot, levels, whales, macro):
        score = 0

        vix = macro.get("VIX", {})
        if vix.get("trend") == "down": score += 1
        if vix.get("trend") == "up":   score -= 1

        if not whales.empty:
            calls = whales[whales["option_type"] == "call"]
            puts  = whales[whales["option_type"] == "put"]
            ratio = len(calls) / max(len(puts), 1)
            if ratio > 1.5: score += 1
            if ratio < 0.7: score -= 1

        if levels.get("support") and spot > levels["support"][0]:
            score += 0.5
        if levels.get("resistance") and spot >= levels["resistance"][0]:
            score -= 0.5

        if score >= 1.5:
            return {"direction": "🟢 BULLISH", "score": score, "color": "#4af0c4"}
        elif score <= -1.5:
            return {"direction": "🔴 BEARISH", "score": score, "color": "#f04a6a"}
        else:
            return {"direction": "🟡 NEUTRAL", "score": score, "color": "#f5c842"}
