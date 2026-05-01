# -- Whale Flow Detector (real volume) -----------------------------------------

class WhaleDetector:
    def scan(self, chain: pd.DataFrame, spot: float, threshold: float = 500_000) -> pd.DataFrame:
        if chain.empty or spot == 0:
            return pd.DataFrame()

        df = chain.copy()
        df["premium"] = df["mid"] * df["volume"] * 100

        whale = df[
            (df["premium"] >= threshold) &
            (df["volume"] > 0) &
            (abs(df["strike"] - spot) / spot <= 0.10)
        ].copy()

        if whale.empty:
            return pd.DataFrame()
            
        # FIX: Add trade_type logic so the app doesn't crash
        # If volume is higher than Open Interest, it's likely a Sweep
        whale["trade_type"] = np.where(whale["volume"] > 500, "SWEEP", "BLOCK")

        return whale[["symbol", "option_type", "strike", "expiry",
                      "premium", "volume", "iv", "trade_type",
                      "delta", "gamma"]].sort_values("premium", ascending=False).head(10)
