"""Time series forecasting via Facebook Prophet.

Pipeline
--------
  yfinance (historical prices)
      → Prophet model (fit on ds/y columns)
          → forecast dataframe (yhat, yhat_lower, yhat_upper)
          → trend + weekly/yearly seasonality components
              → ForecastResult (structured for agent + Plotly)

Public API
----------
  run_forecast(ticker, periods, history_period)  →  ForecastResult
  FORECASTABLE_TICKERS                           →  dict  (curated list)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ── Curated tickers that forecast well with daily data ───────────────────────
FORECASTABLE_TICKERS: dict[str, str] = {
    # Equity indices
    "^GSPC":    "S&P 500",
    "^FTSE":    "FTSE 100",
    "^N225":    "Nikkei 225",
    "^HSI":     "Hang Seng",
    # FX
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDAED=X": "USD/AED",
    "USDSGD=X": "USD/SGD",
    # Commodities
    "GC=F":     "Gold ($/oz)",
    "CL=F":     "Crude Oil WTI",
    "BZ=F":     "Brent Crude",
    # Crypto
    "BTC-USD":  "Bitcoin",
    "ETH-USD":  "Ethereum",
    # Rates proxy ETFs (daily data, no index quirks)
    "TLT":      "iShares 20Y Treasury ETF",
    "HYG":      "iShares High Yield Bond ETF",
}

# Minimum trading days needed to fit a reliable Prophet model
_MIN_HISTORY_DAYS = 90


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    ticker:          str
    label:           str
    history_period:  str            # e.g. "2y"
    forecast_days:   int            # how many future days were requested

    # Historical series (for the "actual" trace on the chart)
    hist_dates:      list[str]  = field(default_factory=list)
    hist_values:     list[float] = field(default_factory=list)

    # Forecast series (future window only)
    fc_dates:        list[str]  = field(default_factory=list)
    fc_yhat:         list[float] = field(default_factory=list)   # point forecast
    fc_lower:        list[float] = field(default_factory=list)   # 80% lower bound
    fc_upper:        list[float] = field(default_factory=list)   # 80% upper bound

    # Trend component (full history + forecast window)
    trend_dates:     list[str]  = field(default_factory=list)
    trend_values:    list[float] = field(default_factory=list)

    # Key summary stats
    last_actual:     float = 0.0
    fc_end_value:    float = 0.0    # point forecast at end of horizon
    fc_pct_change:   float = 0.0    # % change from last actual → end of forecast
    trend_direction: str   = ""     # "upward", "downward", "flat"
    currency:        str   = "USD"

    error:           str | None = None

    def to_agent_dict(self) -> dict:
        """Compact summary for the LLM — no raw arrays."""
        if self.error:
            return {"error": self.error, "ticker": self.ticker}
        return {
            "ticker":          self.ticker,
            "label":           self.label,
            "history_period":  self.history_period,
            "forecast_days":   self.forecast_days,
            "last_actual":     round(self.last_actual, 4),
            "forecast_end":    round(self.fc_end_value, 4),
            "forecast_pct_change": round(self.fc_pct_change, 2),
            "forecast_lower":  round(self.fc_lower[-1], 4) if self.fc_lower else None,
            "forecast_upper":  round(self.fc_upper[-1], 4) if self.fc_upper else None,
            "trend_direction": self.trend_direction,
            "currency":        self.currency,
            "data_points_used": len(self.hist_dates),
        }


# ── Core function ─────────────────────────────────────────────────────────────

def run_forecast(
    ticker: str,
    periods: int = 30,
    history_period: str = "2y",
) -> ForecastResult:
    """Fit a Prophet model on `ticker` history and forecast `periods` calendar days ahead.

    Parameters
    ----------
    ticker         : Yahoo Finance ticker symbol
    periods        : number of future calendar days to forecast (default 30)
    history_period : how much history to train on — more = better seasonality detection
                     options: "6mo", "1y", "2y", "5y"  (default "2y")

    Returns
    -------
    ForecastResult with historical traces, forecast traces, trend, and summary stats.
    Prophet is imported lazily so the app starts even if the package isn't installed yet.
    """
    label = FORECASTABLE_TICKERS.get(ticker, ticker)
    result = ForecastResult(
        ticker=ticker,
        label=label,
        history_period=history_period,
        forecast_days=periods,
    )

    # ── 1. Fetch historical data via yfinance ────────────────────────────────
    try:
        import yfinance as yf
    except ImportError:
        result.error = "yfinance not installed."
        return result

    try:
        tk   = yf.Ticker(ticker)
        hist = tk.history(period=history_period, interval="1d", auto_adjust=True)
        hist = hist["Close"].dropna()
    except Exception as e:
        result.error = f"Failed to fetch data for '{ticker}': {e}"
        return result

    if len(hist) < _MIN_HISTORY_DAYS:
        result.error = (
            f"Not enough history ({len(hist)} days). "
            f"Need at least {_MIN_HISTORY_DAYS} days. Try a longer history_period."
        )
        return result

    # Currency best-effort
    try:
        result.currency = tk.fast_info.currency or "USD"
    except Exception:
        pass

    # Store historical series
    result.hist_dates  = [d.strftime("%Y-%m-%d") for d in hist.index]
    result.hist_values = [round(float(v), 6) for v in hist.values]
    result.last_actual = result.hist_values[-1]

    # ── 2. Prepare Prophet dataframe ─────────────────────────────────────────
    try:
        import pandas as pd
        df = pd.DataFrame({
            "ds": pd.to_datetime(result.hist_dates),
            "y":  result.hist_values,
        })
    except ImportError:
        result.error = "pandas not installed."
        return result

    # ── 3. Fit Prophet model ─────────────────────────────────────────────────
    try:
        from prophet import Prophet          # lazy import
    except ImportError:
        result.error = (
            "prophet not installed. "
            "Add 'prophet' to requirements.txt and rebuild the Docker image."
        )
        return result

    try:
        model = Prophet(
            interval_width=0.80,            # 80% confidence band
            daily_seasonality=False,        # daily bars → no intra-day pattern
            weekly_seasonality=True,        # markets have Mon-Fri pattern
            yearly_seasonality=True,        # annual cycles matter for finance
            changepoint_prior_scale=0.05,   # moderate flexibility — avoids overfit
        )
        # Suppress Prophet's verbose logging
        import logging as _logging
        _logging.getLogger("prophet").setLevel(_logging.WARNING)
        _logging.getLogger("cmdstanpy").setLevel(_logging.WARNING)

        model.fit(df)
    except Exception as e:
        result.error = f"Prophet model fitting failed: {e}"
        return result

    # ── 4. Generate future dataframe and predict ─────────────────────────────
    try:
        future   = model.make_future_dataframe(periods=periods, freq="D")
        forecast = model.predict(future)
    except Exception as e:
        result.error = f"Prophet prediction failed: {e}"
        return result

    # ── 5. Extract forecast window (future dates only) ───────────────────────
    last_hist_date = df["ds"].max()
    fc_df = forecast[forecast["ds"] > last_hist_date].copy()

    result.fc_dates  = [d.strftime("%Y-%m-%d") for d in fc_df["ds"]]
    result.fc_yhat   = [round(float(v), 4) for v in fc_df["yhat"]]
    result.fc_lower  = [round(float(v), 4) for v in fc_df["yhat_lower"]]
    result.fc_upper  = [round(float(v), 4) for v in fc_df["yhat_upper"]]

    # ── 6. Trend component (full window) ─────────────────────────────────────
    result.trend_dates  = [d.strftime("%Y-%m-%d") for d in forecast["ds"]]
    result.trend_values = [round(float(v), 4) for v in forecast["trend"]]

    # ── 7. Summary stats ─────────────────────────────────────────────────────
    if result.fc_yhat:
        result.fc_end_value  = result.fc_yhat[-1]
        result.fc_pct_change = round(
            (result.fc_end_value - result.last_actual) / result.last_actual * 100, 2
        )

    # Trend direction: compare trend at start vs end of forecast window
    if result.trend_values:
        trend_start = result.trend_values[len(result.hist_dates)]   if len(result.trend_values) > len(result.hist_dates) else result.trend_values[0]
        trend_end   = result.trend_values[-1]
        pct_trend   = (trend_end - trend_start) / abs(trend_start) * 100 if trend_start else 0
        if pct_trend > 1:
            result.trend_direction = "upward"
        elif pct_trend < -1:
            result.trend_direction = "downward"
        else:
            result.trend_direction = "flat"

    return result
