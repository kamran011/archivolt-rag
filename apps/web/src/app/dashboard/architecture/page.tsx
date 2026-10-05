"use client";

import Link from "next/link";
import { useApiResource } from "@/hooks/useApiResource";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { UsageSummary } from "@/lib/types";

interface Stage {
  name: string;
  what: string;
  guard?: string;
}

const INGEST: Stage[] = [
  { name: "Upload", what: "PDF · DOCX · MD · TXT · HTML · CSV · JSON · images (OCR)", guard: "size/type sniffing, safe filenames" },
  { name: "Job queue", what: "Durable Postgres jobs, retries with backoff", guard: "SKIP LOCKED, one job per document" },
  { name: "Parse & chunk", what: "Fixed · structure-aware · semantic · agentic", guard: "injection-like text is flagged, not trusted" },
  { name: "Index", what: "pgvector embeddings, full-text, outline tree, summaries", guard: "org + document ACL stored with every row" },
];

const ANSWER: Stage[] = [
  { name: "Analyze", what: "Intent, entities, evidence requirements" },
  { name: "Retrieve", what: "Semantic · keyword · hybrid (RRF) · tree · summary", guard: "tenant + document ACL inside the SQL" },
  { name: "Rerank & filter", what: "Cross-encoder/LLM rerank, stale, authority, dedupe, per-document cap" },
  { name: "Gates", what: "Evidence + sufficiency gates, bounded expansion ladder", guard: "weak evidence → expand, then abstain" },
  { name: "Generate", what: "Grounded prompt: sources are untrusted data, token-budgeted", guard: "RAG · CAG · hybrid; optional web (labelled external)" },
  { name: "Verify", what: "Claim-by-claim check, conflicts, citations", guard: "unsupported → removed or abstain" },
  { name: "Trace", what: "Stage-by-stage trace, usage ledger, tool audit" },
];

const LAYERS: [string, string][] = [
  ["Tenant isolation", "organization is derived from membership, never from request input; every query filters on it; RLS as a second layer"],
  ["Permission-aware retrieval", "restricted documents + explicit grants resolved in SQL on every path (search, tree, summaries, neighbours, agent, CAG, tools)"],
  ["Prompt-injection defence", "documents are evidence, not instructions; the verifier rejects claims the sources do not support; tools are an allow-list with audit"],
  ["Cost control", "per-org rate limits and daily LLM budget, ledger of every metered call"],
  ["Evaluation", "datasets, strategy/mode matrix runs, leakage and injection metrics with zero tolerance"],
];

// Flat by design: these sit inside one elevated section panel (see <Panel>),
// so the tile itself only needs a hairline border, not its own shadow.
function Box({ stage, n }: { stage: Stage; n: number }) {
  return (
    <li className="rounded-xl border border-border p-3 text-sm">
      <p className="flex items-center gap-2 font-medium text-gray-900">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-50 text-[11px] text-blue-700">
          {n}
        </span>
        {stage.name}
      </p>
      <p className="mt-1 text-xs text-gray-500">{stage.what}</p>
      {stage.guard && (
        <p className="mt-1 flex items-center gap-1 text-xs text-green-700">
          <svg className="h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5l8-3z" />
          </svg>
          {stage.guard}
        </p>
      )}
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900 tabular-nums">{value}</p>
    </div>
  );
}

// Each section gets its own elevated card; this just wraps the label + body.
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-bg-white p-6">
      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-gray-500">{title}</h2>
      {children}
    </section>
  );
}

export default function ArchitecturePage() {
  const { currentOrg } = useOrganization();
  const isAdmin = currentOrg?.role === "owner" || currentOrg?.role === "admin";
  const { knowledgeBases } = useKnowledgeBases();
  const usage = useApiResource<UsageSummary>(
    currentOrg && isAdmin ? "/api/v1/analytics/usage?days=30" : null,
    currentOrg?.id,
    "Failed to load usage",
  );
  const docs = knowledgeBases.reduce((n, kb) => n + kb.document_count, 0);
  const u = usage.data;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">How Ragix works</h1>
        <p className="text-sm text-gray-500">
          The pipeline behind every answer, with the guard at each step — and live numbers from this
          organization.
        </p>
      </div>

      <div className="space-y-6">
        <Panel title="Live (last 30 days)">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Knowledge bases" value={String(knowledgeBases.length)} />
            <Stat label="Documents" value={String(docs)} />
            <Stat label="Answers" value={u ? String(u.total_answers) : "—"} />
            <Stat
              label="Abstention rate"
              value={u?.abstention_rate != null ? `${(u.abstention_rate * 100).toFixed(1)}%` : "—"}
            />
            <Stat label="Avg cost / answer" value={u?.avg_cost_usd != null ? `$${u.avg_cost_usd.toFixed(4)}` : "—"} />
            <Stat label="Avg citations" value={u?.avg_citations != null ? u.avg_citations.toFixed(1) : "—"} />
            <Stat label="Conflicts flagged" value={u ? String(u.conflicts_flagged) : "—"} />
            <Stat label="Deep-research answers" value={u ? String(u.agentic_answers) : "—"} />
          </div>
          {!isAdmin && (
            <p className="mt-3 text-xs text-gray-400">Usage figures are visible to owners and admins.</p>
          )}
          {u && Object.keys(u.strategy_counts).length > 0 && (
            <p className="mt-3 text-xs text-gray-500">
              Strategies used:{" "}
              {Object.entries(u.strategy_counts)
                .map(([k, v]) => `${k} ×${v}`)
                .join(" · ")}
            </p>
          )}
        </Panel>

        <Panel title="Ingestion">
          <ol className="grid gap-3 md:grid-cols-4">
            {INGEST.map((s, i) => (
              <Box key={s.name} stage={s} n={i + 1} />
            ))}
          </ol>
        </Panel>

        <Panel title="Answering">
          <ol className="grid gap-3 md:grid-cols-3">
            {ANSWER.map((s, i) => (
              <Box key={s.name} stage={s} n={i + 1} />
            ))}
          </ol>
        </Panel>

        <Panel title="Safety layers">
          <dl className="divide-y divide-gray-100">
            {LAYERS.map(([k, v]) => (
              <div key={k} className="grid gap-1 py-3 text-sm first:pt-0 last:pb-0 md:grid-cols-[14rem_1fr]">
                <dt className="font-medium text-gray-900">{k}</dt>
                <dd className="text-gray-600">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>

        <p className="text-sm text-gray-500">
          See it in action: <Link className="text-blue-600" href="/dashboard/debug">retrieval debugger</Link>,{" "}
          <Link className="text-blue-600" href="/dashboard/analytics">analytics</Link>,{" "}
          <Link className="text-blue-600" href="/dashboard/evals">evaluation lab</Link>.
        </p>
      </div>
    </div>
  );
}
