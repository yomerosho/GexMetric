"""
GexMetrics Scanner — Options Intelligence + Daily Outlook Engine
================================================================
Phase 1: Macro context, dealer positioning, earnings calendar
Phase 2-4: Whale flow integration, catalyst scraper, multi-time emails
"""

import yfinance as yf
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

# Futures + macro proxies (yfinance symbols)
MACRO = {
    "VIX":   "^VIX",        # Volatility index
    "DXY":   "DX-Y.NYB",    # Dollar index
    "10Y":   "^TNX",        # 10-year yield
    "Oil":   "CL=F",        # Crude oil futures
    "Gold":  "GC=F",        # Gold futures
    "ES":    "ES=F",        # S&P futures
    "NQ":    "NQ=F",        # Nasdaq futures
    "RTY":   "RTY=F",       # Russell futures
}

# ── Black-Scholes Greeks ──────────────────────────────────────────────────────

def _norm_cdf(x):
    return (1.0 + np.erf(x / np.sqrt(2.0))) / 2.0

def _norm_pdf(x):
    return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "iv": sigma}
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type.lower() == "call":
        delta = _norm_cdf(d1)
    else:
        delta = _norm_cdf(d1) - 1
    gamma = _norm_pdf(d1) / (S * sigma * np.sqrt(T))
    return {"delta": round(delta,4), "gamma": round(gamma,6),
            "theta": 0, "vega": 0, "iv": round(sigma,4)}


def days_to_expiry(exp_str):
    try:
        return max((datetime.strptime(exp_str, "%Y-%m-%d") - datetime.now()).days / 365, 1/365)
    except:
        return 0.1


# ── Options Chain Fetcher ─────────────────────────────────────────────────────

class OptionsChainFetcher:
    def __init__(self, ticker):
        self.ticker = ticker
        self.t = yf.Ticker(ticker)
        self.spot = self._get_spot()

    def _get_spot(self):
        # Try multiple methods to get spot price
        try:
            info = self.t.info
            spot = (info.get("regularMarketPrice") or
                    info.get("currentPrice") or
                    info.get("previousClose") or 0)
            if spot and spot > 0:
                return float(spot)
        except Exception as e:
            logger.warning(f"{self.ticker} info failed: {e}")

        # Fallback: use recent history
        try:
            hist = self.t.history(period="2d", interval="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"{self.ticker} history failed: {e}")

        return 0

    def get_chain(self, max_expiries=3):
        rows = []
        try:
            options_list = self.t.options
            if not options_list:
                logger.warning(f"{self.ticker}: no options expiries available")
                return pd.DataFrame()

            for exp in list(options_list)[:max_expiries]:
                try:
                    time.sleep(0.5)  # Rate limit pause
                    c = self.t.option_chain(exp)
                    for typ, df in [("call", c.calls), ("put", c.puts)]:
                        if df.empty: continue
                        df = df.copy()
                        df["option_type"] = typ
                        df["expiry"]      = exp
                        df["mid"]         = ((df["bid"].fillna(0) + df["ask"].fillna(0)) / 2)
                        df["premium"]     = df["mid"] * df["volume"].fillna(0) * 100
                        rows.append(df)
                except Exception as inner_e:
                    logger.warning(f"{self.ticker} {exp}: {inner_e}")
                    continue

            if rows:
                logger.info(f"{self.ticker}: fetched {len(rows)} expiry groups, spot=${self.spot:.2f}")
                return pd.concat(rows, ignore_index=True)
            else:
                logger.warning(f"{self.ticker}: no chain data returned")
                return pd.DataFrame()

        except Exception as e:
            logger.error(f"{self.ticker} chain fetch failed: {e}")
            return pd.DataFrame()


# ── GEX Calculator (proper version) ───────────────────────────────────────────

class GEXCalculator:
    """
    Real Gamma Exposure calculation using Black-Scholes gamma.
    Positive GEX = dealers long gamma (stabilizing)
    Negative GEX = dealers short gamma (amplifying)
    """

    def calculate(self, chain, spot, r=0.05):
        if chain.empty or spot == 0:
            return pd.DataFrame()

        df = chain.copy()
        df["openInterest"] = df["openInterest"].fillna(0)
        df["impliedVolatility"] = df["impliedVolatility"].fillna(0.3)

        # Compute gamma for each contract
        gammas = []
        for _, row in df.iterrows():
            T = days_to_expiry(row["expiry"])
            iv = max(row["impliedVolatility"], 0.05)
            g = bs_greeks(spot, row["strike"], T, r, iv, row["option_type"])
            gammas.append(g["gamma"])
        df["gamma_calc"] = gammas

        # GEX per contract: gamma × OI × 100 (contract size) × spot²×0.01
        # Calls add to dealer gamma exposure, puts subtract
        df["gex_contribution"] = np.where(
            df["option_type"] == "call",
             df["gamma_calc"] * df["openInterest"] * 100 * spot**2 * 0.01,
            -df["gamma_calc"] * df["openInterest"] * 100 * spot**2 * 0.01
        )

        # Aggregate by strike
        result = df.groupby("strike").agg(
            net_gex=("gex_contribution", "sum"),
            total_oi=("openInterest", "sum"),
            call_oi=("openInterest", lambda x: x[df.loc[x.index, "option_type"] == "call"].sum()),
            put_oi=("openInterest", lambda x: x[df.loc[x.index, "option_type"] == "put"].sum()),
        ).reset_index()
        result["net_gex"] = result["net_gex"].astype(float)

        return result.sort_values("strike")

    def key_levels(self, gex_df, spot, n=3):
        """Find top N positive (resistance) and negative (support) GEX strikes near spot."""
        if gex_df.empty: return {"resistance": [], "support": [], "max_pain": spot}

        nearby = gex_df[abs(gex_df["strike"] - spot) / spot <= 0.05].copy()
        if nearby.empty: nearby = gex_df

        # Resistance = highest positive GEX above spot
        above = nearby[nearby["strike"] > spot].nlargest(n, "net_gex")["strike"].tolist()
        # Support = highest positive GEX below spot
        below = nearby[nearby["strike"] < spot].nlargest(n, "net_gex")["strike"].tolist()

        return {
            "resistance": sorted(above)[:n],
            "support": sorted(below, reverse=True)[:n],
        }


# ── Whale Detector (improved) ─────────────────────────────────────────────────

class WhaleDetector:
    def scan(self, ticker, chain, spot, threshold=500_000):
        if chain.empty or spot == 0:
            return pd.DataFrame()

        df = chain.copy()
        df["volume"]       = df["volume"].fillna(0)
        df["openInterest"] = df["openInterest"].fillna(0)
        df["vol_oi_ratio"] = df["volume"] / df["openInterest"].replace(0, np.nan)

        # Filter: premium >= threshold AND within 10% of spot
        whale = df[
            (df["premium"] >= threshold) &
            (df["volume"] > 0) &
            (abs(df["strike"] - spot) / spot <= 0.10)
        ].copy()

        if whale.empty: return pd.DataFrame()

        whale["trade_type"] = np.where(whale["vol_oi_ratio"] > 3, "🔥 SWEEP", "📦 BLOCK")
        whale["bias"]       = np.where(whale["option_type"] == "call", "🟢 BULLISH", "🔴 BEARISH")
        whale["Ticker"]     = ticker

        return whale[["Ticker", "option_type", "strike", "expiry",
                      "premium", "volume", "openInterest",
                      "impliedVolatility", "trade_type", "bias"]].sort_values(
            "premium", ascending=False).head(10)


# ── Macro Data Fetcher ────────────────────────────────────────────────────────

class MacroFetcher:
    """Fetches VIX, DXY, 10Y yield, oil, gold, futures."""

    def fetch_all(self):
        result = {}
        for label, symbol in MACRO.items():
            try:
                t = yf.Ticker(symbol)
                hist = t.history(period="5d", interval="1d", auto_adjust=True)
                if hist.empty:
                    continue
                last  = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                pct   = ((last - prev) / prev * 100) if prev > 0 else 0
                result[label] = {
                    "value":   round(last, 2),
                    "change":  round(last - prev, 2),
                    "pct":     round(pct, 2),
                    "trend":   "up" if last > prev else ("down" if last < prev else "flat"),
                }
            except Exception as e:
                logger.debug(f"Macro {label}: {e}")
        return result


# ── Earnings Calendar ─────────────────────────────────────────────────────────

class EarningsCalendar:
    """Fetch upcoming earnings dates for a list of tickers."""

    def fetch(self, tickers, days_ahead=14):
        results = []
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar
                if cal is None or (hasattr(cal, "empty") and cal.empty):
                    continue
                # yfinance returns either dict or DataFrame depending on version
                date = None
                if isinstance(cal, dict):
                    date = cal.get("Earnings Date")
                    if isinstance(date, list) and date:
                        date = date[0]
                else:
                    try:
                        date = cal.loc["Earnings Date"].iloc[0]
                    except:
                        pass

                if date:
                    if isinstance(date, str):
                        try:
                            date = datetime.strptime(date.split()[0], "%Y-%m-%d")
                        except:
                            continue
                    # Convert to datetime
                    if hasattr(date, "to_pydatetime"):
                        date = date.to_pydatetime()
                    days_until = (date - datetime.now()).days
                    if 0 <= days_until <= days_ahead:
                        results.append({
                            "ticker":    ticker,
                            "date":      date.strftime("%Y-%m-%d") if hasattr(date,"strftime") else str(date)[:10],
                            "days":      days_until,
                            "weekday":   date.strftime("%A") if hasattr(date,"strftime") else "—",
                        })
            except Exception as e:
                logger.debug(f"Earnings {ticker}: {e}")
        return sorted(results, key=lambda x: x["days"])


# ── Daily Outlook Generator ───────────────────────────────────────────────────

class DailyOutlook:
    """Synthesizes macro + dealer positioning + flow into a directional bias report."""

    def __init__(self):
        self.macro_fetcher = MacroFetcher()
        self.earnings      = EarningsCalendar()
        self.gex_calc      = GEXCalculator()
        self.whale_det     = WhaleDetector()

    def generate(self, indices=INDICES, mag7=MAG7, max_expiries=3,
                  whale_threshold=500_000, progress_cb=None):
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M ET"),
            "macro":        {},
            "earnings":     [],
            "tickers":      {},
        }

        # Macro
        if progress_cb: progress_cb(0.05, "Fetching macro data...")
        report["macro"] = self.macro_fetcher.fetch_all()

        # Earnings (Mag7 only)
        if progress_cb: progress_cb(0.15, "Loading earnings calendar...")
        report["earnings"] = self.earnings.fetch(mag7, days_ahead=14)

        # Per-ticker analysis
        all_tickers = indices + mag7
        total       = len(all_tickers)

        for idx, ticker in enumerate(all_tickers):
            if progress_cb:
                progress_cb(0.15 + 0.85 * idx/total, f"Analyzing {ticker}...")

            try:
                fetcher = OptionsChainFetcher(ticker)
                chain   = fetcher.get_chain(max_expiries=max_expiries)
                spot    = fetcher.spot

                if chain.empty or spot == 0:
                    continue

                gex_df  = self.gex_calc.calculate(chain, spot)
                levels  = self.gex_calc.key_levels(gex_df, spot, n=3)
                whales  = self.whale_det.scan(ticker, chain, spot, whale_threshold)

                # Determine bias
                bias = self._determine_bias(spot, levels, whales, report["macro"])

                report["tickers"][ticker] = {
                    "spot":      round(spot, 2),
                    "levels":    levels,
                    "bias":      bias,
                    "whales":    whales.to_dict("records") if not whales.empty else [],
                    "gex_total": float(gex_df["net_gex"].sum()) if not gex_df.empty else 0,
                }
            except Exception as e:
                logger.debug(f"Outlook {ticker}: {e}")

        return report

    def _determine_bias(self, spot, levels, whales, macro):
        """Synthesize dealer levels + whale flow + macro → directional bias."""
        score = 0  # +1 bullish, -1 bearish

        # Macro signal
        vix = macro.get("VIX", {})
        if vix.get("trend") == "down": score += 1
        if vix.get("trend") == "up":   score -= 1

        # Whale signal
        if not whales.empty:
            calls = whales[whales["option_type"] == "call"]
            puts  = whales[whales["option_type"] == "put"]
            cp_ratio = len(calls) / max(len(puts), 1)
            if cp_ratio > 1.5: score += 1
            if cp_ratio < 0.7: score -= 1

        # Position relative to support/resistance
        if levels["support"] and spot > levels["support"][0]:
            score += 0.5
        if levels["resistance"] and spot >= levels["resistance"][0]:
            score -= 0.5

        if score >= 1.5:
            return {"direction": "🟢 BULLISH", "score": score, "color": "#4af0c4"}
        elif score <= -1.5:
            return {"direction": "🔴 BEARISH", "score": score, "color": "#f04a6a"}
        else:
            return {"direction": "🟡 NEUTRAL", "score": score, "color": "#f5c842"}


# ── Legacy class stubs for compatibility ──────────────────────────────────────

class ContractIntelligence:
    def max_pain(self, chain, spot): return spot
    def summarize(self, chain, spot): return chain.head() if not chain.empty else pd.DataFrame()


class PortfolioAnalyzer:
    def analyze(self, pos): return pd.DataFrame()


def portfolio_summary(df): return {}
