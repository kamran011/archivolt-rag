"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import KBSelector from "@/components/chat/KBSelector";
import type {
  AnswerMode,
  EvalDataset,
  EvalRun,
  EvalRunConfig,
  MetricDelta,
  RetrievalStrategyName,
} from "@/lib/types";

const STRATEGIES: RetrievalStrategyName[] = ["hybrid", "semantic", "keyword", "tree", "summary"];
const MODES: { id: AnswerMode; label: string }[] = [
  { id: "rag", label: "RAG" },
  { id: "cag", label: "CAG" },
  { id: "hybrid", label: "CAG→RAG" },
];

// metric -> [label, higher-is-better, format]
const METRICS: [string, string, boolean, "pct" | "ms" | "usd"][] = [
  ["hit_rate", "Hit rate", true, "pct"],
  ["recall", "Recall", true, "pct"],
  ["mrr", "MRR", true, "pct"],
  ["ndcg", "nDCG", true, "pct"],
  ["faithfulness", "Faithfulness", true, "pct"],
  ["keyword_coverage", "Keyword coverage", true, "pct"],
  ["abstention_accuracy", "Abstention accuracy", true, "pct"],
  ["false_answer_rate", "False answers", false, "pct"],
  ["false_abstain_rate", "Incorrect refusals", false, "pct"],
  ["leakage_rate", "Leakage", false, "pct"],
  ["injection_success_rate", "Injection success", false, "pct"],
  ["avg_latency_ms", "Latency", false, "ms"],
  ["avg_cost_usd", "Cost / answer", false, "usd"],
];

function fmt(v: number | null | undefined, kind: "pct" | "ms" | "usd"): string {
  if (v === null || v === undefined) return "—";
  if (kind === "pct") return `${(v * 100).toFixed(1)}%`;
  if (kind === "ms") return `${Math.round(v)} ms`;
  return `$${v.toFixed(4)}`;
}

function label(c: EvalRunConfig): string {
  const parts: string[] = [c.strategy, c.mode.toUpperCase()];
  if (c.agentic) parts.push("agentic");
  if (c.retrieval_only) parts.push("retrieval-only");
  if (c.access === "admin") parts.push("as admin");
  return parts.join(" · ");
}

export default function EvalLabPage() {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id;
  const isAdmin = currentOrg?.role === "owner" || currentOrg?.role === "admin";

  const datasets = useApiResource<EvalDataset[]>(
    orgId && isAdmin ? "/api/v1/evals/datasets" : null,
    orgId,
    "Failed to load datasets",
  );
  const runs = useApiResource<EvalRun[]>(
    orgId && isAdmin ? "/api/v1/evals/runs" : null,
    orgId,
    "Failed to load runs",
  );

  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [jsonl, setJsonl] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [kbIds, setKbIds] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<RetrievalStrategyName[]>(["hybrid"]);
  const [modes, setModes] = useState<AnswerMode[]>(["rag"]);
  const [asAdmin, setAsAdmin] = useState(false);
  const [retrievalOnly, setRetrievalOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [deltas, setDeltas] = useState<MetricDelta[] | null>(null);

  const active = (runs.data ?? []).some((r) => r.status === "queued" || r.status === "running");
  const reloadRuns = runs.refresh;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => void reloadRuns(), 4000);
    return () => clearInterval(t);
  }, [active, reloadRuns]);

  if (!currentOrg) return <p className="text-sm text-gray-500">No organization selected.</p>;
  if (!isAdmin) {
    return (
      <p className="text-sm text-gray-500">The evaluation lab is available to owners and admins.</p>
    );
  }
  const org = currentOrg;
  const configCount = strategies.length * modes.length;
  const selectedDataset = datasetId || datasets.data?.[0]?.id || "";

  function toggle<T>(list: T[], v: T): T[] {
    return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
  }

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function createDataset() {
    await api.post("/api/v1/evals/datasets", { name, jsonl }, org.id);
    setName("");
    setJsonl("");
    await datasets.refresh();
  }

  async function startRuns() {
    const configs: Partial<EvalRunConfig>[] = strategies.flatMap((strategy) =>
      modes.map((mode) => ({
        strategy,
        mode,
        retrieval_only: retrievalOnly,
        access: asAdmin ? ("admin" as const) : ("restricted" as const),
      })),
    );
    await api.post(
      "/api/v1/evals/runs",
      { dataset_id: selectedDataset, knowledge_base_ids: kbIds, configs },
      org.id,
    );
    await runs.refresh();
  }

  async function compareSelected() {
    const [a, b] = picked;
    setDeltas(
      await api.get<MetricDelta[]>(`/api/v1/evals/compare?baseline=${a}&candidate=${b}`, org.id),
    );
  }

  const done = (runs.data ?? []).filter((r) => r.status === "succeeded");
  const pickedRuns = picked
    .map((id) => done.find((r) => r.id === id))
    .filter((r): r is EvalRun => !!r);

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">Evaluation lab</h1>
        <p className="text-sm text-gray-500">
          Run a dataset against different strategies and answer modes, then compare quality, safety
          and cost.
        </p>
      </div>
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <section className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-medium text-gray-900 mb-2">1 · Dataset</h2>
        <p className="text-xs text-gray-500 mb-3">
          JSONL, one case per line: <code>id</code>, <code>question</code>,{" "}
          <code>gold_documents</code> or <code>gold_passages</code>, optional{" "}
          <code>expected_keywords</code>, <code>should_abstain</code>,{" "}
          <code>forbidden_documents</code> (leak check) and <code>canary</code> (injection check).
        </p>
        {(datasets.data ?? []).length > 0 && (
          <p className="text-xs text-gray-600 mb-3">
            Existing: {(datasets.data ?? []).map((d) => `${d.name} (${d.case_count})`).join(", ")}
          </p>
        )}
        <div className="grid gap-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Dataset name"
            className="rounded-md border border-gray-200 px-2 py-1.5 text-sm"
          />
          <textarea
            value={jsonl}
            onChange={(e) => setJsonl(e.target.value)}
            rows={5}
            placeholder='{"id":"q1","question":"…","gold_documents":["Refund Policy"]}'
            className="rounded-md border border-gray-200 px-2 py-1.5 text-xs font-mono"
          />
          <div className="flex items-center gap-3">
            <input
              type="file"
              accept=".jsonl,.txt,application/json"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setJsonl(await f.text());
                  if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
                }
              }}
              className="text-xs"
            />
            <button
              disabled={busy || !name.trim() || !jsonl.trim()}
              onClick={() => void guard(createDataset)}
              className="cursor-pointer rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Save dataset
            </button>
          </div>
        </div>
      </section>

      <section className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-medium text-gray-900 mb-3">2 · Run</h2>
        <div className="grid gap-3 text-sm">
          <label className="text-xs text-gray-500">
            Dataset
            <select
              value={selectedDataset}
              onChange={(e) => setDatasetId(e.target.value)}
              className="mt-1 block rounded-md border border-gray-200 px-2 py-1.5 text-sm"
            >
              {(datasets.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.case_count} cases)
                </option>
              ))}
            </select>
          </label>
          <div>
            <p className="text-xs text-gray-500 mb-1">Knowledge bases</p>
            <KBSelector selectedIds={kbIds} onChange={setKbIds} />
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            <fieldset>
              <legend className="text-xs text-gray-500 mb-1">Retrieval strategies</legend>
              {STRATEGIES.map((s) => (
                <label key={s} className="mr-3 inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={strategies.includes(s)}
                    onChange={() => setStrategies(toggle(strategies, s))}
                  />
                  {s}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend className="text-xs text-gray-500 mb-1">Answer modes</legend>
              {MODES.map((m) => (
                <label key={m.id} className="mr-3 inline-flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={modes.includes(m.id)}
                    onChange={() => setModes(toggle(modes, m.id))}
                  />
                  {m.label}
                </label>
              ))}
            </fieldset>
          </div>
          <div className="flex flex-wrap gap-6">
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={asAdmin}
                onChange={(e) => setAsAdmin(e.target.checked)}
              />
              Evaluate as admin (default: least-privileged caller, which exposes leaks)
            </label>
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={retrievalOnly}
                onChange={(e) => setRetrievalOnly(e.target.checked)}
              />
              Retrieval only (no LLM cost)
            </label>
          </div>
          <div className="flex items-center gap-3">
            <button
              disabled={
                busy || !selectedDataset || kbIds.length === 0 || configCount === 0 || configCount > 8
              }
              onClick={() => void guard(startRuns)}
              className="cursor-pointer rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Start {configCount} run{configCount === 1 ? "" : "s"}
            </button>
            {configCount > 8 && <span className="text-xs text-red-600">At most 8 at a time.</span>}
            {!retrievalOnly && (
              <span className="text-xs text-gray-400">Answer runs call the LLM and cost money.</span>
            )}
          </div>
        </div>
      </section>

      <section className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium text-gray-900">3 · Runs</h2>
          <button
            disabled={picked.length !== 2 || busy}
            onClick={() => void guard(compareSelected)}
            className="cursor-pointer rounded-md border border-gray-300 px-3 py-1 text-xs disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Check regressions (first = baseline)
          </button>
        </div>
        {runs.error && <p className="text-sm text-red-600">{runs.error}</p>}
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-gray-500">
            <tr>
              <th className="w-8" />
              <th className="text-left py-2 font-medium">Configuration</th>
              <th className="text-left py-2 font-medium">Status</th>
              <th className="text-left py-2 font-medium">Cases</th>
              <th className="text-left py-2 font-medium">Started</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {(runs.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>
                  <input
                    type="checkbox"
                    disabled={r.status !== "succeeded"}
                    checked={picked.includes(r.id)}
                    onChange={() => {
                      setDeltas(null);
                      setPicked(toggle(picked, r.id).slice(-4));
                    }}
                  />
                </td>
                <td className="py-2">{label(r.config)}</td>
                <td className="py-2">
                  <span
                    className={
                      r.status === "failed"
                        ? "text-red-600"
                        : r.status === "succeeded"
                          ? "text-green-700"
                          : "text-gray-500"
                    }
                  >
                    {r.status}
                  </span>
                  {r.error && <span className="block text-xs text-red-500">{r.error}</span>}
                </td>
                <td className="py-2 text-gray-500">
                  {r.total_cases ?? "—"}
                  {r.failed_cases ? ` (${r.failed_cases} errored)` : ""}
                </td>
                <td className="py-2 text-gray-500">{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(runs.data ?? []).length === 0 && !runs.loading && (
          <p className="text-sm text-gray-400 py-3">No runs yet.</p>
        )}
      </section>

      {pickedRuns.length > 0 && (
        <section className="bg-white rounded-xl border border-gray-200 p-5 overflow-x-auto">
          <h2 className="font-medium text-gray-900 mb-3">Comparison</h2>
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500">
              <tr>
                <th className="text-left py-2 font-medium">Metric</th>
                {pickedRuns.map((r) => (
                  <th key={r.id} className="text-right py-2 font-medium pl-4">
                    {label(r.config)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {METRICS.map(([key, title, higher, kind]) => {
                const values = pickedRuns.map((r) => r.summary?.[key] ?? null);
                const present = values.filter((v): v is number => v !== null);
                if (present.length === 0) return null;
                const best = higher ? Math.max(...present) : Math.min(...present);
                return (
                  <tr key={key}>
                    <td className="py-1.5 text-gray-700">{title}</td>
                    {values.map((v, i) => (
                      <td
                        key={pickedRuns[i].id}
                        className={`py-1.5 text-right pl-4 tabular-nums ${
                          v !== null && v === best && present.length > 1
                            ? "font-semibold text-green-700"
                            : "text-gray-600"
                        }`}
                      >
                        {fmt(v, kind)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {deltas && (
            <div className="mt-4 border-t border-gray-100 pt-3">
              <h3 className="text-sm font-medium text-gray-900 mb-2">
                Regressions vs. {label(pickedRuns[0].config)}
              </h3>
              {deltas.filter((d) => d.regressed).length === 0 ? (
                <p className="text-sm text-green-700">No regressions.</p>
              ) : (
                <ul className="text-sm text-red-600 space-y-0.5">
                  {deltas
                    .filter((d) => d.regressed)
                    .map((d) => (
                      <li key={d.metric}>
                        {d.metric}: {d.baseline} → {d.candidate} ({d.delta > 0 ? "+" : ""}
                        {d.delta})
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
