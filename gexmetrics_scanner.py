import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import time

INDICES = ["SPY", "QQQ", "IWM", "DIA"]
MAG7 = ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA"]
WATCHLIST = ["IWM", "QQQ", "SPY", "AAPL", "AMD", "AMZN", "ARM", "BABA", "COIN", "CRWV", "GOOGL", "NVDA", "TSLA", "TSLL", "JD", "HIMS", "HOOD", "IONQ", "IREN", "INTC", "LMND", "NBIS", "NFLX", "OKLO", "ORCL", "OXY", "PINS", "PLTR", "PYPL", "RBLX", "RDDT", "RKLB", "SOFI", "UNH", "WMT"]
ALL = list(set(INDICES + WATCHLIST))

def _norm_cdf(x): return (1.0 + np.erf(x / np.sqrt(2.0))) / 2.0
def _norm_pdf(x): return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    if T <= 0 or sigma <= 0: return {"delta":0,"gamma":0,"theta":0,"vega":0,"iv":sigma}
    d1 = (np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)
    delta = _norm_cdf(d1) if option_type=="call" else _norm_cdf(d1)-1
    gamma = _norm_pdf(d1)/(S*sigma*np.sqrt(T))
    return {"delta":delta,"gamma":gamma,"theta":0,"vega":0,"iv":sigma}

def days_to_expiry(exp_str):
    try: return max((datetime.strptime(exp_str, "%Y-%m-%d") - datetime.now()).days / 365, 1/365)
    except: return 0.1

class OptionsChainFetcher:
    def __init__(self, ticker):
        self.ticker = ticker
        self.t = yf.Ticker(ticker)
        self.spot = self.t.info.get("regularMarketPrice") or self.t.info.get("currentPrice") or 0

    def get_chain(self, max_expiries=3):
        rows = []
        try:
            for exp in self.t.options[:max_expiries]:
                # PAUSE FOR 1 SECOND BEFORE EACH REQUEST
                time.sleep(1) 
                
                c = self.t.option_chain(exp)
                for typ, df in [("call", c.calls), ("put", c.puts)]:
                    df = df.copy()
                    df["option_type"], df["expiry"] = typ, exp
                    df["premium"] = ((df["bid"]+df["ask"])/2) * df["volume"] * 100
                    rows.append(df)
            return pd.concat(rows)
        except Exception as e:
            print(f"Error fetching {self.ticker}: {e}")
            return pd.DataFrame()

class GEXCalculator:
    def calculate(self, chain, spot):
        return chain.groupby("strike").agg({"openInterest":"sum"}).rename(columns={"openInterest":"gex"}).reset_index()

class WhaleDetector:
    def scan(self, ticker, chain, spot):
        return chain[chain["premium"] > 500000].copy()

class ContractIntelligence:
    def max_pain(self, chain, spot): return spot
    def summarize(self, chain, spot): return chain.head()

class PortfolioAnalyzer:
    def analyze(self, pos): return pd.DataFrame()

def portfolio_summary(df): return {}
