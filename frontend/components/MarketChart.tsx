"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { MarketResponse, SeriesData } from "@/lib/api";

const COLORS = ["#2E7DDD", "#0A2540", "#E07B00", "#16A34A", "#DC2626", "#7C3AED"];

interface Props {
  result: MarketResponse;
  keyPrefix?: string;
}

function MetricCard({ s, period }: { s: SeriesData; period: string }) {
  const positive = s.pct_change >= 0;
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-sm">
      <p className="text-xs text-gray-500 truncate">{s.label}</p>
      <p className="text-base font-semibold text-navy mt-0.5">
        {s.latest.toLocaleString(undefined, { maximumFractionDigits: 4 })}{" "}
        <span className="text-xs font-normal text-gray-400">{s.currency}</span>
      </p>
      <p className={`text-xs mt-0.5 font-medium ${positive ? "text-green-600" : "text-red-500"}`}>
        {positive ? "+" : ""}
        {s.pct_change.toFixed(2)}% ({period})
      </p>
    </div>
  );
}

export default function MarketChart({ result, keyPrefix = "" }: Props) {
  if (!result?.series?.length) return null;

  // Build normalised chart data: base = 100 at first data point
  const series = result.series.filter((s) => s.dates?.length && s.values?.length);
  if (!series.length) return null;

  const dateSet = new Set<string>();
  series.forEach((s) => s.dates.forEach((d) => dateSet.add(d)));
  const sortedDates = Array.from(dateSet).sort();

  // Map each series to a lookup {date → value}
  const valueMaps = series.map((s) => {
    const m: Record<string, number> = {};
    s.dates.forEach((d, i) => (m[d] = s.values[i]));
    return m;
  });

  const chartData = sortedDates.map((date) => {
    const row: Record<string, string | number> = { date };
    series.forEach((s, i) => {
      const base = valueMaps[i][series[i].dates[0]] ?? 1;
      const val  = valueMaps[i][date];
      if (val !== undefined) row[s.label] = parseFloat(((val / base) * 100).toFixed(2));
    });
    return row;
  });

  // X-axis: show every ~10th label to avoid crowding
  const step = Math.max(1, Math.floor(sortedDates.length / 8));
  const tickFormatter = (_: string, i: number) =>
    i % step === 0 ? sortedDates[i]?.slice(5) ?? "" : "";

  return (
    <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-4 space-y-3">
      {/* Metric cards */}
      <div className={`grid gap-2 grid-cols-${Math.min(series.length, 4)}`}
           style={{ gridTemplateColumns: `repeat(${Math.min(series.length, 4)}, minmax(0,1fr))` }}>
        {series.map((s) => (
          <MetricCard key={s.ticker} s={s} period={result.period} />
        ))}
      </div>

      {/* Normalised line chart */}
      <div>
        <p className="text-xs text-gray-400 mb-2">
          Normalised performance (base = 100) — {result.period}
        </p>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf1" />
            <XAxis
              dataKey="date"
              tickFormatter={tickFormatter}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickLine={false}
              axisLine={{ stroke: "#e8ecf1" }}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}`}
            />
            <Tooltip
              contentStyle={{ fontSize: 12, border: "1px solid #e8ecf1", borderRadius: 8 }}
              formatter={(v: number) => [`${v.toFixed(2)}`, ""]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {series.map((s, i) => (
              <Line
                key={s.ticker}
                type="monotone"
                dataKey={s.label}
                stroke={COLORS[i % COLORS.length]}
                dot={false}
                strokeWidth={1.8}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
