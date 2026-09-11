"use client";

import { useEffect, useState } from "react";
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
// recharts v3 compatible
import { api, ForecastResponse } from "@/lib/api";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface Props {
  /** Tool call args from agent — used to fetch full arrays if needed */
  args: { ticker: string; periods?: number; history_period?: string };
  /** Compact summary returned by agent (no arrays) */
  summary: Record<string, unknown>;
  keyPrefix?: string;
}

const TREND_ICON = {
  upward:   <TrendingUp  size={14} className="text-green-500" />,
  downward: <TrendingDown size={14} className="text-red-500" />,
  flat:     <Minus        size={14} className="text-gray-400" />,
};

export default function ForecastChart({ args, summary, keyPrefix = "" }: Props) {
  const [data, setData]     = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState<string | null>(null);

  // Fetch full forecast arrays (the agent only stores the compact summary)
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await api.forecast(
          args.ticker,
          args.periods    ?? 30,
          args.history_period ?? "2y"
        );
        if (!cancelled) setData(res);
      } catch (e: any) {
        if (!cancelled) setError(e.message ?? "Forecast failed.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [args.ticker, args.periods, args.history_period]);

  if (loading)
    return (
      <div className="bg-white border border-gray-200 rounded-2xl p-4 text-sm text-gray-400 animate-pulse">
        Building forecast chart for {args.ticker}…
      </div>
    );

  if (error)
    return (
      <div className="bg-red-50 border border-red-200 rounded-2xl p-3 text-sm text-red-600">
        ⚠️ {error}
      </div>
    );

  if (!data) return null;

  // Build combined chart data
  // Historical: actual values
  // Forecast:   yhat + lower/upper band
  const histMap: Record<string, number> = {};
  data.hist_dates.forEach((d, i) => (histMap[d] = data.hist_values[i]));

  const fcMap: Record<string, { yhat: number; lower: number; upper: number }> = {};
  data.fc_dates.forEach((d, i) => {
    fcMap[d] = {
      yhat:  data.fc_yhat[i],
      lower: data.fc_lower[i],
      upper: data.fc_upper[i],
    };
  });

  // Combine all dates, show last 60 historical points + full forecast
  const histSlice  = data.hist_dates.slice(-60);
  const allDates   = [...histSlice, ...data.fc_dates];
  const lastActual = data.hist_dates[data.hist_dates.length - 1];

  const chartData = allDates.map((d) => {
    const row: Record<string, string | number | null> = { date: d };
    row.actual = histMap[d] ?? null;
    if (fcMap[d]) {
      row.forecast = fcMap[d].yhat;
      row.band     = [fcMap[d].lower, fcMap[d].upper] as any;
      row.lower    = fcMap[d].lower;
      row.upper    = fcMap[d].upper;
    } else {
      row.forecast = null;
      row.lower    = null;
      row.upper    = null;
    }
    return row;
  });

  const step = Math.max(1, Math.floor(allDates.length / 8));
  const positive = data.fc_pct_change >= 0;
  const trendDir = data.trend_direction as keyof typeof TREND_ICON;

  return (
    <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 space-y-3">
      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-400">Last actual</p>
          <p className="text-sm font-semibold text-navy mt-0.5">
            {data.last_actual.toLocaleString(undefined, { maximumFractionDigits: 4 })}{" "}
            <span className="text-xs font-normal text-gray-400">{data.currency}</span>
          </p>
        </div>
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-400">Forecast (+{data.forecast_days}d)</p>
          <p className={`text-sm font-semibold mt-0.5 ${positive ? "text-green-600" : "text-red-500"}`}>
            {data.fc_end_value.toLocaleString(undefined, { maximumFractionDigits: 4 })}
            <span className="text-xs ml-1">({positive ? "+" : ""}{data.fc_pct_change.toFixed(2)}%)</span>
          </p>
        </div>
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-400">80% band (end)</p>
          <p className="text-xs font-medium text-gray-600 mt-0.5">
            {data.fc_lower[data.fc_lower.length - 1]?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            {" – "}
            {data.fc_upper[data.fc_upper.length - 1]?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </p>
        </div>
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-400">Trend</p>
          <div className="flex items-center gap-1 mt-0.5">
            {TREND_ICON[trendDir]}
            <span className="text-sm font-medium text-gray-700 capitalize">
              {data.trend_direction}
            </span>
          </div>
        </div>
      </div>

      {/* Forecast chart */}
      <div>
        <p className="text-xs text-gray-400 mb-2">
          {data.label} — {data.forecast_days}-day Prophet forecast · trained on {data.hist_dates.length} days
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf1" />
            <XAxis
              dataKey="date"
              tickFormatter={(_, i) => (i % step === 0 ? allDates[i]?.slice(5) ?? "" : "")}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickLine={false}
              axisLine={{ stroke: "#e8ecf1" }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) =>
                v >= 1000
                  ? `${(v / 1000).toFixed(1)}k`
                  : v.toFixed(2)
              }
            />
            <Tooltip
              contentStyle={{ fontSize: 11, border: "1px solid #e8ecf1", borderRadius: 8 }}
              formatter={(v: number, name: string) => [
                v?.toLocaleString(undefined, { maximumFractionDigits: 4 }),
                name,
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />

            {/* 80% confidence band */}
            <Area
              type="monotone"
              dataKey="upper"
              stroke="none"
              fill="#2E7DDD"
              fillOpacity={0.1}
              name="80% band"
              legendType="none"
              activeDot={false}
            />
            <Area
              type="monotone"
              dataKey="lower"
              stroke="none"
              fill="#ffffff"
              fillOpacity={1}
              name=""
              legendType="none"
              activeDot={false}
            />

            {/* Actual price */}
            <Line
              type="monotone"
              dataKey="actual"
              stroke="#0A2540"
              strokeWidth={1.5}
              dot={false}
              name="Actual"
              connectNulls={false}
            />

            {/* Forecast */}
            <Line
              type="monotone"
              dataKey="forecast"
              stroke="#2E7DDD"
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={false}
              name={`Forecast (${data.forecast_days}d)`}
              connectNulls={false}
            />

            {/* Today marker */}
            <ReferenceLine
              x={lastActual}
              stroke="#9ca3af"
              strokeDasharray="3 3"
              label={{ value: "Today", fontSize: 10, fill: "#9ca3af", position: "top" }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="text-xs text-gray-400">
        ⚠️ Prophet statistical model — not financial advice. Confidence band widens with forecast horizon.
      </p>
    </div>
  );
}
