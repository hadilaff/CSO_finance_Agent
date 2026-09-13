"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, RefreshCw, BarChart2, Loader2 } from "lucide-react";
import { api, BriefingResponse, BriefingSection } from "@/lib/api";

function SectionCard({ section }: { section: BriefingSection }) {
  const [open, setOpen] = useState(false);
  const lines = section.answer.split("\n");

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white shadow-sm">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
      >
        <span className="text-sm font-semibold text-navy">
          {section.icon}&nbsp;&nbsp;{section.title}
        </span>
        {open ? <ChevronUp size={15} className="text-gray-400" /> : <ChevronDown size={15} className="text-gray-400" />}
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-100 text-sm text-gray-700 space-y-1">
          {lines.map((line, i) => {
            if (line.startsWith("- ") || line.startsWith("• "))
              return <li key={i} className="ml-4 list-disc leading-relaxed">{line.slice(2)}</li>;
            if (line.trim() === "") return null;
            return <p key={i} className="leading-relaxed">{line}</p>;
          })}
        </div>
      )}
    </div>
  );
}

export default function BriefingPanel() {
  const today = new Date().toISOString().slice(0, 10);

  const [briefing,    setBriefing]    = useState<BriefingResponse | null>(null);
  const [loading,     setLoading]     = useState(false);
  const [deckLoading, setDeckLoading] = useState(false);
  const [deckUrl,     setDeckUrl]     = useState<string | null>(null);
  const [deckName,    setDeckName]    = useState("briefing.pptx");
  const [error,       setError]       = useState<string | null>(null);

  async function loadToday() {
    setError(null);
    try {
      const data = await api.getBriefing(today);
      setBriefing(data);
    } catch {
      // 404 means not generated yet — that's fine
    }
  }

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.generateBriefing();
      setBriefing(data);
    } catch (e: any) {
      setError(e.message ?? "Failed to generate briefing.");
    } finally {
      setLoading(false);
    }
  }

  async function buildDeck() {
    if (!briefing) return;
    setDeckLoading(true);
    setError(null);
    try {
      const info = await api.buildBriefingDeck(today);
      setDeckUrl(api.deckDownloadUrl(info.deck_id));
      setDeckName(info.filename);
    } catch (e: any) {
      setError(e.message ?? "Deck generation failed.");
    } finally {
      setDeckLoading(false);
    }
  }

  // Load on first render
  useState(() => { loadToday(); });

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-navy">
            📅 Today's Strategic Briefing
          </h2>
          {briefing && (
            <p className="text-xs text-gray-400 mt-0.5">
              Generated {briefing.generated_at}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={generate}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-navy text-white rounded-lg hover:bg-navy/90 disabled:opacity-50 transition-colors"
          >
            {loading
              ? <Loader2 size={13} className="animate-spin" />
              : <RefreshCw size={13} />}
            {briefing ? "Refresh" : "Generate"}
          </button>
          {briefing && (
            <button
              onClick={buildDeck}
              disabled={deckLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent text-white rounded-lg hover:bg-accent/90 disabled:opacity-50 transition-colors"
            >
              {deckLoading
                ? <Loader2 size={13} className="animate-spin" />
                : <BarChart2 size={13} />}
              Build deck
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
          ⚠️ {error}
        </div>
      )}

      {/* Deck download */}
      {deckUrl && (
        <a
          href={deckUrl}
          download={deckName}
          className="flex items-center gap-2 px-3 py-2 bg-green-50 border border-green-200 rounded-lg text-xs text-green-700 hover:bg-green-100 transition-colors"
        >
          ⬇ Download {deckName}
        </a>
      )}

      {/* Sections */}
      {briefing ? (
        <div className="space-y-2">
          {briefing.sections.map((s) => (
            <SectionCard key={s.key} section={s} />
          ))}
        </div>
      ) : (
        !loading && (
          <div className="text-center py-8 text-sm text-gray-400 border border-dashed border-gray-200 rounded-xl">
            No briefing for today yet.
            <br />
            Click <span className="text-navy font-medium">Generate</span> to create one.
          </div>
        )
      )}

      {loading && (
        <div className="text-center py-8 text-sm text-gray-400 animate-pulse">
          Generating 6 intelligence areas in parallel…
          <br />
          <span className="text-xs">This takes 1–2 minutes</span>
        </div>
      )}
    </div>
  );
}
