### 3. `README.md`
```markdown
# 📊 GexMetrics

GexMetrics is a Streamlit-based intelligence dashboard designed for 0DTE traders and institutional-grade options analysis. It provides real-time (EOD-basis) insights into dealer positioning and unusual options activity.

## ✨ Features
- **GEX/VEX Heatmaps**: Visualize dealer gamma and vanna exposure to identify support, resistance, and volatility zones.
- **Whale Flow**: Detect aggressive institutional trades with premiums over $500,000.
- **Contract Intelligence**: Calculate Max Pain and analyze Open Interest distribution.
- **Portfolio Greeks**: Manage complex risk with aggregate Delta, Gamma, Theta, and Vega.

## 🛠️ Tech Stack
- **Language**: Python
- **Data**: yfinance (Yahoo Finance API)
- **UI**: Streamlit
- **Visualization**: Plotly

## 🚀 Quick Start
1. Clone the repo.
2. Install dependencies: `pip install -r requirements.txt`.
3. Run the app: `streamlit run gexmetrics_app.py`.
