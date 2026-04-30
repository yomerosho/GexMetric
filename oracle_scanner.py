"""
Oracle Scanner — Institutional-Grade Options Intelligence
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
    """
    Black-Scholes Greeks.
    S = spot, K = strike, T = time to expiry (years),
    r = risk-free rate, sigma = IV
    """
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
    """Convert expiry string YYYY-MM-DD to years."""
    try:
        exp = datetime.strptime(exp_str, "%Y-%m-%d")
        days = max((exp - datetime.now()).days, 0)
        return max(days / 365, 1/365)
    except:
        return 30 / 365


# ── Options Chain Fetcher ─────────────────────────────────────────────────────

class OptionsChainFetcher:
    """Fetches and processes full options chain for a ticker."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        self._t     = yf.Ticker(ticker)
        self._info  = None
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
        """Get combined calls + puts chain for nearest expiries."""
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

                    # Compute Greeks
                    greeks_list = []
                    for _, row in df.iterrows():
                        iv    = row.get("impliedVolatility", 0.3) or 0.3
                        g     = bs_greeks(spot, row["strike"], dte, 0.05, iv, opt_type)
                        greeks_list.append(g)

                    greeks_df = pd.DataFrame(greeks_list)
                    df = pd.concat([df.reset_index(drop=True),
                                    greeks_df.reset_index(drop=True)], axis=1)

                    # Premium = mid price × volume × 100
                    df["mid_price"] = (df["bid"].fillna(0) + df["ask"].fillna(0)) / 2
                    df["premium"]   = df["mid_price"] * df["volume"].fillna(0) * 100

                    rows.append(df)
                time.sleep(0.2)
            except Exception as e:
                logger.debug(f"{self.ticker} {exp}: {e}")

        if not rows:
            return pd.DataFrame()

        combined = pd.concat(rows, ignore_index=True)
        return combined


# ── GEX / VEX Calculator ──────────────────────────────────────────────────────

class GEXCalculator:
    """
    Gamma Exposure (GEX) approximation.
    GEX = Gamma × OI × 100 × Spot²× 0.01
    Positive GEX = dealers long gamma = market stabilizing
    Negative GEX = dealers short gamma = market amplifying
    """

    def calculate(self, chain: pd.DataFrame, spot: float) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()

        df = chain.copy()
        df["openInterest"] = df["openInterest"].fillna(0)
        df["gamma"]        = df["gamma"].fillna(0)

        # GEX per strike: calls positive, puts negative (dealer perspective)
        df["gex"] = np.where(
            df["option_type"] == "call",
            df["gamma"] * df["openInterest"] * 100 * spot**2 * 0.01,
           -df["gamma"] * df["openInterest"] * 100 * spot**2 * 0.01
        )

        # VEX (Vanna Exposure) — approximated as vega × delta sensitivity
        df["vex"] = df["vega"] * df["delta"].abs() * df["openInterest"] * 100

        # Aggregate by strike
        gex_by_strike = (df.groupby("strike")
                           .agg(gex=("gex","sum"), vex=("vex","sum"),
                                total_oi=("openInterest","sum"),
                                call_oi=("openInterest", lambda x: x[df.loc[x.index,"option_type"]=="call"].sum()),
                                put_oi=("openInterest",  lambda x: x[df.loc[x.index,"option_type"]=="put"].sum()))
                           .reset_index())

        gex_by_strike["net_gex"]    = gex_by_strike["gex"]
        gex_by_strike["pcr"]        = (gex_by_strike["put_oi"] /
                                        gex_by_strike["call_oi"].replace(0, np.nan)).fillna(0)
        gex_by_strike["is_spot"]    = abs(gex_by_strike["strike"] - spot) < spot * 0.01

        return gex_by_strike.sort_values("strike")


# ── Whale Detector ────────────────────────────────────────────────────────────

class WhaleDetector:
    """
    Detects unusual options activity suggesting large institutional positioning.
    Criteria:
    - Premium > $500K
    - Volume/OI ratio > 2 (fresh positioning, not rolling)
    - Strike within 5% of spot (actionable)
    """

    def scan(self, ticker: str, chain: pd.DataFrame,
             spot: float) -> pd.DataFrame:
        if chain.empty: return pd.DataFrame()

        df = chain.copy()
        df["volume"]        = df["volume"].fillna(0)
        df["openInterest"]  = df["openInterest"].fillna(0)
        df["vol_oi_ratio"]  = (df["volume"] /
                                df["openInterest"].replace(0, np.nan)).fillna(0)

        # Filters
        whale = df[
            (df["premium"] >= WHALE_THRESHOLD) &
            (df["volume"] > 0) &
            (abs(df["strike"] - spot) / spot <= 0.10)  # within 10% of spot
        ].copy()

        if whale.empty: return pd.DataFrame()

        # Classify sweep vs block
        whale["trade_type"] = np.where(
            whale["vol_oi_ratio"] > 3,
            "🔥 SWEEP",   # High vol/OI = fresh aggressive buying
            "📦 BLOCK"    # Lower ratio = rolling or hedging
        )

        # Bias
        whale["bias"] = np.where(whale["option_type"] == "call", "🟢 BULLISH", "🔴 BEARISH")

        # Format
        whale["Premium ($)"]   = whale["premium"].apply(lambda x: f"${x:,.0f}")
        whale["Strike"]        = whale["strike"]
        whale["Type"]          = whale["option_type"].str.upper()
        whale["Volume"]        = whale["volume"].astype(int)
        whale["OI"]            = whale["openInterest"].astype(int)
        whale["Vol/OI"]        = whale["vol_oi_ratio"].round(1)
        whale["IV"]            = (whale["impliedVolatility"] * 100).round(1).astype(str) + "%"
        whale["Expiry"]        = whale["expiry"]
        whale["Ticker"]        = ticker

        cols = ["Ticker","Type","Strike","Expiry","Premium ($)",
                "Volume","OI","Vol/OI","IV","bias","trade_type"]
        available = [c for c in cols if c in whale.columns]
        return whale[available].sort_values("Volume", ascending=False).head(20)


# ── Contract Intelligence ─────────────────────────────────────────────────────

class ContractIntelligence:
    """Per-strike volume, OI, liquidity, and max pain analysis."""

    def max_pain(self, chain: pd.DataFrame, spot: float) -> float:
        """Calculate max pain strike."""
        if chain.empty: return spot
        try:
            strikes = sorted(chain["strike"].unique())
            pain    = {}
            for s in strikes:
                calls_itm = chain[(chain["option_type"]=="call") & (chain["strike"] < s)]
                puts_itm  = chain[(chain["option_type"]=="put")  & (chain["strike"] > s)]
                call_pain = ((s - calls_itm["strike"]) *
                              calls_itm["openInterest"].fillna(0) * 100).sum()
                put_pain  = ((puts_itm["strike"] - s) *
                              puts_itm["openInterest"].fillna(0) * 100).sum()
                pain[s]   = call_pain + put_pain
            return min(pain, key=pain.get)
        except:
            return spot

    def summarize(self, chain: pd.DataFrame, spot: float) -> pd.DataFrame:
        """Strike-level summary table."""
        if chain.empty: return pd.DataFrame()

        df = chain.copy()
        df["volume"]       = df["volume"].fillna(0)
        df["openInterest"] = df["openInterest"].fillna(0)
        df["bid"]          = df["bid"].fillna(0)
        df["ask"]          = df["ask"].fillna(0)
        df["spread"]       = df["ask"] - df["bid"]
        df["mid"]          = (df["bid"] + df["ask"]) / 2
        df["liquidity"]    = np.where(
            df["spread"] / df["mid"].replace(0,np.nan) < 0.05, "✅ Tight",
            np.where(df["spread"] / df["mid"].replace(0,np.nan) < 0.15, "🟡 Moderate", "🔴 Wide")
        )

        # Pivot calls vs puts
        calls = df[df["option_type"]=="call"][["strike","volume","openInterest","mid","liquidity","impliedVolatility","delta","gamma"]].copy()
        puts  = df[df["option_type"]=="put"] [["strike","volume","openInterest","mid","liquidity","impliedVolatility","delta"]].copy()

        calls.columns = ["Strike","C_Vol","C_OI","C_Mid","C_Liq","C_IV","C_Delta","C_Gamma"]
        puts.columns  = ["Strike","P_Vol","P_OI","P_Mid","P_Liq","P_IV","P_Delta"]

        merged = calls.merge(puts, on="Strike", how="outer").sort_values("Strike")
        merged["PCR"]   = (merged["P_OI"] / merged["C_OI"].replace(0,np.nan)).round(2)
        merged["Near?"] = abs(merged["Strike"] - spot) / spot < 0.03

        return merged


# ── Portfolio Greeks ──────────────────────────────────────────────────────────

class PortfolioAnalyzer:
    """
    Analyze portfolio Greeks from user-entered positions.
    Each position: ticker, strike, expiry, option_type, contracts, direction (long/short)
    """

    def analyze(self, positions: list) -> pd.DataFrame:
        """
        positions = list of dicts:
        {ticker, strike, expiry, type (call/put), contracts, direction (long/short)}
        """
        rows = []
        for pos in positions:
            try:
                t     = yf.Ticker(pos["ticker"])
                info  = t.info
                spot  = info.get("regularMarketPrice") or info.get("currentPrice") or 0
                dte   = days_to_expiry(pos["expiry"])
                mult  = 1 if pos["direction"] == "long" else -1
                contracts = int(pos.get("contracts", 1))

                # Get IV from chain if available
                iv = 0.3
                try:
                    chain = t.option_chain(pos["expiry"])
                    df    = chain.calls if pos["type"] == "call" else chain.puts
                    row   = df[df["strike"] == pos["strike"]]
                    if not row.empty:
                        iv = float(row.iloc[0]["impliedVolatility"]) or 0.3
                except:
                    pass

                g = bs_greeks(spot, pos["strike"], dte, 0.05, iv, pos["type"])

                rows.append({
                    "Ticker":    pos["ticker"],
                    "Type":      pos["type"].upper(),
                    "Strike":    pos["strike"],
                    "Expiry":    pos["expiry"],
                    "Direction": pos["direction"].upper(),
                    "Contracts": contracts,
                    "Spot":      round(spot, 2),
                    "IV":        f"{iv*100:.1f}%",
                    "Delta":     round(g["delta"] * mult * contracts * 100, 2),
                    "Gamma":     round(g["gamma"] * mult * contracts * 100, 4),
                    "Theta":     round(g["theta"] * mult * contracts * 100, 2),
                    "Vega":      round(g["vega"]  * mult * contracts * 100, 2),
                })
            except Exception as e:
                logger.debug(f"Portfolio position error: {e}")

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df


def portfolio_summary(df: pd.DataFrame) -> dict:
    """Aggregate Greeks across full portfolio."""
    if df.empty:
        return {}
    return {
        "Total Delta": round(df["Delta"].sum(), 2),
        "Total Gamma": round(df["Gamma"].sum(), 4),
        "Total Theta": round(df["Theta"].sum(), 2),
        "Total Vega":  round(df["Vega"].sum(), 2),
        "Positions":   len(df),
        "Tickers":     df["Ticker"].nunique(),
    }
