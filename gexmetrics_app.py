
"""
GexMetrics — Institutional-Grade Options Intelligence Dashboard
============================================================
Tab 1: GEX/VEX Heatmap
Tab 2: Whale Flow Detector ($500K+)
Tab 3: Contract Intelligence
Tab 4: Portfolio Greeks
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import yfinance as yf
from datetime import datetime
import time

from gexmetrics_scanner import (
    OptionsChainFetcher, GEXCalculator, WhaleDetector,
    ContractIntelligence, PortfolioAnalyzer, portfolio_summary,
    INDICES, MAG7, ALL, days_to_expiry, bs_greeks
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GexMetrics — Options Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=JetBrains+Mono:wght@300;400;600&display=swap');

html, body, [class*="css"] {
  font-family: 'Syne', sans-serif;
  background: #06080f;
  color: #d4dce8;
}
section[data-testid="stSidebar"] {
  background: #090c14;
  border-right: 1px solid #1a2030;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div { color: #e0e8f0 !important; font-size: 0.85rem; }

[data-testid="metric-container"] {
  background: #0e1520;
  border: 1px solid #1a2535;
  border-radius: 10px;
  padding: 16px 20px;
}
[data-testid="metric-container"] label { color: #4a5a70 !important; font-size: 0.7rem; letter-spacing:.1em; text-transform:uppercase; }
[data-testid="metric-container"] [data-testid="stMetricValue"] {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.6rem; font-weight: 600; color: #bc8cff;
}

.stTabs [data-baseweb="tab-list"] { background: #090c14; border-bottom: 1px solid #1a2030; }
.stTabs [data-baseweb="tab"] { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #5a6a80; padding: 10px 20px; }
.stTabs [aria-selected="true"] { background: #131922 !important; color: #bc8cff !important; border-bottom: 2px solid #bc8cff !important; }

.stButton > button {
  font-family: 'JetBrains Mono', monospace; font-size: 0.82rem;
  border-radius: 6px; padding: 10px 0; width: 100%; border: none;
  background: linear-gradient(135deg, #3a1a6b, #1a0d4a); color: #bc8cff;
}
.stButton > button:hover { background: linear-gradient(135deg, #4a2a80, #250f60); }

.whale-call { border-left: 3px solid #4af0c4; background: #0a1f18; padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 4px 0; }
.whale-put  { border-left: 3px solid #f04a6a; background: #1f0a10; padding: 12px 16px; border-radius: 0 8px 8px 0; margin: 4px 0; }
.gex-metrics-card { background: #0e1520; border: 1px solid #2a1a4a; border-radius: 8px; padding: 16px; margin: 6px 0; }

hr { border-color: #1a2030; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

for k, v in {
    "gex_data":        {},
    "whale_data":      pd.DataFrame(),
    "chain_data":      {},
    "portfolio_df":    pd.DataFrame(),
    "last_scan":       None,
    "positions":       [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📊 GexMetrics")
    st.markdown("*Institutional Options Intelligence*")
    st.markdown("---")

    st.markdown("### 🎯 Ticker Selection")
    selected_indices = st.multiselect("Indices", INDICES, default=INDICES)
    selected_mag7    = st.multiselect("Mag7", MAG7, default=MAG7)
    all_tickers      = selected_indices + selected_mag7

    st.markdown("### ⚙️ Settings")
    whale_threshold = st.number_input("Whale threshold ($)", value=500_000, step=100_000)
    max_expiries    = st.slider("Expiries to scan", 1, 6, 3)

    st.markdown("---")
    scan_btn = st.button("📊 Run GexMetrics Scan")

    if st.session_state.last_scan:
        st.caption(f"Last scan: {st.session_state.last_scan}")

    st.markdown("""
    <div style='margin-top:16px;font-size:0.72rem;color:#6a5a90;line-height:1.8;'>
    <b style='color:#bc8cff'>GEX</b> — Gamma Exposure by strike<br>
    <b style='color:#bc8cff'>VEX</b> — Vanna Exposure by strike<br>
    <b style='color:#bc8cff'>Whale</b> — $500K+ premium trades<br>
    <b style='color:#bc8cff'>Greeks</b> — Black-Scholes calculated<br><br>
    <i style='color:#3a2a50'>Data: yfinance EOD · Approx. GEX<br>Not financial advice</i>
    </div>""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div style='padding:8px 0 16px 0;'>
  <h1 style='font-family:"Syne",sans-serif;font-size:2.2rem;font-weight:800;
             background:linear-gradient(90deg,#bc8cff,#6a5aff,#4af0c4);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;
             margin:0;letter-spacing:-0.02em;'>📊 GexMetrics</h1>
  <p style='color:#5a3a80;font-family:"JetBrains Mono",monospace;font-size:0.78rem;margin:4px 0 0 0;'>
    Institutional Options Intelligence · GEX/VEX · Whale Flow · Contract Analytics · Portfolio Greeks
  </p>
</div>""", unsafe_allow_html=True)

# ── Run scan ──────────────────────────────────────────────────────────────────

def run_gexmetrics_scan(tickers, max_exp, whale_thresh):
    gex_data   = {}
    whale_rows = []
    chain_data = {}
    gex_calc   = GEXCalculator()
    whale_det  = WhaleDetector()
    ci         = ContractIntelligence()
    total      = len(tickers)

    with st.status("📊 Running GexMetrics scan...", expanded=True) as status:
        pb  = st.progress(0)
        stx = st.empty()

        for idx, ticker in enumerate(tickers, 1):
            pb.progress(idx / total)
            stx.markdown(f"`[{idx}/{total}]` scanning **{ticker}**...")

            fetcher = OptionsChainFetcher(ticker)
            chain   = fetcher.get_chain(max_expiries=max_exp)
            spot    = fetcher.spot

            if chain.empty or spot == 0:
                continue

            # GEX/VEX
            gex = gex_calc.calculate(chain, spot)
            gex_data[ticker] = {"gex": gex, "spot": spot, "chain": chain}

            # Whale detection
            whales = whale_det.scan(ticker, chain, spot)
            whales = whales[whales["Premium ($)"].apply(
                lambda x: float(x.replace("$","").replace(",","")) >= whale_thresh
            )] if not whales.empty else whales
            if not whales.empty:
                whale_rows.append(whales)

            # Contract intelligence
            chain_data[ticker] = {"ci": ci.summarize(chain, spot),
                                   "max_pain": ci.max_pain(chain, spot),
                                   "spot": spot, "chain": chain}

        pb.empty(); stx.empty()
        status.update(label="✅ GexMetrics scan complete!", state="complete")

    st.session_state.gex_data   = gex_data
    st.session_state.whale_data = pd.concat(whale_rows, ignore_index=True) if whale_rows else pd.DataFrame()
    st.session_state.chain_data = chain_data
    st.session_state.last_scan  = datetime.now().strftime("%H:%M:%S")

if scan_btn:
    run_gexmetrics_scan(all_tickers, max_expiries, whale_threshold)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 GEX / VEX Heatmap",
    "🐋 Whale Flow",
    "📋 Contract Intelligence",
    "💼 Portfolio Greeks",
])

# ════════════════════════════════════════════════
#  TAB 1 — GEX / VEX
# ════════════════════════════════════════════════
with tab1:
    st.markdown("""
    <div style='background:#0e1520;border:1px solid #2a1a4a;border-radius:8px;
                padding:12px 16px;margin-bottom:16px;font-family:"JetBrains Mono",monospace;font-size:0.75rem;color:#8090a0;'>
    📊 <b style='color:#bc8cff'>Gamma Exposure (GEX)</b> — Positive = dealers long gamma (stabilizing) · Negative = dealers short gamma (amplifying moves)<br>
    🔮 <b style='color:#bc8cff'>Key levels</b> — Large positive GEX strikes act as resistance · Large negative GEX = volatility acceleration zones
    </div>""", unsafe_allow_html=True)

    if not st.session_state.gex_data:
        st.markdown("""
        <div style='text-align:center;padding:60px 0;color:#2a1a4a;'>
          <div style='font-size:3rem;'>📊</div>
          <div style='font-family:"JetBrains Mono",monospace;color:#5a3a80;margin-top:12px;'>
            Run GexMetrics Scan to see GEX/VEX maps
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        sel_ticker = st.selectbox("Select ticker", list(st.session_state.gex_data.keys()), key="gex_sel")

        if sel_ticker and sel_ticker in st.session_state.gex_data:
            data  = st.session_state.gex_data[sel_ticker]
            gex   = data["gex"]
            spot  = data["spot"]

            if not gex.empty:
                # Filter to ±15% from spot
                gex_filtered = gex[abs(gex["strike"] - spot) / spot <= 0.15]

                col1, col2 = st.columns(2)

                # GEX Chart
                with col1:
                    st.markdown("#### 📊 Gamma Exposure (GEX)")
                    colors = ["#4af0c4" if v >= 0 else "#f04a6a" for v in gex_filtered["net_gex"]]
                    fig_gex = go.Figure(go.Bar(
                        x=gex_filtered["net_gex"],
                        y=gex_filtered["strike"],
                        orientation="h",
                        marker_color=colors,
                        name="GEX"
                    ))
                    fig_gex.add_hline(y=spot, line=dict(color="#f5c842", width=2, dash="dash"),
                                      annotation_text=f"Spot ${spot:.2f}",
                                      annotation_font_color="#f5c842")
                    fig_gex.update_layout(
                        template="plotly_dark", paper_bgcolor="#0e1520", plot_bgcolor="#0e1520",
                        height=500, margin=dict(l=8,r=8,t=24,b=8),
                        xaxis_title="GEX ($)", yaxis_title="Strike",
                        font=dict(family="JetBrains Mono", color="#8090a0")
                    )
                    st.plotly_chart(fig_gex, use_container_width=True)

                # VEX Chart
                with col2:
                    st.markdown("#### 🔮 Vanna Exposure (VEX)")
                    vex_colors = ["#bc8cff" if v >= 0 else "#f04a6a" for v in gex_filtered["vex"]]
                    fig_vex = go.Figure(go.Bar(
                        x=gex_filtered["vex"],
                        y=gex_filtered["strike"],
                        orientation="h",
                        marker_color=vex_colors,
                        name="VEX"
                    ))
                    fig_vex.add_hline(y=spot, line=dict(color="#f5c842", width=2, dash="dash"),
                                      annotation_text=f"Spot ${spot:.2f}",
                                      annotation_font_color="#f5c842")
                    fig_vex.update_layout(
                        template="plotly_dark", paper_bgcolor="#0e1520", plot_bgcolor="#0e1520",
                        height=500, margin=dict(l=8,r=8,t=24,b=8),
                        xaxis_title="VEX", yaxis_title="Strike",
                        font=dict(family="JetBrains Mono", color="#8090a0")
                    )
                    st.plotly_chart(fig_vex, use_container_width=True)

                # Key levels
                total_gex = gex_filtered["net_gex"].sum()
                max_pos   = gex_filtered.loc[gex_filtered["net_gex"].idxmax(), "strike"] if not gex_filtered.empty else spot
                max_neg   = gex_filtered.loc[gex_filtered["net_gex"].idxmin(), "strike"] if not gex_filtered.empty else spot

                st.markdown("---")
                m1,m2,m3,m4 = st.columns(4)
                m1.metric("Spot Price",      f"${spot:.2f}")
                m2.metric("Total Net GEX",   f"${total_gex:,.0f}")
                m3.metric("Max Support",     f"${max_pos:.2f}")
                m4.metric("Max Resistance",  f"${max_neg:.2f}")

                st.markdown(f"""
                <div style='background:#0e1520;border:1px solid #2a1a4a;border-radius:8px;padding:14px;margin-top:8px;font-family:"JetBrains Mono",monospace;font-size:0.78rem;'>
                  <b style='color:#bc8cff;'>{sel_ticker} GEX Analysis</b><br><br>
                  {"🟢 Positive net GEX — dealers are long gamma. Market makers will buy dips and sell rips, creating a <b>pinning effect</b> near high-GEX strikes." if total_gex > 0
                   else "🔴 Negative net GEX — dealers are short gamma. Market makers amplify moves, creating <b>volatility expansion</b> conditions."}
                  <br><br>
                  <span style='color:#8090a0;'>Key support zone: <b style='color:#4af0c4;'>${max_pos:.2f}</b> · Key resistance zone: <b style='color:#f04a6a;'>${max_neg:.2f}</b></span>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════
#  TAB 2 — WHALE FLOW
# ════════════════════════════════════════════════
with tab2:
    st.markdown("""
    <div style='background:#0e1520;border:1px solid #2a1a4a;border-radius:8px;
                padding:12px 16px;margin-bottom:16px;font-family:"JetBrains Mono",monospace;font-size:0.75rem;color:#8090a0;'>
    🐋 <b style='color:#bc8cff'>Whale Flow</b> — Options trades with $500K+ premium · High Vol/OI = fresh positioning (SWEEP) · Lower = rolling/hedging (BLOCK)
    </div>""", unsafe_allow_html=True)

    if st.session_state.whale_data.empty:
        st.markdown("""
        <div style='text-align:center;padding:60px 0;color:#2a1a4a;'>
          <div style='font-size:3rem;'>🐋</div>
          <div style='font-family:"JetBrains Mono",monospace;color:#5a3a80;margin-top:12px;'>
            Run GexMetrics Scan to detect whale activity
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        df = st.session_state.whale_data
        calls_w = df[df["Type"]=="CALL"] if "Type" in df.columns else pd.DataFrame()
        puts_w  = df[df["Type"]=="PUT"]  if "Type" in df.columns else pd.DataFrame()

        c1,c2,c3 = st.columns(3)
        c1.metric("Total Whale Trades", len(df))
        c2.metric("🟢 Bullish (Calls)", len(calls_w))
        c3.metric("🔴 Bearish (Puts)",  len(puts_w))

        st.markdown("---")

        col_c, col_p = st.columns(2)
        with col_c:
            st.markdown("### 🟢 Bullish Whale Trades")
            if calls_w.empty:
                st.caption("No bullish whale trades detected")
            for _, r in calls_w.iterrows():
                st.markdown(f"""
                <div class="whale-call">
                  <div style='display:flex;align-items:center;gap:8px;margin-bottom:5px;'>
                    <span style='font-family:"JetBrains Mono",monospace;font-size:1rem;font-weight:700;color:#e0e8f0;'>{r.get("Ticker","")}</span>
                    <span style='background:#0d3d28;color:#4af0c4;font-size:0.7rem;font-weight:700;padding:2px 8px;border-radius:10px;'>▲ CALL</span>
                    <span style='color:#f5c842;font-size:0.8rem;font-weight:700;'>{r.get("trade_type","")}</span>
                    <span style='margin-left:auto;color:#4af0c4;font-weight:700;'>{r.get("Premium ($)","")}</span>
                  </div>
                  <div style='font-size:0.78rem;color:#a0b0c0;'>
                    Strike ${r.get("Strike","")} · {r.get("Expiry","")} · IV {r.get("IV","")}
                  </div>
                  <div style='font-size:0.72rem;color:#5a7a90;'>
                    Vol: {r.get("Volume",""):,} · OI: {r.get("OI",""):,} · Vol/OI: {r.get("Vol/OI","")}x
                  </div>
                </div>""", unsafe_allow_html=True)

        with col_p:
            st.markdown("### 🔴 Bearish Whale Trades")
            if puts_w.empty:
                st.caption("No bearish whale trades detected")
            for _, r in puts_w.iterrows():
                st.markdown(f"""
                <div class="whale-put">
                  <div style='display:flex;align-items:center;gap:8px;margin-bottom:5px;'>
                    <span style='font-family:"JetBrains Mono",monospace;font-size:1rem;font-weight:700;color:#e0e8f0;'>{r.get("Ticker","")}</span>
                    <span style='background:#3d0d1a;color:#f04a6a;font-size:0.7rem;font-weight:700;padding:2px 8px;border-radius:10px;'>▼ PUT</span>
                    <span style='color:#f5c842;font-size:0.8rem;font-weight:700;'>{r.get("trade_type","")}</span>
                    <span style='margin-left:auto;color:#f04a6a;font-weight:700;'>{r.get("Premium ($)","")}</span>
                  </div>
                  <div style='font-size:0.78rem;color:#a0b0c0;'>
                    Strike ${r.get("Strike","")} · {r.get("Expiry","")} · IV {r.get("IV","")}
                  </div>
                  <div style='font-size:0.72rem;color:#5a7a90;'>
                    Vol: {r.get("Volume",""):,} · OI: {r.get("OI",""):,} · Vol/OI: {r.get("Vol/OI","")}x
                  </div>
                </div>""", unsafe_allow_html=True)

        # Full table
        st.markdown("---")
        st.markdown("### 📋 Full Whale Activity Table")
        st.dataframe(df, use_container_width=True)


# ════════════════════════════════════════════════
#  TAB 3 — CONTRACT INTELLIGENCE
# ════════════════════════════════════════════════
with tab3:
    if not st.session_state.chain_data:
        st.markdown("""
        <div style='text-align:center;padding:60px 0;color:#2a1a4a;'>
          <div style='font-size:3rem;'>📋</div>
          <div style='font-family:"JetBrains Mono",monospace;color:#5a3a80;margin-top:12px;'>
            Run GexMetrics Scan to see contract intelligence
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        sel = st.selectbox("Select ticker", list(st.session_state.chain_data.keys()), key="ci_sel")

        if sel and sel in st.session_state.chain_data:
            data      = st.session_state.chain_data[sel]
            ci_df     = data["ci"]
            max_pain  = data["max_pain"]
            spot      = data["spot"]
            chain     = data["chain"]

            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Spot",       f"${spot:.2f}")
            m2.metric("Max Pain",   f"${max_pain:.2f}")
            m3.metric("Distance",   f"{((max_pain-spot)/spot*100):+.1f}%")

            # Overall PCR
            total_call_oi = chain[chain["option_type"]=="call"]["openInterest"].sum()
            total_put_oi  = chain[chain["option_type"]=="put"]["openInterest"].sum()
            pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0
            m4.metric("Put/Call Ratio", f"{pcr:.2f}")

            st.markdown("---")

            # OI by strike chart
            if not ci_df.empty:
                st.markdown("### 📊 Open Interest by Strike")
                fig_oi = go.Figure()
                if "C_OI" in ci_df.columns:
                    fig_oi.add_trace(go.Bar(
                        x=ci_df["Strike"], y=ci_df["C_OI"],
                        name="Call OI", marker_color="rgba(74,240,196,0.7)"
                    ))
                if "P_OI" in ci_df.columns:
                    fig_oi.add_trace(go.Bar(
                        x=ci_df["Strike"], y=-ci_df["P_OI"].fillna(0),
                        name="Put OI", marker_color="rgba(240,74,106,0.7)"
                    ))
                fig_oi.add_vline(x=spot, line=dict(color="#f5c842", width=2, dash="dash"),
                                  annotation_text=f"Spot ${spot:.2f}")
                fig_oi.add_vline(x=max_pain, line=dict(color="#bc8cff", width=2, dash="dot"),
                                  annotation_text=f"Max Pain ${max_pain:.2f}",
                                  annotation_font_color="#bc8cff")
                fig_oi.update_layout(
                    template="plotly_dark", paper_bgcolor="#0e1520", plot_bgcolor="#0e1520",
                    barmode="overlay", height=400,
                    margin=dict(l=8,r=8,t=24,b=8),
                    font=dict(family="JetBrains Mono", color="#8090a0"),
                    legend=dict(bgcolor="rgba(0,0,0,0)")
                )
                st.plotly_chart(fig_oi, use_container_width=True)

            # IV Skew
            st.markdown("### 📈 IV Skew")
            call_iv = chain[chain["option_type"]=="call"][["strike","impliedVolatility"]].dropna()
            put_iv  = chain[chain["option_type"]=="put"] [["strike","impliedVolatility"]].dropna()
            if not call_iv.empty or not put_iv.empty:
                fig_iv = go.Figure()
                if not call_iv.empty:
                    fig_iv.add_trace(go.Scatter(x=call_iv["strike"],
                                                 y=call_iv["impliedVolatility"]*100,
                                                 name="Call IV", line=dict(color="#4af0c4", width=2)))
                if not put_iv.empty:
                    fig_iv.add_trace(go.Scatter(x=put_iv["strike"],
                                                 y=put_iv["impliedVolatility"]*100,
                                                 name="Put IV", line=dict(color="#f04a6a", width=2)))
                fig_iv.add_vline(x=spot, line=dict(color="#f5c842", width=1, dash="dash"))
                fig_iv.update_layout(
                    template="plotly_dark", paper_bgcolor="#0e1520", plot_bgcolor="#0e1520",
                    height=300, margin=dict(l=8,r=8,t=24,b=8),
                    yaxis_title="IV %", xaxis_title="Strike",
                    font=dict(family="JetBrains Mono", color="#8090a0")
                )
                st.plotly_chart(fig_iv, use_container_width=True)

            # Contract table
            st.markdown("### 📋 Strike-Level Data")
            if not ci_df.empty:
                near = ci_df[abs(ci_df["Strike"] - spot) / spot <= 0.05]
                st.caption(f"Showing strikes within 5% of spot ${spot:.2f}")
                st.dataframe(near.style.format({
                    "Strike": "${:.2f}", "C_Mid": "${:.2f}", "P_Mid": "${:.2f}",
                    "C_OI": "{:,.0f}", "P_OI": "{:,.0f}",
                    "C_Vol": "{:,.0f}", "P_Vol": "{:,.0f}",
                    "PCR": "{:.2f}",
                }), use_container_width=True)


# ════════════════════════════════════════════════
#  TAB 4 — PORTFOLIO GREEKS
# ════════════════════════════════════════════════
with tab4:
    st.markdown("""
    <div style='background:#0e1520;border:1px solid #2a1a4a;border-radius:8px;
                padding:12px 16px;margin-bottom:16px;font-family:"JetBrains Mono",monospace;font-size:0.75rem;color:#8090a0;'>
    💼 <b style='color:#bc8cff'>Portfolio Greeks</b> — Enter your positions to see aggregate Delta, Gamma, Theta, Vega exposure.
    Greeks are calculated using Black-Scholes with live IV from yfinance.
    </div>""", unsafe_allow_html=True)

    st.markdown("### ➕ Add Position")

    with st.form("add_position"):
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1: pticker    = st.text_input("Ticker", "SPY")
        with c2: ptype      = st.selectbox("Type", ["call","put"])
        with c3: pstrike    = st.number_input("Strike", value=500.0, step=1.0)
        with c4: pexpiry    = st.text_input("Expiry (YYYY-MM-DD)", "2025-05-16")
        with c5: pcontracts = st.number_input("Contracts", value=1, min_value=1)
        with c6: pdirection = st.selectbox("Direction", ["long","short"])

        submitted = st.form_submit_button("Add Position")
        if submitted:
            st.session_state.positions.append({
                "ticker":    pticker.upper().strip(),
                "type":      ptype,
                "strike":    pstrike,
                "expiry":    pexpiry,
                "contracts": pcontracts,
                "direction": pdirection,
            })
            st.success(f"Added {pdirection} {pcontracts}x {pticker} ${pstrike} {ptype} {pexpiry}")

    if st.session_state.positions:
        col_pos, col_clear = st.columns([4,1])
        with col_clear:
            if st.button("🗑️ Clear All"):
                st.session_state.positions = []
                st.session_state.portfolio_df = pd.DataFrame()
                st.rerun()

        st.markdown("### 📋 Current Positions")
        pos_df = pd.DataFrame(st.session_state.positions)
        st.dataframe(pos_df, use_container_width=True)

        if st.button("📊 Calculate Greeks"):
            with st.spinner("Calculating portfolio Greeks..."):
                analyzer = PortfolioAnalyzer()
                port_df  = analyzer.analyze(st.session_state.positions)
                st.session_state.portfolio_df = port_df

    if not st.session_state.portfolio_df.empty:
        df  = st.session_state.portfolio_df
        summ= portfolio_summary(df)

        st.markdown("### 📊 Greeks Summary")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Net Delta",  summ.get("Total Delta","—"),
                  help="$1 move in underlying = Delta change in portfolio value")
        c2.metric("Net Gamma",  summ.get("Total Gamma","—"),
                  help="Rate of Delta change per $1 move")
        c3.metric("Net Theta",  summ.get("Total Theta","—"),
                  help="Daily time decay in $ terms")
        c4.metric("Net Vega",   summ.get("Total Vega","—"),
                  help="P&L change per 1% IV move")

        # Delta interpretation
        delta = summ.get("Total Delta", 0)
        if abs(delta) > 0:
            bias = "🟢 Net long delta — profitable if market rises" if delta > 0 else "🔴 Net short delta — profitable if market falls"
            st.markdown(f"""
            <div style='background:#0e1520;border:1px solid #2a1a4a;border-radius:8px;
                        padding:14px;margin:8px 0;font-family:"JetBrains Mono",monospace;font-size:0.78rem;'>
              {bias}<br>
              <span style='color:#8090a0;'>
              Theta of {summ.get("Total Theta","—")} means you {"lose" if summ.get("Total Theta",0) < 0 else "gain"}
              ${abs(summ.get("Total Theta",0)):.2f}/day from time decay.<br>
              Vega of {summ.get("Total Vega","—")} means a 1% IV increase {"adds" if summ.get("Total Vega",0) > 0 else "costs"}
              ${abs(summ.get("Total Vega",0)):.2f} to your portfolio.
              </span>
            </div>""", unsafe_allow_html=True)

        st.markdown("### 📋 Position-Level Greeks")
        st.dataframe(df.style.format({
            "Strike": "${:.2f}", "Spot": "${:.2f}",
            "Delta": "{:.2f}", "Gamma": "{:.4f}",
            "Theta": "{:.2f}", "Vega": "{:.2f}",
        }), use_container_width=True)
    else:
        if not st.session_state.positions:
            st.markdown("""
            <div style='text-align:center;padding:60px 0;color:#2a1a4a;'>
              <div style='font-size:3rem;'>💼</div>
              <div style='font-family:"JetBrains Mono",monospace;color:#5a3a80;margin-top:12px;'>
                Add positions above then click Calculate Greeks
              </div>
            </div>""", unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style='text-align:center;font-family:"JetBrains Mono",monospace;font-size:0.68rem;color:#1a0a30;'>
  GexMetrics · yfinance EOD data · GEX approximated from OI + Black-Scholes · Not financial advice
</div>""", unsafe_allow_html=True)
