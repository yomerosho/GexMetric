"""
GexMetrics — Daily Market Outlook Dashboard
============================================
Tab 1: 🔮 Daily Outlook (the main feature)
Tab 2: 📊 GEX/VEX Deep Dive (power user reference)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import yfinance as yf
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import time

from gexmetrics_scanner import (
    OptionsChainFetcher, GEXCalculator, WhaleDetector,
    MacroFetcher, EarningsCalendar, DailyOutlook,
    INDICES, MAG7, WATCHLIST, ALL,
)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GexMetrics — Daily Outlook",
    page_icon="🔮",
    layout="wide",
)

# ── Secrets loader ────────────────────────────────────────────────────────────

def get_secret(section, key, default=""):
    try:    return st.secrets[section][key]
    except: return default

GMAIL_USER = get_secret("gmail", "user", "")
GMAIL_PASS = get_secret("gmail", "password", "")

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=JetBrains+Mono:wght@300;400;600&display=swap');
html, body, [class*="css"] { font-family: 'Syne', sans-serif; background: #06080f; color: #d4dce8; }
section[data-testid="stSidebar"] { background: #090c14; border-right: 1px solid #1a2030; }
section[data-testid="stSidebar"] * { color: #e0e8f0 !important; }
.stTabs [data-baseweb="tab-list"] { background: #090c14; border-bottom: 1px solid #1a2030; }
.stTabs [data-baseweb="tab"] { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; padding: 12px 24px; color: #5a6a80; }
.stTabs [aria-selected="true"] { background: #131922 !important; color: #bc8cff !important; border-bottom: 2px solid #bc8cff !important; }
.stButton > button {
  background: linear-gradient(135deg, #3a1a6b, #1a0d4a);
  color: #bc8cff; border: none; border-radius: 6px;
  padding: 10px 20px; font-family: 'JetBrains Mono', monospace;
}
.stButton > button:hover { background: linear-gradient(135deg, #4a2a80, #2a0f60); }

.outlook-header {
  background: linear-gradient(90deg, #0a0518, #1a0d3a);
  border: 1px solid #2a1a4a;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 20px;
}

.outlook-section {
  background: #0e1520;
  border: 1px solid #1a2535;
  border-radius: 10px;
  padding: 20px 24px;
  margin: 12px 0;
}

.macro-pill {
  display: inline-block;
  background: #131922;
  border: 1px solid #2a3a4a;
  border-radius: 8px;
  padding: 6px 12px;
  margin: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
}

.bias-badge {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 20px;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 0.85rem;
}

.level-pill {
  display: inline-block;
  background: #131922;
  border-radius: 6px;
  padding: 4px 10px;
  margin: 3px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  color: #d4dce8;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

for k, v in {
    "outlook":   None,
    "gex_data":  {},
    "last_run":  None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helper: Build HTML email ──────────────────────────────────────────────────

def build_outlook_html(report):
    """Build a formatted HTML report from the outlook data."""

    macro    = report.get("macro", {})
    earnings = report.get("earnings", [])
    tickers  = report.get("tickers", {})

    # Macro pills
    macro_html = ""
    for label, data in macro.items():
        col = "#4af0c4" if data["trend"] == "down" and label == "VIX" else \
              "#4af0c4" if data["trend"] == "up" and label != "VIX" else \
              "#f04a6a" if data["trend"] == "up" and label == "VIX" else \
              "#f04a6a" if data["trend"] == "down" and label != "VIX" else "#8090a0"
        arrow = "▲" if data["trend"] == "up" else ("▼" if data["trend"] == "down" else "◆")
        macro_html += f"""<span style='display:inline-block;background:#131922;border:1px solid #2a3a4a;border-radius:8px;padding:6px 12px;margin:4px;font-family:monospace;font-size:0.78rem;'>
            <b style='color:#a0b0c0;'>{label}:</b>
            <span style='color:#e0e8f0;'>{data["value"]}</span>
            <span style='color:{col};'>{arrow} {data["pct"]:+.2f}%</span>
        </span>"""

    # Earnings
    earnings_html = ""
    if earnings:
        for e in earnings[:10]:
            day_lbl = "TODAY" if e["days"] == 0 else f"in {e['days']}d"
            earnings_html += f"""<div style='font-family:monospace;font-size:0.78rem;color:#a0b0c0;padding:4px 0;'>
                📊 <b style='color:#bc8cff;'>{e["ticker"]}</b> · {e["weekday"]}, {e["date"]}
                <span style='color:#5a7a90;'>({day_lbl})</span>
            </div>"""
    else:
        earnings_html = "<div style='color:#5a7a90;font-size:0.78rem;'>No Mag7 earnings in next 14 days.</div>"

    # Per-ticker sections
    tickers_html = ""
    for ticker, data in tickers.items():
        spot     = data["spot"]
        levels   = data["levels"]
        bias     = data["bias"]
        whales   = data["whales"]

        res_html = " ".join([f"<span style='background:#1f0a10;color:#f04a6a;border-radius:6px;padding:3px 8px;margin:2px;font-family:monospace;font-size:0.75rem;'>${l:.2f}</span>"
                             for l in levels.get("resistance", [])]) or "<span style='color:#5a7a90;'>—</span>"
        sup_html = " ".join([f"<span style='background:#0a1f18;color:#4af0c4;border-radius:6px;padding:3px 8px;margin:2px;font-family:monospace;font-size:0.75rem;'>${l:.2f}</span>"
                             for l in levels.get("support", [])]) or "<span style='color:#5a7a90;'>—</span>"

        # Top 3 whales
        whale_html = ""
        for w in whales[:3]:
            wcol  = "#4af0c4" if w["option_type"] == "call" else "#f04a6a"
            wicon = "🟢" if w["option_type"] == "call" else "🔴"
            whale_html += f"""<div style='font-family:monospace;font-size:0.74rem;color:#a0b0c0;padding:3px 0;'>
                {wicon} <b style='color:{wcol};'>{w["option_type"].upper()}</b> ${w["strike"]:.0f}
                <span style='color:#5a7a90;'>{w["expiry"]}</span> ·
                <b style='color:#e0e8f0;'>${w["premium"]:,.0f}</b> ·
                {w["trade_type"]}
            </div>"""
        if not whale_html:
            whale_html = "<div style='color:#5a7a90;font-size:0.75rem;'>No whale flow detected.</div>"

        tickers_html += f"""
        <div style='background:#0e1520;border:1px solid #1a2535;border-radius:10px;padding:18px 22px;margin:10px 0;'>
          <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>
            <span style='font-family:Syne,sans-serif;font-size:1.3rem;font-weight:800;color:#bc8cff;'>{ticker}</span>
            <span style='font-family:monospace;font-size:0.95rem;color:#e0e8f0;'>${spot:.2f}</span>
            <span style='background:{bias["color"]}20;color:{bias["color"]};padding:6px 14px;border-radius:20px;font-family:monospace;font-weight:700;font-size:0.82rem;'>{bias["direction"]}</span>
          </div>

          <div style='font-size:0.78rem;color:#5a7a90;margin-bottom:6px;font-family:monospace;'>RESISTANCE ABOVE</div>
          <div style='margin-bottom:10px;'>{res_html}</div>

          <div style='font-size:0.78rem;color:#5a7a90;margin-bottom:6px;font-family:monospace;'>SUPPORT BELOW</div>
          <div style='margin-bottom:14px;'>{sup_html}</div>

          <div style='font-size:0.78rem;color:#5a7a90;margin-bottom:6px;font-family:monospace;'>TOP WHALE FLOW</div>
          <div>{whale_html}</div>
        </div>"""

    return f"""<!DOCTYPE html><html>
    <body style='background:#06080f;color:#d4dce8;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:0;'>
    <div style='max-width:900px;margin:0 auto;padding:24px;'>

      <!-- Header -->
      <div style='background:linear-gradient(90deg,#0a0518,#1a0d3a);border:1px solid #2a1a4a;border-radius:12px;padding:20px 24px;margin-bottom:20px;'>
        <h1 style='margin:0;font-family:Syne,sans-serif;font-size:1.8rem;font-weight:800;
                   background:linear-gradient(90deg,#bc8cff,#6a5aff,#4af0c4);
                   -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>🔮 GexMetrics — Daily Market Outlook</h1>
        <p style='color:#5a7a90;font-family:monospace;font-size:0.78rem;margin:6px 0 0 0;'>
          Generated: {report["generated_at"]} · {len(tickers)} tickers analyzed
        </p>
      </div>

      <!-- Macro -->
      <div style='background:#0e1520;border:1px solid #1a2535;border-radius:10px;padding:18px 22px;margin:10px 0;'>
        <h2 style='margin:0 0 12px 0;font-family:monospace;font-size:0.95rem;color:#bc8cff;'>📊 MACRO CONTEXT</h2>
        <div>{macro_html}</div>
      </div>

      <!-- Earnings -->
      <div style='background:#0e1520;border:1px solid #1a2535;border-radius:10px;padding:18px 22px;margin:10px 0;'>
        <h2 style='margin:0 0 12px 0;font-family:monospace;font-size:0.95rem;color:#bc8cff;'>📅 UPCOMING EARNINGS (NEXT 14 DAYS)</h2>
        <div>{earnings_html}</div>
      </div>

      <!-- Per-ticker -->
      <div style='margin-top:16px;'>
        <h2 style='font-family:monospace;font-size:0.95rem;color:#bc8cff;margin-bottom:12px;'>🎯 DEALER POSITIONING & BIAS</h2>
        {tickers_html}
      </div>

      <!-- Footer -->
      <div style='text-align:center;font-family:monospace;font-size:0.68rem;color:#3a2a50;margin-top:24px;padding-top:14px;border-top:1px solid #1a2030;'>
        GexMetrics · yfinance EOD data · GEX from Black-Scholes · Educational use only · Not financial advice
      </div>
    </div></body></html>"""


# ── Email subscribers ─────────────────────────────────────────────────────────

def load_subscribers():
    subs = []
    try:
        with open("subscribers.txt", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                parts = line.split(",", 1)
                email = parts[0].strip()
                name  = parts[1].strip() if len(parts) > 1 else email.split("@")[0]
                if "@" in email:
                    subs.append({"email": email, "name": name})
    except FileNotFoundError:
        pass
    return subs


def send_outlook_email(html, subject):
    if not GMAIL_USER or not GMAIL_PASS:
        return False, "Gmail credentials missing in secrets"

    subscribers = load_subscribers()
    if not subscribers:
        return False, "No subscribers in subscribers.txt"

    sent_count = 0
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            for sub in subscribers:
                try:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"]    = GMAIL_USER
                    msg["To"]      = sub["email"]
                    msg.attach(MIMEText(html, "html"))
                    s.sendmail(GMAIL_USER, sub["email"], msg.as_string())
                    sent_count += 1
                except Exception as e:
                    print(f"Failed for {sub['email']}: {e}")
        return True, f"Sent to {sent_count} subscriber(s)"
    except Exception as e:
        return False, str(e)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔮 GexMetrics")
    st.markdown("*Daily Market Outlook*")
    st.markdown("---")

    st.markdown("### ⚙️ Settings")
    sel_indices = st.multiselect("Indices",  INDICES, default=INDICES)
    sel_mag7    = st.multiselect("Mag7",     MAG7,    default=MAG7)
    max_exp     = st.slider("Expiries to scan", 1, 6, 3)
    whale_thresh= st.number_input("Whale threshold ($)", value=500000, step=100000)

    st.markdown("---")
    gen_btn   = st.button("🔮 Generate Outlook", type="primary")
    email_btn = st.button("📧 Email Outlook")

    if st.session_state.last_run:
        st.caption(f"Last run: {st.session_state.last_run}")

    st.markdown("""
    <div style='margin-top:20px;font-size:0.7rem;color:#5a3a80;line-height:1.7;'>
    <b style='color:#bc8cff;'>How to read</b><br>
    🟢 BULLISH = positive bias<br>
    🔴 BEARISH = negative bias<br>
    🟡 NEUTRAL = no clear signal<br><br>
    <b style='color:#bc8cff;'>Levels</b><br>
    🟢 Green = support (positive GEX)<br>
    🔴 Red = resistance (positive GEX)<br><br>
    <i style='color:#3a2a50;'>Phase 1 · yfinance EOD<br>Not financial advice</i>
    </div>""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div style='padding:8px 0 16px 0;'>
  <h1 style='font-family:Syne,sans-serif;font-size:2.2rem;font-weight:800;
             background:linear-gradient(90deg,#bc8cff,#6a5aff,#4af0c4);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;
             margin:0;letter-spacing:-0.02em;'>🔮 GexMetrics</h1>
  <p style='color:#5a3a80;font-family:JetBrains Mono,monospace;font-size:0.78rem;margin:4px 0 0 0;'>
    Daily Market Outlook · SPY · QQQ · IWM · Mag7 · Dealer Positioning · Whale Flow
  </p>
</div>""", unsafe_allow_html=True)

# ── Generate Outlook ──────────────────────────────────────────────────────────

if gen_btn:
    outlook_engine = DailyOutlook()
    with st.status("🔮 Generating outlook...", expanded=True) as status:
        pb  = st.progress(0)
        stx = st.empty()

        def cb(pct, msg):
            pb.progress(pct)
            stx.markdown(f"`{msg}`")

        report = outlook_engine.generate(
            indices=sel_indices, mag7=sel_mag7,
            max_expiries=max_exp, whale_threshold=whale_thresh,
            progress_cb=cb,
        )
        pb.empty(); stx.empty()
        st.session_state.outlook  = report
        st.session_state.last_run = datetime.now().strftime("%H:%M:%S")
        status.update(label="✅ Outlook generated!", state="complete")

# ── Email Outlook ─────────────────────────────────────────────────────────────

if email_btn:
    if st.session_state.outlook is None:
        st.warning("⚠️ Generate an outlook first")
    else:
        html    = build_outlook_html(st.session_state.outlook)
        subject = f"🔮 GexMetrics — Daily Market Outlook · {datetime.now().strftime('%b %d %H:%M ET')}"
        ok, msg = send_outlook_email(html, subject)
        if ok: st.success(f"✅ {msg}")
        else:  st.error(f"❌ {msg}")

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2 = st.tabs(["🔮 Daily Outlook", "📊 GEX/VEX Deep Dive"])

# ════════════════════════════════════════════════
#  TAB 1 — DAILY OUTLOOK
# ════════════════════════════════════════════════
with tab1:
    if st.session_state.outlook is None:
        st.markdown("""
        <div style='text-align:center;padding:80px 0;'>
          <div style='font-size:4rem;'>🔮</div>
          <h2 style='font-family:Syne,sans-serif;color:#5a3a80;margin-top:16px;'>Daily Market Outlook</h2>
          <p style='font-family:JetBrains Mono,monospace;color:#3a2a50;font-size:0.9rem;'>
            Click <b style='color:#bc8cff;'>Generate Outlook</b> in the sidebar
          </p>
          <p style='font-family:JetBrains Mono,monospace;color:#3a2a50;font-size:0.78rem;margin-top:24px;line-height:1.8;'>
            Macro context · Dealer positioning · Whale flow · Earnings calendar<br>
            Synthesizes data into a directional bias for SPY · QQQ · IWM · Mag7
          </p>
        </div>""", unsafe_allow_html=True)
    else:
        report = st.session_state.outlook

        # Strip outer html/body tags for Streamlit display (keep them for email)
        full_html = build_outlook_html(report)
        # Extract just the inner content
        import re
        m = re.search(r'<div style=\'max-width:900px[^>]*>(.+)</div>\s*</body>', full_html, re.DOTALL)
        inner = m.group(1) if m else full_html

        st.markdown(inner, unsafe_allow_html=True)


# ════════════════════════════════════════════════
#  TAB 2 — GEX/VEX DEEP DIVE
# ════════════════════════════════════════════════
with tab2:
    if st.session_state.outlook is None:
        st.markdown("""
        <div style='text-align:center;padding:60px 0;color:#3a2a50;'>
          <div style='font-size:3rem;'>📊</div>
          <p style='font-family:JetBrains Mono,monospace;font-size:0.85rem;margin-top:12px;'>
            Run outlook first to populate GEX/VEX data
          </p>
        </div>""", unsafe_allow_html=True)
    else:
        all_tickers = list(st.session_state.outlook["tickers"].keys())
        sel_t = st.selectbox("Select ticker", all_tickers, key="gex_deep")

        if sel_t:
            # Recompute fresh GEX for the deep dive
            with st.spinner(f"Loading {sel_t} chain..."):
                fetcher = OptionsChainFetcher(sel_t)
                chain   = fetcher.get_chain(max_expiries=max_exp)
                spot    = fetcher.spot

                if not chain.empty:
                    gex_df = GEXCalculator().calculate(chain, spot)

                    if not gex_df.empty:
                        # Filter to ±15% of spot
                        gex_filtered = gex_df[abs(gex_df["strike"] - spot) / spot <= 0.15]

                        st.markdown(f"### {sel_t} — Spot ${spot:.2f}")

                        c1, c2, c3 = st.columns(3)
                        c1.metric("Total Net GEX", f"${gex_df['net_gex'].sum():,.0f}")
                        if not gex_filtered.empty:
                            max_pos = gex_filtered.loc[gex_filtered["net_gex"].idxmax(), "strike"]
                            max_neg = gex_filtered.loc[gex_filtered["net_gex"].idxmin(), "strike"]
                            c2.metric("Max Support",    f"${max_pos:.2f}")
                            c3.metric("Max Resistance", f"${max_neg:.2f}")

                        # GEX bar chart
                        colors = ["#4af0c4" if v >= 0 else "#f04a6a" for v in gex_filtered["net_gex"]]
                        fig = go.Figure(go.Bar(
                            x=gex_filtered["net_gex"],
                            y=gex_filtered["strike"],
                            orientation="h",
                            marker_color=colors,
                        ))
                        fig.add_hline(y=spot, line=dict(color="#f5c842", width=2, dash="dash"),
                                      annotation_text=f"Spot ${spot:.2f}",
                                      annotation_font_color="#f5c842")
                        fig.update_layout(
                            template="plotly_dark", paper_bgcolor="#0e1520", plot_bgcolor="#0e1520",
                            height=600, margin=dict(l=8, r=8, t=24, b=8),
                            xaxis_title="GEX ($)", yaxis_title="Strike",
                            font=dict(family="JetBrains Mono", color="#8090a0"),
                        )
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("No options chain data available")

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style='text-align:center;font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#1a0a30;'>
  GexMetrics · Phase 1 · yfinance EOD data · Not financial advice
</div>""", unsafe_allow_html=True)
