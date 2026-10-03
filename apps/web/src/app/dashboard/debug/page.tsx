"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";
import KBSelector from "@/components/chat/KBSelector";
import type { DebugChunk, DebugResponse, DebugStage, RetrievalStrategy } from "@/lib/types";

const STRATEGIES: Array<RetrievalStrategy | "auto"> = [
  "auto",
  "hybrid",
  "semantic",
  "keyword",
  "tree",
];

function verdictClass(verdict: string | null): string {
  if (!verdict) return "text-gray-400";
  if (verdict.startsWith("dropped") || verdict.startsWith("skipped")) return "text-red-600";
  if (verdict === "kept" || verdict === "in context") return "text-green-600";
  return "text-gray-500";
}

function ChunkRow({ chunk, rank }: { chunk: DebugChunk; rank: number }) {
  const muted = chunk.verdict?.startsWith("dropped") || chunk.verdict?.startsWith("skipped");
  return (
    <li className={`px-4 py-3 ${muted ? "bg-gray-50 opacity-70" : ""}`}>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-400 w-5">{rank}</span>
        <span className="font-medium text-gray-900 truncate">{chunk.document_title}</span>
        {chunk.page !== null && <span className="text-gray-400">p.{chunk.page}</span>}
        <span className="ml-auto font-mono text-gray-700">{chunk.score.toFixed(3)}</span>
        {chunk.tokens !== null && <span className="text-gray-400">{chunk.tokens} tok</span>}
        {chunk.authority_tier !== "standard" && (
          <span className="rounded bg-indigo-50 text-indigo-700 px-1.5 py-0.5">
            {chunk.authority_tier}
          </span>
        )}
        {!chunk.is_current && (
          <span className="rounded bg-amber-50 text-amber-700 px-1.5 py-0.5">superseded</span>
        )}
      </div>
      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{chunk.preview}</p>
      {chunk.verdict && (
        <p className={`text-xs mt-1 font-medium ${verdictClass(chunk.verdict)}`}>
          {chunk.verdict}
        </p>
      )}
    </li>
  );
}

function StageCard({ stage }: { stage: DebugStage }) {
  const [open, setOpen] = useState(stage.chunks.length <= 10);
  return (
    <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full cursor-pointer flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-primary"
      >
        <span className="font-medium text-sm text-gray-900 capitalize">{stage.name}</span>
        <span className="text-xs text-gray-400">
          {stage.chunks.length} chunks · {stage.duration_ms} ms
        </span>
        {stage.note && <span className="text-xs text-gray-500 truncate">{stage.note}</span>}
        <span className="ml-auto text-gray-400 text-xs">{open ? "Hide" : "Show"}</span>
      </button>
      {open && stage.chunks.length > 0 && (
        <ul className="divide-y divide-gray-100 border-t border-gray-100">
          {stage.chunks.map((c, i) => (
            <ChunkRow key={`${c.chunk_id}-${i}`} chunk={c} rank={i + 1} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function RetrievalDebuggerPage() {
  const { currentOrg } = useOrganization();
  const [query, setQuery] = useState("");
  const [kbIds, setKbIds] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<RetrievalStrategy | "auto">("auto");
  const [result, setResult] = useState<DebugResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!currentOrg || !query.trim() || kbIds.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      setResult(
        await api.post<DebugResponse>(
          "/api/v1/retrieval/debug",
          {
            query,
            knowledge_base_ids: kbIds,
            strategy: strategy === "auto" ? null : strategy,
          },
          currentOrg.id
        )
      );
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Debug run failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold text-gray-900">Retrieval Debugger</h1>
      <p className="text-gray-500 text-sm mt-1 mb-6">
        See what each retrieval stage kept or dropped for a question, and why. No answer is
        generated.
      </p>

      <form onSubmit={run} className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div>
          <label className="text-xs font-medium text-gray-500">Question</label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="How long do customers have to request a refund?"
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <p className="text-xs font-medium text-gray-500 mb-2">Knowledge bases</p>
          <KBSelector selectedIds={kbIds} onChange={setKbIds} />
        </div>
        <div className="flex items-end gap-4">
          <div>
            <label className="text-xs font-medium text-gray-500">Strategy</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as RetrievalStrategy | "auto")}
              className="mt-1 block rounded-lg border border-gray-300 px-3 py-2 text-sm"
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s === "auto" ? "auto (router decides)" : s}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={loading || !query.trim() || kbIds.length === 0}
            className="cursor-pointer rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "Running…" : "Run"}
          </button>
        </div>
      </form>

      {error && (
        <div className="mt-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 space-y-3">
          <div className="bg-white rounded-xl border border-gray-200 p-4 text-sm grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-gray-500">Route</p>
              <p className="font-medium text-gray-900">{result.route.strategy}</p>
              <p className="text-xs text-gray-500">
                {result.routed ? "router: " : ""}
                {result.route.reason}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Evidence gate</p>
              <p
                className={`font-medium ${result.gate.pass_gate ? "text-green-600" : "text-red-600"}`}
              >
                {result.gate.pass_gate ? "Pass" : "Abstain"}
              </p>
              <p className="text-xs text-gray-500">
                top score {result.gate.top_score.toFixed(2)} · {result.gate.chunk_count} chunks
                {result.gate.reason ? ` · ${result.gate.reason}` : ""}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Final context</p>
              <p className="font-medium text-gray-900">
                {result.final_context_chunks} chunks · {result.final_context_tokens} tokens
              </p>
            </div>
          </div>
          {result.stages.map((s, i) => (
            <StageCard key={`${s.name}-${i}`} stage={s} />
          ))}
        </div>
      )}
    </div>
  );
}
