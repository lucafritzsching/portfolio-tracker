"""Data Science pipeline: technical indicators, statistical models, forecasting."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


@dataclass
class TechnicalIndicators:
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_12: float | None
    ema_26: float | None
    current_price: float | None
    price_vs_sma200: float | None  # percent deviation
    trend_signal: str  # BULLISH / BEARISH / NEUTRAL


@dataclass
class ModelForecast:
    method: str
    forecast_7d: float | None
    forecast_30d: float | None
    confidence: float | None  # 0.0 – 1.0
    signal: str  # BUY / HOLD / SELL
    details: str


def calculate_technical_indicators(prices: list[dict]) -> TechnicalIndicators:
    """Calculate technical indicators from a list of OHLCV dicts."""
    if len(prices) < 30:
        return TechnicalIndicators(
            rsi_14=None, macd=None, macd_signal=None, macd_histogram=None,
            bb_upper=None, bb_middle=None, bb_lower=None,
            sma_20=None, sma_50=None, sma_200=None,
            ema_12=None, ema_26=None, current_price=None,
            price_vs_sma200=None, trend_signal="NEUTRAL"
        )

    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    close = df["close"].astype(float)

    # RSI
    rsi = _rsi(close, 14)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # SMAs
    sma50 = close.rolling(50).mean() if len(close) >= 50 else pd.Series([None] * len(close))
    sma200 = close.rolling(200).mean() if len(close) >= 200 else pd.Series([None] * len(close))

    current = float(close.iloc[-1])
    sma200_val = float(sma200.iloc[-1]) if len(close) >= 200 and not pd.isna(sma200.iloc[-1]) else None
    price_vs_sma200 = ((current - sma200_val) / sma200_val * 100) if sma200_val else None

    # Trend signal
    rsi_val = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
    macd_val = float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0
    hist_val = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0

    bullish_signals = 0
    bearish_signals = 0
    if rsi_val and rsi_val > 50: bullish_signals += 1
    if rsi_val and rsi_val < 50: bearish_signals += 1
    if macd_val > 0: bullish_signals += 1
    if macd_val < 0: bearish_signals += 1
    if hist_val > 0: bullish_signals += 1
    if hist_val < 0: bearish_signals += 1
    if price_vs_sma200 and price_vs_sma200 > 0: bullish_signals += 1
    if price_vs_sma200 and price_vs_sma200 < 0: bearish_signals += 1

    if bullish_signals > bearish_signals + 1:
        trend = "BULLISH"
    elif bearish_signals > bullish_signals + 1:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return TechnicalIndicators(
        rsi_14=rsi_val,
        macd=macd_val,
        macd_signal=float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else None,
        macd_histogram=hist_val,
        bb_upper=float(bb_upper.iloc[-1]) if not pd.isna(bb_upper.iloc[-1]) else None,
        bb_middle=float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None,
        bb_lower=float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else None,
        sma_20=float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None,
        sma_50=float(sma50.iloc[-1]) if len(close) >= 50 and not pd.isna(sma50.iloc[-1]) else None,
        sma_200=sma200_val,
        ema_12=float(ema12.iloc[-1]),
        ema_26=float(ema26.iloc[-1]),
        current_price=current,
        price_vs_sma200=round(price_vs_sma200, 2) if price_vs_sma200 else None,
        trend_signal=trend,
    )


def run_arima_forecast(prices: list[dict]) -> ModelForecast:
    """Run ARIMA(p,d,q) forecast on closing prices."""
    if len(prices) < 60:
        return ModelForecast(
            method="ARIMA",
            forecast_7d=None,
            forecast_30d=None,
            confidence=None,
            signal="HOLD",
            details="Nicht genug Datenpunkte für ARIMA-Prognose (min. 60 Tage benötigt)",
        )

    try:
        from statsmodels.tsa.arima.model import ARIMA

        df = pd.DataFrame(prices)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        close = df["close"].astype(float).values

        # Fit ARIMA(2,1,2) – reasonable default for stock prices
        model = ARIMA(close, order=(2, 1, 2))
        fit = model.fit()

        # Forecast 30 steps ahead
        forecast_result = fit.forecast(steps=30)
        f7 = float(forecast_result[6])
        f30 = float(forecast_result[29])
        current = float(close[-1])

        change_7d = (f7 - current) / current * 100
        change_30d = (f30 - current) / current * 100

        # Simple confidence from AIC (lower = better; normalize roughly)
        aic = fit.aic
        confidence = max(0.1, min(0.9, 1.0 - abs(aic) / 10000))

        if change_30d > 5:
            signal = "BUY"
        elif change_30d < -5:
            signal = "SELL"
        else:
            signal = "HOLD"

        details = (
            f"ARIMA(2,1,2) Prognose: "
            f"+7 Tage: {f7:.2f} ({change_7d:+.1f}%), "
            f"+30 Tage: {f30:.2f} ({change_30d:+.1f}%). "
            f"AIC: {aic:.0f}, Konfidenz: {confidence:.0%}"
        )

        return ModelForecast(
            method="ARIMA(2,1,2)",
            forecast_7d=round(f7, 2),
            forecast_30d=round(f30, 2),
            confidence=round(confidence, 2),
            signal=signal,
            details=details,
        )

    except Exception as e:
        return ModelForecast(
            method="ARIMA",
            forecast_7d=None,
            forecast_30d=None,
            confidence=None,
            signal="HOLD",
            details=f"ARIMA-Modell konnte nicht angepasst werden: {e}",
        )


def run_ml_signal(prices: list[dict]) -> ModelForecast:
    """Random Forest classifier: Buy/Hold/Sell signal based on technical features."""
    if len(prices) < 100:
        return ModelForecast(
            method="RandomForest",
            forecast_7d=None,
            forecast_30d=None,
            confidence=None,
            signal="HOLD",
            details="Nicht genug Datenpunkte für ML-Signal (min. 100 Tage benötigt)",
        )

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler

        df = pd.DataFrame(prices)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        close = df["close"].astype(float)

        # Feature engineering
        df["rsi"] = _rsi(close, 14)
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        df["macd"] = ema12 - ema26
        df["sma20"] = close.rolling(20).mean()
        df["sma50"] = close.rolling(50).mean()
        df["volatility"] = close.pct_change().rolling(20).std()
        df["momentum"] = close.pct_change(10)
        df["price_vs_sma20"] = (close - df["sma20"]) / df["sma20"]
        df["price_vs_sma50"] = (close - df["sma50"]) / df["sma50"]

        # Label: forward 20-day return > 3% → BUY=2, < -3% → SELL=0, else HOLD=1
        df["future_return"] = close.pct_change(20).shift(-20)
        df["label"] = 1  # HOLD
        df.loc[df["future_return"] > 0.03, "label"] = 2   # BUY
        df.loc[df["future_return"] < -0.03, "label"] = 0  # SELL

        feature_cols = ["rsi", "macd", "volatility", "momentum", "price_vs_sma20", "price_vs_sma50"]
        df_clean = df[feature_cols + ["label"]].dropna()

        if len(df_clean) < 50:
            raise ValueError("Zu wenige saubere Datenpunkte")

        X = df_clean[feature_cols].values
        y = df_clean["label"].values

        # Train on all but last 20 rows, predict on last row
        X_train, X_pred = X[:-20], X[-1:]
        y_train = y[:-20]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_pred_s = scaler.transform(X_pred)

        clf = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
        clf.fit(X_train_s, y_train)

        pred = clf.predict(X_pred_s)[0]
        proba = clf.predict_proba(X_pred_s)[0]
        confidence = float(max(proba))
        label_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
        signal = label_map[pred]

        details = (
            f"Random Forest (100 Bäume, {len(X_train)} Trainingspunkte): "
            f"Signal={signal}, "
            f"P(SELL)={proba[0]:.1%}, P(HOLD)={proba[1]:.1%}, P(BUY)={proba[2]:.1%}"
        )

        return ModelForecast(
            method="RandomForest",
            forecast_7d=None,
            forecast_30d=None,
            confidence=round(confidence, 2),
            signal=signal,
            details=details,
        )

    except Exception as e:
        return ModelForecast(
            method="RandomForest",
            forecast_7d=None,
            forecast_30d=None,
            confidence=None,
            signal="HOLD",
            details=f"ML-Modell Fehler: {e}",
        )


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
