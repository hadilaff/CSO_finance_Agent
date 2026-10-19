"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { api, MarketResponse, MacroResponse, ForecastResponse } from "@/lib/api";
import MarketChart from "./MarketChart";
import ForecastChart from "./ForecastChart";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";

// ── Preset data ───────────────────────────────────────────────────────────────
const WATCHLIST: Record<string, Record<string, string>> = {
  "Equity Indices": { "^GSPC": "S&P 500", "^FTSE": "FTSE 100", "^N225": "Nikkei 225", "^HSI": "Hang Seng" },
  "FX Rates":       { "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDAED=X": "USD/AED", "USDSGD=X": "USD/SGD" },
  "Commodities":    { "GC=F": "Gold ($/oz)", "CL=F": "Crude WTI", "BZ=F": "Brent" },
  "Crypto":         { "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum" },
  "Rates ETF":      { "TLT": "iShares 20Y Treasury", "HYG": "High Yield Bond ETF" },
};

const MACRO_PRESETS: Record<string, string> = {
  FEDFUNDS: "Fed Funds Rate",
  DGS10:    "US 10Y Treasury Yield",
  CPIAUCSL: "US CPI",
  UNRATE:   "Unemployment",
  VIXCLS:   "VIX",
  BAMLH0A0HYM2: "US HY Spread",
};

const FORECAST_TICKERS: Record<string, string> = {
  "^GSPC":    "S&P 500",
  "GC=F":     "Gold ($/oz)",
  "BTC-USD":  "Bitcoin",
  "EURUSD=X": "EUR/USD",
  "CL=F":     "Crude Oil WTI",
  "ETH-USD":  "Ethereum",
  "GBPUSD=X": "GBP/USD",
  "^FTSE":    "FTSE 100",
};

const PERIODS = ["1mo", "3mo", "6mo", "ytd", "1y", "2y"];
const MACRO_PERIODS = ["3mo", "6mo", "1y", "2y", "5y"];
const FORECAST_HORIZONS = [7, 14, 30, 60, 90];
const HISTORY_OPTIONS = ["6mo", "1y", "2y", "5y"];

// ── Tab type ──────────────────────────────────────────────────────────────────
type Tab = "markets" | "macro" | "forecast";

// ── Markets tab ───────────────────────────────────────────────────────────────
function MarketsTab() {
  const allTickers = Object.values(WATCHLIST).flatMap((g) =>
    Object.entries(g).map(([ticker, label]) => ({ ticker, label }))
  );

  const defaultSelected = ["^GSPC", "EURUSD=X", "GC=F", "BTC-USD"];
  const [selected, setSelected] = useState<string[]>(defaultSelected);
  const [period,   setPeriod]   = useState("3mo");
  const [result,   setResult]   = useState<MarketResponse | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  function toggle(ticker: string) {
    setSelected((prev) =>
      prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]
    );
  }

  async function fetch() {
    if (!selected.length) return;
    setLoading(true); setError(null);
    try {
      const data = await api.market(selected, period);
      setResult(data);
    } catch (e: any) { setError(e.message ?? "Fetch failed."); }
    finally { setLoading(false); }
  }

  return (
    <div className="space-y-4">
      {/* Ticker picker */}
      <div className="space-y-2">
        {Object.entries(WATCHLIST).map(([group, tickers]) => (
          <div key={group}>
            <p className="text-xs text-gray-400 font-medium mb-1">{group}</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(tickers).map(([ticker, label]) => (
                <button
                  key={ticker}
                  onClick={() => toggle(ticker)}
                  className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${
                    selected.includes(ticker)
                      ? "bg-accent text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-accent"
        >
          {PERIODS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <button
          onClick={fetch}
          disabled={loading || !selected.length}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-navy text-white text-xs rounded-lg hover:bg-navy/90 disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : null}
          {loading ? "Fetching…" : "Fetch data"}
        </button>
      </div>

      {error && <p className="text-xs text-red-500">⚠️ {error}</p>}
      {result && <MarketChart result={result} keyPrefix="dashboard" />}
    </div>
  );
}

// ── Macro tab ─────────────────────────────────────────────────────────────────
const COLORS = ["#2E7DDD", "#0A2540", "#E07B00", "#16A34A", "#DC2626", "#7C3AED"];

function MacroTab() {
  const defaultSeries = ["FEDFUNDS", "DGS10", "CPIAUCSL", "VIXCLS"];
  const [selected, setSelected] = useState<string[]>(defaultSeries);
  const [period,   setPeriod]   = useState("1y");
  const [result,   setResult]   = useState<MacroResponse | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  }

  async function fetch() {
    if (!selected.length) return;
    setLoading(true); setError(null);
    try {
      const data = await api.macro(selected, period);
      setResult(data);
    } catch (e: any) { setError(e.message ?? "Fetch failed."); }
    finally { setLoading(false); }
  }

  const hasFredError = result?.errors?.["_all"]?.includes("FRED_API_KEY");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(MACRO_PRESETS).map(([id, label]) => (
          <button
            key={id}
            onClick={() => toggle(id)}
            className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${
              selected.includes(id)
                ? "bg-accent text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-accent"
        >
          {MACRO_PERIODS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <button
          onClick={fetch}
          disabled={loading || !selected.length}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-navy text-white text-xs rounded-lg hover:bg-navy/90 disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : null}
          {loading ? "Fetching…" : "Fetch macro"}
        </button>
      </div>

      {error && <p className="text-xs text-red-500">⚠️ {error}</p>}

      {hasFredError && (
        <div className="px-3 py-3 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-700">
          <strong>FRED API key required.</strong> Get a free key at{" "}
          <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" className="underline">
            fred.stlouisfed.org
          </a>{" "}
          and add <code className="bg-blue-100 px-1 rounded">FRED_API_KEY=your_key</code> to your <code>.env</code>.
        </div>
      )}

      {result?.series && result.series.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl p-4 space-y-3 shadow-sm">
          {/* Metric cards */}
          <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(result.series.length, 4)}, minmax(0,1fr))` }}>
            {result.series.map((s) => (
              <div key={s.ticker} className="bg-gray-50 rounded-xl p-3">
                <p className="text-xs text-gray-400 truncate">{s.label}</p>
                <p className="text-sm font-semibold text-navy mt-0.5">{s.latest.toFixed(3)}</p>
                <p className={`text-xs mt-0.5 ${s.pct_change >= 0 ? "text-green-600" : "text-red-500"}`}>
                  {s.pct_change >= 0 ? "+" : ""}{s.pct_change.toFixed(2)}% ({period})
                </p>
              </div>
            ))}
          </div>

          {/* Line chart */}
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={(() => {
                const dates = result.series[0]?.dates ?? [];
                return dates.map((d, i) => {
                  const row: Record<string, string | number> = { date: d };
                  result.series.forEach((s) => { row[s.label] = s.values[i] ?? null; });
                  return row;
                });
              })()}
              margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf1" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={{ stroke: "#e8ecf1" }} tickFormatter={(_, i) => i % Math.max(1, Math.floor((result.series[0]?.dates.length ?? 1) / 8)) === 0 ? result.series[0]?.dates[i]?.slice(5) ?? "" : ""} />
              <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {result.series.map((s, i) => (
                <Line key={s.ticker} type="monotone" dataKey={s.label} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={1.8} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ── Forecast tab ──────────────────────────────────────────────────────────────
function ForecastTab() {
  const [ticker,    setTicker]    = useState("GC=F");
  const [periods,   setPeriods]   = useState(30);
  const [history,   setHistory]   = useState("2y");
  const [triggered, setTriggered] = useState(false);
  const [args,      setArgs]      = useState<{ ticker: string; periods: number; history_period: string } | null>(null);

  function run() {
    setArgs({ ticker, periods, history_period: history });
    setTriggered(true);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Instrument</label>
          <select
            value={ticker}
            onChange={(e) => { setTicker(e.target.value); setTriggered(false); }}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-accent"
          >
            {Object.entries(FORECAST_TICKERS).map(([t, l]) => (
              <option key={t} value={t}>{l} ({t})</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Horizon</label>
          <select
            value={periods}
            onChange={(e) => { setPeriods(Number(e.target.value)); setTriggered(false); }}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-accent"
          >
            {FORECAST_HORIZONS.map((h) => (
              <option key={h} value={h}>{h} days</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Training history</label>
          <select
            value={history}
            onChange={(e) => { setHistory(e.target.value); setTriggered(false); }}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-accent"
          >
            {HISTORY_OPTIONS.map((h) => <option key={h} value={h}>{h}</option>)}
          </select>
        </div>
        <button
          onClick={run}
          className="flex items-center gap-1.5 px-4 py-1.5 bg-navy text-white text-xs rounded-lg hover:bg-navy/90 transition-colors"
        >
          Run forecast
        </button>
      </div>

      {triggered && args && (
        <ForecastChart args={args} summary={{}} keyPrefix="dashboard-fc" />
      )}
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────────
export default function MarketDashboard() {
  const [tab, setTab] = useState<Tab>("markets");

  const tabs: { id: Tab; label: string }[] = [
    { id: "markets",  label: "📊 Markets" },
    { id: "macro",    label: "🏦 Macro (FRED)" },
    { id: "forecast", label: "🔮 Forecast" },
  ];

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-navy">📈 Market Data</h2>

      {/* Tabs */}
      <div className="flex border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id
                ? "border-accent text-accent"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="pt-1">
        {tab === "markets"  && <MarketsTab />}
        {tab === "macro"    && <MacroTab />}
        {tab === "forecast" && <ForecastTab />}
      </div>
    </div>
  );
}
