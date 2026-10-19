/**
 * API client — all calls to the FastAPI backend go through here.
 * Base URL is read from NEXT_PUBLIC_API_URL (set in .env.local).
 */

const BASE = "/api/proxy";

async function req<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface HistoryTurn {
  role: "user" | "assistant";
  text: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: unknown;
}

export interface ChatResponse {
  answer: string;
  tool_calls: ToolCall[];
}

export interface SeriesData {
  ticker: string;
  label: string;
  dates: string[];
  values: number[];
  currency: string;
  pct_change: number;
  latest: number;
}

export interface MarketResponse {
  period: string;
  interval: string;
  series: SeriesData[];
  errors: Record<string, string>;
}

export interface MacroResponse {
  series: SeriesData[];
  errors: Record<string, string>;
}

export interface ForecastResponse {
  ticker: string;
  label: string;
  history_period: string;
  forecast_days: number;
  currency: string;
  last_actual: number;
  fc_end_value: number;
  fc_pct_change: number;
  trend_direction: "upward" | "downward" | "flat";
  hist_dates: string[];
  hist_values: number[];
  fc_dates: string[];
  fc_yhat: number[];
  fc_lower: number[];
  fc_upper: number[];
  trend_dates: string[];
  trend_values: number[];
}

export interface BriefingSection {
  key: string;
  title: string;
  icon: string;
  answer: string;
}

export interface BriefingResponse {
  date: string;
  generated_at: string;
  sections: BriefingSection[];
}

export interface IndexResult {
  filename: string;
  chunks?: number;
  status: "ok" | "error";
  detail?: string;
}

// ── API functions ─────────────────────────────────────────────────────────────

export const api = {
  health: () =>
    req<{ status: string }>("/api/health"),

  chat: (message: string, history: HistoryTurn[]) =>
    req<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),

  indexDocuments: async (files: File[]): Promise<{ results: IndexResult[] }> => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const res = await fetch(`${BASE}/api/index`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Index error ${res.status}`);
    return res.json();
  },

  sources: () =>
    req<{ sources: string[] }>("/api/sources"),

  clearIndex: () =>
    req<{ status: string }>("/api/index", { method: "DELETE" }),

  market: (tickers: string[], period = "3mo") =>
    req<MarketResponse>("/api/market", {
      method: "POST",
      body: JSON.stringify({ tickers, period }),
    }),

  macro: (series_ids: string[], period = "1y") =>
    req<MacroResponse>("/api/macro", {
      method: "POST",
      body: JSON.stringify({ series_ids, period }),
    }),

  forecast: (ticker: string, periods = 30, history_period = "2y") =>
    req<ForecastResponse>("/api/forecast", {
      method: "POST",
      body: JSON.stringify({ ticker, periods, history_period }),
    }),

  generateBriefing: () =>
    req<BriefingResponse>("/api/briefing/generate", { method: "POST" }),

  getBriefing: (date: string) =>
    req<BriefingResponse>(`/api/briefing/${date}`),

  buildBriefingDeck: (date: string) =>
    req<{ deck_id: string; filename: string }>("/api/briefing/deck", {
      method: "POST",
      body: JSON.stringify({ date }),
    }),

  deckDownloadUrl: (deck_id: string) =>
    `${BASE}/api/deck/${deck_id}`,

  transcribe: async (audioBlob: Blob, filename = "audio.wav"): Promise<string> => {
    const form = new FormData();
    form.append("file", audioBlob, filename);
    const res = await fetch(`${BASE}/api/transcribe`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Transcription error ${res.status}`);
    const data = await res.json();
    return data.text ?? "";
  },
};
