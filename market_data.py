"""Market data time series — yfinance (equities, FX, ETFs) + FRED (macro).

Public API
----------
fetch_market_data(tickers, period, interval) -> MarketResult
fetch_macro_data(series_ids, period)         -> MacroResult
get_ticker_info(ticker)                      -> dict
PRESET_WATCHLIST                             -> dict  (curated tickers for a financial center CSO)

Both yfinance and fredapi are optional — graceful errors if not installed.
FRED requires a free API key in the env var FRED_API_KEY; omit and only
FRED calls fail while yfinance still works.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# ── Curated watchlist relevant to an international financial center CSO ──────
PRESET_WATCHLIST: dict[str, dict[str, str]] = {
    "Equity Indices": {
        "^GSPC":  "S&P 500",
        "^FTSE":  "FTSE 100",
        "^N225":  "Nikkei 225",
        "^HSI":   "Hang Seng",
        "^STI":   "Straits Times (SGX)",
    },
    "FX Rates (vs USD)": {
        "EURUSD=X": "EUR/USD",
        "GBPUSD=X": "GBP/USD",
        "USDJPY=X": "USD/JPY",
        "USDCNH=X": "USD/CNH",
        "USDINR=X": "USD/INR",
        "USDAED=X": "USD/AED",
        "USDSGD=X": "USD/SGD",
    },
    "Commodities": {
        "GC=F":  "Gold ($/oz)",
        "CL=F":  "Crude Oil WTI ($/bbl)",
        "BZ=F":  "Crude Oil Brent ($/bbl)",
    },
    "Crypto": {
        "BTC-USD": "Bitcoin",
        "ETH-USD": "Ethereum",
    },
    "Fixed Income / Rates": {
        "^TNX": "US 10Y Treasury Yield",
        "^TYX": "US 30Y Treasury Yield",
        "^IRX": "US 3M T-Bill Yield",
    },
    "Fintech / Digital Asset ETFs": {
        "ARKF":  "ARK Fintech Innovation ETF",
        "BITO":  "ProShares Bitcoin ETF",
        "FDIG":  "Fidelity Crypto Industry ETF",
    },
}

# FRED series relevant to a financial center CSO
PRESET_MACRO: dict[str, str] = {
    "FEDFUNDS":   "Fed Funds Rate",
    "DGS10":      "US 10Y Treasury Yield",
    "CPIAUCSL":   "US CPI (YoY inflation)",
    "UNRATE":     "US Unemployment Rate",
    "DXY":        "US Dollar Index (DXY)",
    "DEXUSEU":    "EUR/USD Exchange Rate",
    "BAMLH0A0HYM2": "US High Yield Spread",
    "VIXCLS":     "VIX (Volatility Index)",
}

# Period → yfinance period string mapping
_PERIOD_MAP: dict[str, str] = {
    "1d": "1d",   "5d": "5d",   "1w": "5d",
    "1mo": "1mo", "1m": "1mo",
    "3mo": "3mo", "3m": "3mo",
    "6mo": "6mo", "6m": "6mo",
    "ytd": "ytd", "1y": "1y",
    "2y": "2y",   "5y": "5y",
    "max": "max",
}

# Period → interval (so charts don't have thousands of points)
_INTERVAL_MAP: dict[str, str] = {
    "1d":  "5m",  "5d":  "1h",
    "1mo": "1d",  "3mo": "1d",
    "6mo": "1wk", "ytd": "1d",
    "1y":  "1wk", "2y":  "1wk",
    "5y":  "1mo", "max": "1mo",
}


# ── Result dataclasses ───────────────────────────────────────────────────────

@dataclass
class SeriesData:
    ticker: str
    label: str
    dates: list[str]        # ISO date strings
    values: list[float]     # close / adjusted close prices
    currency: str = "USD"
    pct_change: float = 0.0  # total % change over the period
    latest: float = 0.0


@dataclass
class MarketResult:
    period: str
    interval: str
    series: list[SeriesData] = field(default_factory=list)
    errors: dict[str, str]  = field(default_factory=dict)

    def to_agent_dict(self) -> dict:
        """Compact representation for the LLM — no raw date arrays."""
        return {
            "period": self.period,
            "series": [
                {
                    "ticker":     s.ticker,
                    "label":      s.label,
                    "latest":     round(s.latest, 4),
                    "pct_change": round(s.pct_change, 2),
                    "currency":   s.currency,
                    "data_points": len(s.dates),
                    "from": s.dates[0] if s.dates else None,
                    "to":   s.dates[-1] if s.dates else None,
                }
                for s in self.series
            ],
            "errors": self.errors,
        }


@dataclass
class MacroResult:
    series: list[SeriesData] = field(default_factory=list)
    errors: dict[str, str]   = field(default_factory=dict)

    def to_agent_dict(self) -> dict:
        return {
            "series": [
                {
                    "series_id":  s.ticker,
                    "label":      s.label,
                    "latest":     round(s.latest, 4),
                    "pct_change": round(s.pct_change, 2),
                    "data_points": len(s.dates),
                    "from": s.dates[0] if s.dates else None,
                    "to":   s.dates[-1] if s.dates else None,
                }
                for s in self.series
            ],
            "errors": self.errors,
        }


# ── Fetchers ─────────────────────────────────────────────────────────────────

def _label_for(ticker: str) -> str:
    """Best-effort human label from the preset watchlist."""
    for group in PRESET_WATCHLIST.values():
        if ticker in group:
            return group[ticker]
    return ticker


def fetch_market_data(
    tickers: list[str],
    period: str = "3mo",
    interval: str | None = None,
) -> MarketResult:
    """Download OHLCV time series for one or more tickers via yfinance.

    Parameters
    ----------
    tickers  : list of Yahoo Finance tickers, e.g. ["^GSPC", "EURUSD=X"]
    period   : look-back window — "1d","5d","1mo","3mo","6mo","ytd","1y","2y","5y","max"
    interval : bar size — if None, auto-selected based on period
    """
    try:
        import yfinance as yf
    except ImportError:
        return MarketResult(
            period=period, interval=interval or "auto",
            errors={"_all": "yfinance not installed. Add 'yfinance' to requirements.txt."},
        )

    yf_period   = _PERIOD_MAP.get(period.lower(), period)
    yf_interval = interval or _INTERVAL_MAP.get(yf_period, "1d")

    result = MarketResult(period=yf_period, interval=yf_interval)

    for ticker in tickers:
        try:
            tk   = yf.Ticker(ticker)
            hist = tk.history(period=yf_period, interval=yf_interval, auto_adjust=True)

            if hist.empty:
                result.errors[ticker] = "No data returned (delisted or invalid ticker?)"
                continue

            closes = hist["Close"].dropna()
            dates  = [d.strftime("%Y-%m-%d") for d in closes.index]
            vals   = [round(float(v), 6) for v in closes.values]

            pct = ((vals[-1] - vals[0]) / vals[0] * 100) if len(vals) >= 2 else 0.0

            # Currency hint from ticker info (best-effort, non-blocking)
            currency = "USD"
            try:
                info = tk.fast_info
                currency = getattr(info, "currency", "USD") or "USD"
            except Exception:
                pass

            result.series.append(SeriesData(
                ticker     = ticker,
                label      = _label_for(ticker),
                dates      = dates,
                values     = vals,
                currency   = currency,
                pct_change = round(pct, 2),
                latest     = vals[-1],
            ))
        except Exception as e:
            result.errors[ticker] = str(e)

    return result


def fetch_macro_data(
    series_ids: list[str],
    period: str = "1y",
) -> MacroResult:
    """Download macro time series from FRED.

    Requires FRED_API_KEY environment variable (free at https://fred.stlouisfed.org/docs/api/api_key.html).
    Falls back gracefully if key is missing or fredapi is not installed.
    """
    fred_key = os.getenv("FRED_API_KEY", "").strip()
    if not fred_key:
        return MacroResult(
            errors={"_all": "FRED_API_KEY not set. Add it to .env for macro data."}
        )

    try:
        from fredapi import Fred
    except ImportError:
        return MacroResult(
            errors={"_all": "fredapi not installed. Add 'fredapi' to requirements.txt."}
        )

    # Determine date range from period string
    end   = datetime.today()
    delta_map = {
        "1mo": 30,  "3mo": 90,  "6mo": 180,
        "1y": 365,  "2y": 730,  "5y": 1825,
    }
    days  = delta_map.get(period.lower(), 365)
    start = end - timedelta(days=days)

    fred   = Fred(api_key=fred_key)
    result = MacroResult()

    for sid in series_ids:
        try:
            s     = fred.get_series(sid, observation_start=start, observation_end=end)
            s     = s.dropna()
            dates = [d.strftime("%Y-%m-%d") for d in s.index]
            vals  = [round(float(v), 6) for v in s.values]

            if not vals:
                result.errors[sid] = "No data for this series in the requested period."
                continue

            pct = ((vals[-1] - vals[0]) / vals[0] * 100) if len(vals) >= 2 else 0.0
            label = PRESET_MACRO.get(sid, sid)

            result.series.append(SeriesData(
                ticker     = sid,
                label      = label,
                dates      = dates,
                values     = vals,
                pct_change = round(pct, 2),
                latest     = vals[-1],
            ))
        except Exception as e:
            result.errors[sid] = str(e)

    return result


def get_ticker_info(ticker: str) -> dict:
    """Return a compact info dict for a single ticker (name, sector, market cap, etc.)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        keys = ["longName", "shortName", "sector", "industry", "marketCap",
                "currency", "exchange", "quoteType", "regularMarketPrice",
                "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "trailingPE",
                "dividendYield", "beta"]
        return {k: info.get(k) for k in keys if info.get(k) is not None}
    except Exception as e:
        return {"error": str(e)}
