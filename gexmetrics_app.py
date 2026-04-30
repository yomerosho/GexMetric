import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import yfinance as yf
from datetime import datetime

from gexmetrics_scanner import (
    OptionsChainFetcher, GEXCalculator, WhaleDetector,
    ContractIntelligence, PortfolioAnalyzer, portfolio_summary,
    INDICES, MAG7, WATCHLIST, ALL, days_to_expiry, bs_greeks
)

st.set_page_config(page_title="GexMetrics", page_icon="📊", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=JetBrains+Mono:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'Syne', sans-serif; background: #06080f; color: #d4dce8; }
.stButton > button { background: linear-gradient(135deg, #3a1a6b, #1a0d4a); color: #bc8cff; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("📊 GexMetrics")
    selected_indices = st.multiselect("Indices", INDICES, default=INDICES)
    selected_watchlist = st.multiselect("Watchlist", WATCHLIST, default=WATCHLIST)
    all_tickers = list(set(selected_indices + selected_watchlist))
    whale_threshold = st.number_input("Whale threshold ($)", value=500000)
    max_expiries = st.slider("Expiries to scan", 1, 6, 3)
    scan_btn = st.button("📊 Run GexMetrics Scan")

st.title("📊 GexMetrics Options Intelligence")

if scan_btn:
    gex_data, whale_rows, chain_data = {}, [], {}
    gex_calc, whale_det, ci = GEXCalculator(), WhaleDetector(), ContractIntelligence()
    with st.status("Scanning...", expanded=True) as status:
        for ticker in all_tickers:
            fetcher = OptionsChainFetcher(ticker)
            chain = fetcher.get_chain(max_expiries=max_expiries)
            if not chain.empty:
                gex_data[ticker] = {"gex": gex_calc.calculate(chain, fetcher.spot), "spot": fetcher.spot}
                whales = whale_det.scan(ticker, chain, fetcher.spot)
                if not whales.empty: whale_rows.append(whales)
                chain_data[ticker] = {"ci": ci.summarize(chain, fetcher.spot), "max_pain": ci.max_pain(chain, fetcher.spot)}
        status.update(label="Complete!", state="complete")
    st.session_state.gex_data = gex_data
    st.session_state.whale_data = pd.concat(whale_rows) if whale_rows else pd.DataFrame()
    st.session_state.chain_data = chain_data

tab1, tab2, tab3, tab4 = st.tabs(["GEX/VEX", "Whale Flow", "Contract Intel", "Portfolio"])

with tab1:
    if "gex_data" in st.session_state:
        ticker = st.selectbox("Ticker", list(st.session_state.gex_data.keys()))
        data = st.session_state.gex_data[ticker]
        st.write(f"Spot: ${data['spot']:.2f}")
        st.bar_chart(data['gex'].set_index('strike'))

with tab2:
    if "whale_data" in st.session_state:
        st.dataframe(st.session_state.whale_data)

with tab3:
    if "chain_data" in st.session_state:
        ticker = st.selectbox("Ticker ", list(st.session_state.chain_data.keys()))
        st.write(f"Max Pain: ${st.session_state.chain_data[ticker]['max_pain']:.2f}")

with tab4:
    st.write("Portfolio Tracker")