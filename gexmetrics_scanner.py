"""
GexMetrics Scanner — Institutional-Grade Options Intelligence
=========================================================
Free data via yfinance. Approximated GEX/VEX from OI + Black-Scholes Greeks.
Whale detection via volume/OI anomalies.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional
import logging
import time
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── Tickers ───────────────────────────────────────────────────────────────────

INDICES = ["SPY", "QQQ", "IWM", "DIA"]
MAG7    = ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA"]
ALL     = INDICES + MAG7

WHALE_THRESHOLD = 500_000  # $500K premium minimum

# ── Black-Scholes Greeks ──────────────────────────────────────────────────────

def _norm_cdf(x):
    """Cumulative normal distribution."""
    return (1.0 + np.erf(x / np.sqrt(2.0))) / 2.0

def _norm_pdf(x):
    """Normal probability density."""
    return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "iv": sigma}

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type.lower() == "call":
        delta = _norm_cdf(d1)
    else:
        delta = _norm_cdf(d1) - 1

    gamma = _norm_pdf(d1) / (S * sigma * np.sqrt(T))
    theta = (-(S * _norm_pdf(d1) * sigma) / (2 * np.sqrt(T))
             - r * K * np.exp(-r * T) * _norm_cdf(d2 if option_type=="call" else -d2)) / 365
    vega  = S * _norm_pdf(d1) * np.sqrt(T) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega":  round(vega, 4),
        "iv":    round(sigma, 4),
    }

def days_to_expiry(exp_str: str) -> float:
    try:
        exp = datetime.strptime(exp_str, "%Y-%m-%d")
        days = max((exp - datetime.now()).days, 0)
        return max(days / 365, 1/365)
    except:
        return 30 / 365

# ── Options Chain Fetcher ─────────────────────────────────────────────────────

class OptionsChainFetcher:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self._t     = yf.Ticker(ticker)
        self._spot  = None

    @property
    def spot(self) -> float:
        if self._spot is None:
            try:
                info = self._t.info
                self._spot = (info.get("regularMarketPrice") or
                              info.get("currentPrice") or
                              info.get("previousClose") or 0)
            except:
                self._spot = 0
        return self._spot

    def get_chain(self, max_expiries: int = 4) -> pd.DataFrame:
        try:
            exps = self._t.options[:max_expiries]
        except:
            return pd.DataFrame()

        rows = []
        for exp in exps:
            try:
                chain = self._t.option_chain(exp)
                dte   = days_to_expiry(exp)
                spot  = self.spot

                for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                    if df.empty: continue
                    df = df.copy()
                    df["expiry"]      = exp
                    df["dte_years"]   = dte
                    df["option_type"] = opt_type
                    df["spot"]        = spot

                    greeks_list = []
                    for _, row in df.iterrows():
                        iv    = row.get("impliedVolatility", 0.3) or 0.3
                        g     = bs_greeks(spot, row["strike"], dte, 0.05, iv, opt_type)
                        greeks_list.append(g)

                    greeks_df = pd.DataFrame(greeks_list)
                    df = pd.concat([df.reset_index(drop=True),
                                    greeks_df.reset_index(drop=True)], axis=1)

                    df["mid_price"] = (df["bid"].fillna(0) + df["ask"].fillna(0)) / 2
                    df["premium"]   = df["mid_price"] * df["volume"].fillna(0) * 100
                    rows.append(df)
                time.sleep(0.2)
            except Exception as e:
                logger.debug(f"{self.ticker} {exp}: {e}")

        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

# ── GEX / VEX Calculator ──────────────────────────────────────────────────────

class GEXCalculator:
    def calculate(self, chain: pd.DataFrame, spot: float) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        df = chain.copy()
        df["gex"] = np.where(
            df["option_type"] == "call",
            df["gamma"] * df["openInterest"] * 100 * spot**2 * 0.01,
           -df["gamma"] * df["openInterest"] * 100 * spot**2 * 0.01
        )
        df["vex"] = df["vega"] * df["delta"].abs() * df["openInterest"] * 100
        gex_by_strike = (df.groupby("strike")
                           .agg(gex=("gex","sum"), vex=("vex","sum"),
                                total_oi=("openInterest","sum"),
                                call_oi=("openInterest", lambda x: x[df.loc[x.index,"option_type"]=="call"].sum()),
                                put_oi=("openInterest",  lambda x: x[df.loc[x.index,"option_type"]=="put"].sum()))
                           .reset_index())
        gex_by_strike["net_gex"] = gex_by_strike["gex"]
        return gex_by_strike.sort_values("strike")

# ── Whale Detector ────────────────────────────────────────────────────────────

class WhaleDetector:
    def scan(self, ticker: str, chain: pd.DataFrame, spot: float) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        df = chain.copy()
        df["vol_oi_ratio"] = (df["volume"] / df["openInterest"].replace(0, np.nan)).fillna(0)
        whale = df[(df["premium"] >= WHALE_THRESHOLD) & (df["volume"] > 0) & (abs(df["strike"] - spot) / spot <= 0.10)].copy()
        if whale.empty: return pd.DataFrame()
        whale["trade_type"] = np.where(whale["vol_oi_ratio"] > 3, "🔥 SWEEP", "📦 BLOCK")
        whale["Premium ($)"] = whale["premium"].apply(lambda x: f"${x:,.0f}")
        whale["Type"] = whale["option_type"].str.upper()
        whale["Ticker"] = ticker
        return whale[["Ticker","Type","strike","expiry","Premium ($)","volume","openInterest","vol_oi_ratio","trade_type"]]

# ── Contract Intelligence & Portfolio ─────────────────────────────────────────

class ContractIntelligence:
    def max_pain(self, chain: pd.DataFrame, spot: float) -> float:
        if chain.empty: return spot
        strikes = sorted(chain["strike"].unique())
        pain = {s: (((s - chain[(chain["option_type"]=="call") & (chain["strike"] < s)]["strike"]) * chain[(chain["option_type"]=="call") & (chain["strike"] < s)]["openInterest"].fillna(0) * 100).sum() +
                    ((chain[(chain["option_type"]=="put") & (chain["strike"] > s)]["strike"] - s) * chain[(chain["option_type"]=="put") & (chain["strike"] > s)]["openInterest"].fillna(0) * 100).sum()) for s in strikes}
        return min(pain, key=pain.get)

    def summarize(self, chain: pd.DataFrame, spot: float) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()
        calls = chain[chain["option_type"]=="call"][["strike","volume","openInterest"]].rename(columns={"volume":"C_Vol","openInterest":"C_OI","strike":"Strike"})
        puts = chain[chain["option_type"]=="put"][["strike","volume","openInterest"]].rename(columns={"volume":"P_Vol","openInterest":"P_OI","strike":"Strike"})
        return calls.merge(puts, on="Strike", how="outer")

class PortfolioAnalyzer:
    def analyze(self, positions: list) -> pd.DataFrame:
        rows = []
        for pos in positions:
            t = yf.Ticker(pos["ticker"])
            spot = t.info.get("regularMarketPrice", 0)
            dte = days_to_expiry(pos["expiry"])
            mult = 1 if pos["direction"] == "long" else -1
            g = bs_greeks(spot, pos["strike"], dte, 0.05, 0.3, pos["type"])
            rows.append({"Ticker": pos["ticker"], "Delta": g["delta"] * mult * pos["contracts"] * 100, "Gamma": g["gamma"] * mult * pos["contracts"] * 100, "Theta": g["theta"] * mult * pos["contracts"] * 100, "Vega": g["vega"] * mult * pos["contracts"] * 100})
        return pd.DataFrame(rows)

def portfolio_summary(df: pd.DataFrame) -> dict:
    return {"Total Delta": df["Delta"].sum(), "Total Gamma": df["Gamma"].sum(), "Total Theta": df["Theta"].sum(), "Total Vega": df["Vega"].sum()} if not df.empty else {}
