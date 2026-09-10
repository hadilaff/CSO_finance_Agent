"use client";

import { useState, useEffect } from "react";
import {
  MessageSquare,
  BarChart2,
  FileText,
  Calendar,
  LogOut,
  Menu,
  X,
  Activity,
} from "lucide-react";
import ChatWindow from "@/components/ChatWindow";
import MarketDashboard from "@/components/MarketDashboard";
import FileUpload from "@/components/FileUpload";
import BriefingPanel from "@/components/BriefingPanel";
import { api } from "@/lib/api";

// ── Auth gate ─────────────────────────────────────────────────────────────────
const APP_PASSWORD = process.env.NEXT_PUBLIC_APP_PASSWORD ?? "";

function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const [pwd, setPwd]     = useState("");
  const [error, setError] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pwd === APP_PASSWORD || APP_PASSWORD === "") {
      onLogin();
    } else {
      setError(true);
      setPwd("");
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-sm border border-gray-200 p-8 space-y-6">
        <div className="text-center">
          <div className="w-12 h-12 bg-navy rounded-xl flex items-center justify-center mx-auto mb-3">
            <Activity size={24} className="text-white" />
          </div>
          <h1 className="text-xl font-semibold text-navy">CSO Intelligence</h1>
          <p className="text-sm text-gray-500 mt-1">Strategic Intelligence Agent</p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <input
            type="password"
            value={pwd}
            onChange={(e) => { setPwd(e.target.value); setError(false); }}
            placeholder="Enter password"
            autoFocus
            className={`w-full px-4 py-2.5 border rounded-xl text-sm focus:outline-none focus:border-accent transition-colors ${
              error ? "border-red-400 bg-red-50" : "border-gray-300"
            }`}
          />
          {error && (
            <p className="text-xs text-red-500">Incorrect password.</p>
          )}
          <button
            type="submit"
            className="w-full py-2.5 bg-navy text-white rounded-xl text-sm font-medium hover:bg-navy/90 transition-colors"
          >
            Sign in
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Nav items ─────────────────────────────────────────────────────────────────
type View = "chat" | "market" | "briefing" | "docs";

const NAV: { id: View; label: string; icon: React.ReactNode }[] = [
  { id: "chat",     label: "Chat",     icon: <MessageSquare size={18} /> },
  { id: "market",   label: "Markets",  icon: <BarChart2 size={18} /> },
  { id: "briefing", label: "Briefing", icon: <Calendar size={18} /> },
  { id: "docs",     label: "Documents",icon: <FileText size={18} /> },
];

// ── Main app shell ────────────────────────────────────────────────────────────
function AppShell() {
  const [view,          setView]          = useState<View>("chat");
  const [sidebarOpen,   setSidebarOpen]   = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  // Health-check the backend on mount
  useEffect(() => {
    api.health()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, []);

  function logout() {
    if (typeof window !== "undefined") {
      sessionStorage.removeItem("authed");
      window.location.reload();
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      {/* ── Top navbar ─────────────────────────────────────────────────────── */}
      <header className="h-14 bg-white border-b border-gray-200 flex items-center px-4 gap-3 shrink-0 z-20">
        {/* Mobile menu toggle */}
        <button
          className="md:hidden p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
          onClick={() => setSidebarOpen((o) => !o)}
        >
          {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-navy rounded-lg flex items-center justify-center">
            <Activity size={15} className="text-white" />
          </div>
          <span className="font-semibold text-navy text-sm hidden sm:block">
            CSO Intelligence
          </span>
        </div>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-1 ml-4">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => setView(n.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                view === n.id
                  ? "bg-accent/10 text-accent font-medium"
                  : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
              }`}
            >
              {n.icon}
              {n.label}
            </button>
          ))}
        </nav>

        {/* Right side: status + logout */}
        <div className="ml-auto flex items-center gap-3">
          {backendOnline !== null && (
            <div className="hidden sm:flex items-center gap-1.5 text-xs">
              <div
                className={`w-1.5 h-1.5 rounded-full ${
                  backendOnline ? "bg-green-500" : "bg-red-400"
                }`}
              />
              <span className="text-gray-400">
                {backendOnline ? "Backend online" : "Backend offline"}
              </span>
            </div>
          )}
          <button
            onClick={logout}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
          >
            <LogOut size={14} />
            <span className="hidden sm:block">Sign out</span>
          </button>
        </div>
      </header>

      {/* ── Body ───────────────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Mobile sidebar overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/30 z-10 md:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Mobile sidebar */}
        <aside
          className={`fixed top-14 left-0 bottom-0 w-56 bg-white border-r border-gray-200 z-10 transform transition-transform md:hidden ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <nav className="p-3 space-y-1">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => { setView(n.id); setSidebarOpen(false); }}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                  view === n.id
                    ? "bg-accent/10 text-accent font-medium"
                    : "text-gray-600 hover:bg-gray-50"
                }`}
              >
                {n.icon}
                {n.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-hidden">
          {/* Backend offline banner */}
          {backendOnline === false && (
            <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-xs text-red-700 text-center">
              ⚠️ Backend is unreachable. Check that the FastAPI server is running at{" "}
              <code className="font-mono bg-red-100 px-1 rounded">
                {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
              </code>
            </div>
          )}

          {/* Chat — full-height, no padding */}
          {view === "chat" && (
            <div className="h-[calc(100vh-3.5rem)] flex flex-col">
              <ChatWindow />
            </div>
          )}

          {/* Market dashboard */}
          {view === "market" && (
            <div className="h-[calc(100vh-3.5rem)] overflow-y-auto p-6">
              <MarketDashboard />
            </div>
          )}

          {/* Briefing */}
          {view === "briefing" && (
            <div className="h-[calc(100vh-3.5rem)] overflow-y-auto p-6 max-w-3xl mx-auto">
              <BriefingPanel />
            </div>
          )}

          {/* Documents */}
          {view === "docs" && (
            <div className="h-[calc(100vh-3.5rem)] overflow-y-auto p-6 max-w-xl mx-auto">
              <FileUpload />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

// ── Root: auth wrapper ────────────────────────────────────────────────────────
export default function Home() {
  const [authed, setAuthed] = useState(false);

  // Persist auth in sessionStorage so refreshing doesn't log out
  useEffect(() => {
    if (typeof window !== "undefined") {
      setAuthed(sessionStorage.getItem("authed") === "1" || APP_PASSWORD === "");
    }
  }, []);

  function handleLogin() {
    sessionStorage.setItem("authed", "1");
    setAuthed(true);
  }

  if (!authed) return <LoginScreen onLogin={handleLogin} />;
  return <AppShell />;
}
