"use client";

import { useCallback, useEffect, useState } from "react";
import { Upload, X, FileText, CheckCircle, AlertCircle, Loader2, Trash2 } from "lucide-react";
import { api, IndexResult } from "@/lib/api";

const ACCEPTED = ".pdf,.docx,.pptx,.txt,.md";

export default function FileUpload() {
  const [sources,    setSources]    = useState<string[]>([]);
  const [dragging,   setDragging]   = useState(false);
  const [files,      setFiles]      = useState<File[]>([]);
  const [indexing,   setIndexing]   = useState(false);
  const [results,    setResults]    = useState<IndexResult[] | null>(null);
  const [error,      setError]      = useState<string | null>(null);

  async function loadSources() {
    try {
      const data = await api.sources();
      setSources(data.sources);
    } catch { /* ignore */ }
  }

  useEffect(() => { loadSources(); }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files);
    setFiles((prev) => [...prev, ...dropped]);
  }, []);

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    setFiles((prev) => [...prev, ...picked]);
    e.target.value = "";
  }

  function removeFile(i: number) {
    setFiles((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function indexFiles() {
    if (!files.length || indexing) return;
    setIndexing(true);
    setError(null);
    setResults(null);
    try {
      const data = await api.indexDocuments(files);
      setResults(data.results);
      setFiles([]);
      await loadSources();
    } catch (e: any) {
      setError(e.message ?? "Indexing failed.");
    } finally {
      setIndexing(false);
    }
  }

  async function clearAll() {
    if (!confirm("Clear the entire document index? This cannot be undone.")) return;
    try {
      await api.clearIndex();
      setSources([]);
      setResults(null);
    } catch (e: any) {
      setError(e.message ?? "Clear failed.");
    }
  }

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-navy">📁 Institutional Knowledge</h2>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-xl p-5 text-center transition-colors ${
          dragging
            ? "border-accent bg-accent/5"
            : "border-gray-200 hover:border-accent/50 bg-white"
        }`}
      >
        <Upload size={22} className={`mx-auto mb-2 ${dragging ? "text-accent" : "text-gray-300"}`} />
        <p className="text-xs text-gray-500">
          Drag & drop files here, or{" "}
          <label className="text-accent cursor-pointer hover:underline">
            browse
            <input
              type="file"
              multiple
              accept={ACCEPTED}
              onChange={onFileInput}
              className="hidden"
            />
          </label>
        </p>
        <p className="text-xs text-gray-400 mt-1">PDF · DOCX · PPTX · TXT · MD</p>
      </div>

      {/* Staged files */}
      {files.length > 0 && (
        <div className="space-y-1">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2">
              <FileText size={14} className="text-accent shrink-0" />
              <span className="text-xs text-gray-700 flex-1 truncate">{f.name}</span>
              <span className="text-xs text-gray-400">
                {(f.size / 1024).toFixed(0)} KB
              </span>
              <button onClick={() => removeFile(i)} className="text-gray-400 hover:text-red-500">
                <X size={13} />
              </button>
            </div>
          ))}
          <button
            onClick={indexFiles}
            disabled={indexing}
            className="w-full mt-1 flex items-center justify-center gap-2 py-2 bg-accent text-white text-xs rounded-lg hover:bg-accent/90 disabled:opacity-50 transition-colors"
          >
            {indexing ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
            {indexing ? "Indexing…" : `Index ${files.length} file${files.length > 1 ? "s" : ""}`}
          </button>
        </div>
      )}

      {/* Index results */}
      {results && (
        <div className="space-y-1">
          {results.map((r, i) => (
            <div key={i} className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-gray-50">
              {r.status === "ok"
                ? <CheckCircle size={13} className="text-green-500 shrink-0" />
                : <AlertCircle size={13} className="text-red-500 shrink-0" />}
              <span className="truncate text-gray-700">{r.filename}</span>
              {r.status === "ok"
                ? <span className="ml-auto text-gray-400">{r.chunks} chunks</span>
                : <span className="ml-auto text-red-400">{r.detail}</span>}
            </div>
          ))}
        </div>
      )}

      {error && (
        <p className="text-xs text-red-500 px-1">⚠️ {error}</p>
      )}

      {/* Indexed sources list */}
      {sources.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-500 font-medium">
              Indexed sources ({sources.length})
            </p>
            <button
              onClick={clearAll}
              className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600 transition-colors"
            >
              <Trash2 size={11} /> Clear all
            </button>
          </div>
          <div className="space-y-0.5 max-h-36 overflow-y-auto">
            {sources.map((s) => (
              <div key={s} className="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-gray-50">
                <FileText size={11} className="text-accent shrink-0" />
                <span className="text-xs text-gray-600 truncate">{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
