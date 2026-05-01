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
    BASE_URL = "https://data.alpaca.markets"

    def __init__(self, key=None, secret=None):
        self.key    = key    or os.environ.get("ALPACA_KEY",    "")
        self.secret = secret or os.environ.get("ALPACA_SECRET", "")

    def _headers(self):
        return {
            "APCA-API-KEY-ID":     self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "accept":              "application/json",
        }

    def get_spot(self, ticker: str) -> float:
        try:
            url = f"{self.BASE_URL}/v2/stocks/{ticker}/quotes/latest"
            r = requests.get(url, headers=self._headers(), timeout=10)
            if r.status_code == 200:
                q = r.json().get("quote", {})
                bid, ask = q.get("bp", 0), q.get("ap", 0)
                return (bid + ask) / 2 if bid and ask else ask or bid
        except Exception as e:
            logger.error(f"{ticker} spot exception: {e}")
        return 0

    def get_option_chain(self, underlying: str,
                          expiration_date_gte: str = None,
                          expiration_date_lte: str = None) -> pd.DataFrame:
        try:
            url = f"{self.BASE_URL}/v1beta1/options/snapshots/{underlying}"
            params = {"limit": 1000, "feed": "indicative"}
            if expiration_date_gte: params["expiration_date_gte"] = expiration_date_gte
            if expiration_date_lte: params["expiration_date_lte"] = expiration_date_lte

            all_rows, page_token = [], None
            while True:
                if page_token: params["page_token"] = page_token
                r = requests.get(url, headers=self._headers(), params=params, timeout=15)
                if r.status_code != 200: break
                
                data = r.json()
                for symbol, snap in data.get("snapshots", {}).items():
                    parsed = self._parse_option_symbol(symbol)
                    if not parsed: continue
                    greeks = snap.get("greeks") or {}
                    quote = snap.get("latestQuote") or {}
                    trade = snap.get("latestTrade") or {}
                    bid, ask = quote.get("bp") or 0, quote.get("ap") or 0

                    all_rows.append({
                        "symbol": symbol, "option_type": parsed["type"],
                        "strike": parsed["strike"], "expiry": parsed["expiration"],
                        "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
                        "volume": trade.get("s") or 0, "delta": greeks.get("delta", 0),
                        "gamma": greeks.get("gamma", 0), "iv": snap.get("impliedVolatility") or 0
                    })
                page_token = data.get("next_page_token")
                if not page_token: break
            return pd.DataFrame(all_rows)
        except Exception as e:
            logger.error(f"{underlying} chain error: {e}")
            return pd.DataFrame()

    def get_open_interest(self, underlying: str) -> dict:
        try:
            url = "https://paper-api.alpaca.markets/v2/options/contracts"
            params = {"underlying_symbols": underlying, "status": "active", "limit": 1000}
            oi_map, page_token = {}, None
            while True:
                if page_token: params["page_token"] = page_token
                r = requests.get(url, headers=self._headers(), params=params, timeout=15)
                if r.status_code != 200: break
                data = r.json()
                for c in data.get("option_contracts", []):
                    oi_map[c.get("symbol")] = int(c.get("open_interest") or 0)
                page_token = data.get("next_page_token")
                if not page_token: break
            return oi_map
        except: return {}

    @staticmethod
    def _parse_option_symbol(symbol: str) -> dict:
        try:
            for i, ch in enumerate(symbol):
                if ch.isdigit():
                    ticker, rest = symbol[:i], symbol[i:]
                    break
            else: return None
            opt_t = "call" if rest[6] == "C" else "put"
            return {"expiration": f"20{rest[:2]}-{rest[2:4]}-{rest[4:6]}", "type": opt_t, "strike": int(rest[7:15]) / 1000.0}
        except: return None

# ── Whale Detector ────────────────────────────────────────────────────────────
class WhaleDetector:
    def scan(self, chain: pd.DataFrame, spot: float, threshold: float = 500_000) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        df = chain.copy()
        df["premium"] = df["mid"] * df["volume"] * 100
        whale = df[(df["premium"] >= threshold) & (df["volume"] > 0)].copy()
        if whale.empty: return pd.DataFrame()
        
        # FIX: Added trade_type logic to classify trades based on volume
        whale["trade_type"] = np.where(whale["volume"] > 500, "SWEEP", "BLOCK")
        return whale.sort_values("premium", ascending=False).head(5)

# ── Whale Magnet Detector ─────────────────────────────────────────────────────
class WhaleMagnetDetector:
    def find_magnets(self, chain: pd.DataFrame, spot: float, oi_map: dict = None, top_n: int = 5) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        df = chain.copy()
        df["open_interest"] = df["symbol"].map(oi_map or {}).fillna(0)
        df["distance_pct"] = abs(df["strike"] - spot) / spot
        df["magnet_score"] = df["gamma"].abs() * df["open_interest"] * np.exp(-df["distance_pct"] * 5)
        
        by_strike = df.groupby("strike").agg(total_gamma_oi=("magnet_score", "sum"), total_oi=("open_interest", "sum")).reset_index()
        by_strike["distance_pct"] = ((by_strike["strike"] - spot) / spot * 100).round(2)
        return by_strike.sort_values("total_gamma_oi", ascending=False).head(top_n)

# ── GEX Calculator ────────────────────────────────────────────────────────────
class GEXCalculator:
    def calculate(self, chain: pd.DataFrame, spot: float, oi_map: dict = None) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        df = chain.copy()
        df["open_interest"] = df["symbol"].map(oi_map or {}).fillna(0)
        df["net_gex"] = np.where(df["option_type"] == "call", 1, -1) * df["gamma"].abs() * df["open_interest"] * 100 * spot**2 * 0.01
        return df.groupby("strike").agg(net_gex=("net_gex", "sum")).reset_index()

    def key_levels(self, gex_df: pd.DataFrame, spot: float, n: int = 3) -> dict:
        if gex_df.empty: return {"resistance": [], "support": []}
        above = gex_df[gex_df["strike"] > spot].nlargest(n, "net_gex")
        below = gex_df[gex_df["strike"] < spot].nlargest(n, "net_gex")
        return {"resistance": sorted(above["strike"].tolist()), "support": sorted(below["strike"].tolist(), reverse=True)}

# ── Macro Fetcher ─────────────────────────────────────────────────────────────
class MacroFetcher:
    def fetch_all(self):
        result = {}
        for label, sym in {"VIX": "^VIX", "DXY": "DX-Y.NYB", "ES": "ES=F"}.items():
            try:
                hist = yf.Ticker(sym).history(period="2d")
                last, prev = hist["Close"].iloc[-1], hist["Close"].iloc[-2]
                result[label] = {"value": round(last, 2), "pct": round((last-prev)/prev*100, 2), "trend": "up" if last > prev else "down"}
            except: pass
        return result

# ── Daily Outlook Engine ──────────────────────────────────────────────────────
class DailyOutlook:
    def __init__(self, key, secret):
        self.alpaca, self.gex, self.whale, self.magnet, self.macro = AlpacaOptionsClient(key, secret), GEXCalculator(), WhaleDetector(), WhaleMagnetDetector(), MacroFetcher()

    def generate(self, indices=INDICES, mag7=MAG7, whale_threshold=500_000, days_out=30, progress_cb=None):
        report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M ET"), "macro": self.macro.fetch_all(), "tickers": {}}
        tickers = list(set(indices + mag7))
        for i, t in enumerate(tickers):
            if progress_cb: progress_cb(0.1 + 0.9 * i/len(tickers), f"Scanning {t}...")
            spot = self.alpaca.get_spot(t)
            if spot == 0: continue
            chain = self.alpaca.get_option_chain(t, datetime.now().date().isoformat(), (datetime.now() + timedelta(days=days_out)).date().isoformat())
            oi_map = self.alpaca.get_open_interest(t)
            gex_df = self.gex.calculate(chain, spot, oi_map)
            report["tickers"][t] = {
                "spot": spot, "levels": self.gex.key_levels(gex_df, spot),
                "magnets": self.magnet.find_magnets(chain, spot, oi_map).to_dict("records"),
                "whales": self.whale.scan(chain, spot, whale_threshold).to_dict("records"),
                "bias": {"direction": "🟢 BULLISH" if gex_df["net_gex"].sum() > 0 else "🔴 BEARISH", "color": "#4af0c4" if gex_df["net_gex"].sum() > 0 else "#f04a6a"}
            }
        return report
