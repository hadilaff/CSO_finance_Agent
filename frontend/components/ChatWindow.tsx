"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Mic, MicOff, ChevronDown, ChevronUp, Download } from "lucide-react";
import { api, HistoryTurn, ToolCall } from "@/lib/api";
import MarketChart from "./MarketChart";
import ForecastChart from "./ForecastChart";

// ── Simple markdown renderer (bold, bullets, inline code) ────────────────────
function AnswerText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="prose-answer text-sm leading-relaxed">
      {lines.map((line, i) => {
        if (line.startsWith("- ") || line.startsWith("• ")) {
          return (
            <li key={i} className="ml-4 list-disc">
              <InlineMd text={line.slice(2)} />
            </li>
          );
        }
        if (line.trim() === "") return <br key={i} />;
        return (
          <p key={i}>
            <InlineMd text={line} />
          </p>
        );
      })}
    </div>
  );
}

function InlineMd({ text }: { text: string }) {
  // bold (**text**) and inline code (`text`)
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**"))
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("`") && part.endsWith("`"))
          return (
            <code key={i} className="bg-gray-100 px-1 rounded text-xs font-mono">
              {part.slice(1, -1)}
            </code>
          );
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ── Tool call expander ────────────────────────────────────────────────────────
function ToolCallExpander({ toolCalls }: { toolCalls: ToolCall[] }) {
  const [open, setOpen] = useState(false);
  if (!toolCalls.length) return null;
  return (
    <div className="mt-2 border border-gray-200 rounded-lg overflow-hidden text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-gray-500 transition-colors"
      >
        <span>Tool calls ({toolCalls.length})</span>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {toolCalls.map((tc, i) => (
            <div key={i} className="px-3 py-2 space-y-1">
              <p className="font-mono font-semibold text-accent">{tc.name}</p>
              <p className="text-gray-400">
                args: {JSON.stringify(tc.args)}
              </p>
              <pre className="bg-gray-50 rounded p-2 text-xs overflow-x-auto max-h-32">
                {JSON.stringify(tc.result, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Deck download button (surfaces from tool_calls) ───────────────────────────
function DeckButton({ toolCalls }: { toolCalls: ToolCall[] }) {
  const deckCall = toolCalls.find((tc) => tc.name === "generate_deck");
  if (!deckCall) return null;
  const result = deckCall.result as Record<string, string> | null;
  const deckId = result?.deck_id;
  if (!deckId) return null;
  return (
    <a
      href={api.deckDownloadUrl(deckId)}
      download={result?.filename ?? "deck.pptx"}
      className="inline-flex items-center gap-2 mt-2 px-3 py-1.5 bg-navy text-white text-xs rounded-lg hover:bg-navy/90 transition-colors"
    >
      <Download size={13} />
      Download {result?.filename ?? "deck.pptx"}
    </a>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
interface Message extends HistoryTurn {
  tool_calls?: ToolCall[];
}

function MessageBubble({ msg, index }: { msg: Message; index: number }) {
  const isUser = msg.role === "user";

  // Find market / forecast tool calls for inline charts
  const marketCall = msg.tool_calls?.find(
    (tc) => tc.name === "market_data" || tc.name === "macro_data"
  );
  const forecastCall = msg.tool_calls?.find(
    (tc) => tc.name === "forecast_market"
  );

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold mr-2 mt-1 shrink-0">
          AI
        </div>
      )}

      <div className={`max-w-[80%] space-y-2`}>
        <div
          className={`px-4 py-3 rounded-2xl text-sm ${
            isUser
              ? "bg-accent text-white rounded-tr-sm"
              : "bg-white border border-gray-200 text-gray-800 rounded-tl-sm shadow-sm"
          }`}
        >
          {isUser ? (
            <p>{msg.text}</p>
          ) : (
            <AnswerText text={msg.text} />
          )}
        </div>

        {!isUser && msg.tool_calls && (
          <>
            <DeckButton toolCalls={msg.tool_calls} />
            {marketCall && (
              <MarketChart
                result={marketCall.result as any}
                keyPrefix={`msg-${index}`}
              />
            )}
            {forecastCall && (
              <ForecastChart
                args={forecastCall.args as any}
                summary={forecastCall.result as any}
                keyPrefix={`msg-${index}`}
              />
            )}
            <ToolCallExpander toolCalls={msg.tool_calls} />
          </>
        )}
      </div>

      {isUser && (
        <div className="w-7 h-7 rounded-full bg-gray-300 flex items-center justify-center text-gray-600 text-xs font-bold ml-2 mt-1 shrink-0">
          U
        </div>
      )}
    </div>
  );
}

// ── Quick-start prompts ───────────────────────────────────────────────────────
const QUICK_PROMPTS = [
  "Forecast Gold price for the next 30 days.",
  "How is DIFC Dubai positioning itself for digital assets?",
  "Summarise the strategic priorities in my uploaded documents.",
];

// ── Main ChatWindow ───────────────────────────────────────────────────────────
export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const mediaRef  = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text: string) {
    if (!text.trim() || loading) return;
    setError(null);

    const userMsg: Message = { role: "user", text };
    const history: HistoryTurn[] = messages.map((m) => ({
      role: m.role,
      text: m.text,
    }));

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await api.chat(text, history);
      const assistantMsg: Message = {
        role:       "assistant",
        text:       res.answer,
        tool_calls: res.tool_calls,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      setError(e.message ?? "Request failed.");
    } finally {
      setLoading(false);
    }
  }

  // Voice recording
  async function toggleRecording() {
    if (recording) {
      mediaRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        try {
          const text = await api.transcribe(blob, "audio.webm");
          if (text) setInput(text);
        } catch {
          setError("Transcription failed.");
        }
      };
      recorder.start();
      mediaRef.current = recorder;
      setRecording(true);
    } catch {
      setError("Microphone access denied.");
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full space-y-6 text-center">
            <div>
              <h2 className="text-xl font-semibold text-navy mb-1">
                CSO Intelligence Agent
              </h2>
              <p className="text-sm text-gray-500">
                RAG · Web search · Market data · Forecasting
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 w-full max-w-lg">
              {QUICK_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => send(p)}
                  className="text-left px-4 py-3 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 hover:border-accent hover:text-accent transition-colors shadow-sm"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} index={i} />
        ))}

        {loading && (
          <div className="flex justify-start mb-4">
            <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center text-white text-xs font-bold mr-2 mt-1 shrink-0">
              AI
            </div>
            <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
              <div className="flex space-x-1 items-center h-4">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-2 h-2 bg-accent rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="mx-auto max-w-lg mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
            ⚠️ {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-gray-200 bg-white px-4 py-3">
        <div className="flex items-end gap-2 max-w-4xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="Ask about markets, competitors, your documents…"
            rows={1}
            className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-accent transition-colors max-h-40 overflow-y-auto"
          />
          <button
            onClick={toggleRecording}
            className={`p-2.5 rounded-xl transition-colors ${
              recording
                ? "bg-red-500 text-white animate-pulse"
                : "bg-gray-100 text-gray-500 hover:bg-gray-200"
            }`}
            title={recording ? "Stop recording" : "Voice input"}
          >
            {recording ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || loading}
            className="p-2.5 bg-accent text-white rounded-xl hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
