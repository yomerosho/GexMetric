"""
GexMetrics — Daily Market Outlook Dashboard
============================================
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
import time

# Attempt to import from your scanner file
try:
    from gexmetrics_scanner import (
        AlpacaOptionsClient, GEXCalculator, WhaleDetector, WhaleMagnetDetector,
        MacroFetcher, DailyOutlook,
        INDICES, MAG7
    )
except ImportError:
    st.error("Error: gexmetrics_scanner.py not found in the same directory.")
    st.stop()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GexMetrics — Daily Outlook",
    page_icon="🔮",
    layout="wide",
)

# ── Secrets loader ────────────────────────────────────────────────────────────
ALPACA_KEY    = st.secrets.get("alpaca", {}).get("key", "")
ALPACA_SECRET = st.secrets.get("alpaca", {}).get("secret", "")

# ── Session state ─────────────────────────────────────────────────────────────
if "outlook" not in st.session_state:
    st.session_state.outlook = None

# ── Helper: Build HTML for Dashboard ──────────────────────────────────────────
def build_outlook_html(report):
    """Build a formatted HTML string for the tickers."""
    tickers = report.get("tickers", {})
    tickers_html = ""

    for ticker, data in tickers.items():
        spot   = data["spot"]
        bias   = data["bias"]
        whales = data["whales"]
        magnets = data.get("magnets", [])

        # Magnetic levels
        magnets_html = ""
        for m in magnets:
            dist_lbl = f"{m.get('distance_pct', 0):+.2f}%"
            magnets_html += f"""
            <div style='font-family:monospace;font-size:0.85rem;padding:8px;background:#131922;border-left:3px solid #bc8cff;margin:5px 0;border-radius:4px;'>
                🧲 <b style='color:#bc8cff;'>${m["strike"]:.0f}</b> 
                <span style='color:#4af0c4;'>({dist_lbl})</span> · OI: {int(m.get("total_oi",0)):,}
            </div>"""

        # Whale flow
        whale_html = ""
        for w in whales[:3]:
            wcol = "#4af0c4" if w.get("option_type") == "call" else "#f04a6a"
            whale_html += f"""
            <div style='font-family:monospace;font-size:0.8rem;color:#a0b0c0;padding:4px 0;border-bottom:1px solid #1a2535;'>
                <b style='color:{wcol};'>{w.get("option_type", "N/A").upper()}</b> ${w.get("strike", 0):.0f} · 
                ${w.get("premium", 0):,.0f} · {w.get("trade_type", "FLOW")}
            </div>"""

        tickers_html += f"""
        <div style='background:#0e1520;border:1px solid #1a2535;border-radius:12px;padding:20px;margin-bottom:20px;'>
          <div style='display:flex;justify-content:space-between;margin-bottom:15px;'>
            <span style='font-size:1.5rem;font-weight:800;color:#bc8cff;'>{ticker}</span>
            <span style='font-family:monospace;font-size:1.1rem;color:#e0e8f0;'>${spot:.2f}</span>
            <span style='color:{bias["color"]};font-weight:700;'>{bias["direction"]}</span>
          </div>
          <div style='color:#5a7a90;font-size:0.75rem;margin-bottom:5px;'>MAGNETIC STRIKES</div>
          {magnets_html}
          <div style='color:#5a7a90;font-size:0.75rem;margin-top:15px;margin-bottom:5px;'>WHALE FLOW</div>
          {whale_html}
        </div>"""

    return f"<div style='color:#d4dce8;'>{tickers_html}</div>"

# ── Main UI ───────────────────────────────────────────────────────────────────
st.title("🔮 GexMetrics Daily Outlook")

with st.sidebar:
    st.markdown("### ⚙️ Controls")
    gen_btn = st.button("🔮 Generate Outlook", type="primary")
    if not ALPACA_KEY:
        st.error("Alpaca Key missing in Secrets!")

if gen_btn:
    with st.spinner("Analyzing market positioning via Alpaca..."):
        try:
            engine = DailyOutlook(ALPACA_KEY, ALPACA_SECRET)
            report = engine.generate(indices=INDICES, mag7=MAG7)
            st.session_state.outlook = report
        except Exception as e:
            st.error(f"Scan failed: {e}")

# Rendering logic
if st.session_state.outlook:
    st.markdown(build_outlook_html(st.session_state.outlook), unsafe_allow_html=True)
else:
    # This prevents the "Blank Screen"
    st.info("👋 Welcome to GexMetrics. Click 'Generate Outlook' in the sidebar to fetch live dealer positioning and whale flows.")
