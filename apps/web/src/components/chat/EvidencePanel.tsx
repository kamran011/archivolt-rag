"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/hooks/useChat";
import { safeHttpUrl } from "@/lib/safeUrl";
import type { AbstentionReason, Citation, ClaimStatus } from "@/lib/types";

const ABSTENTION_COPY: Record<AbstentionReason, string> = {
  insufficient_evidence: "The knowledge base did not contain enough relevant evidence.",
  conflicting_sources: "Sources contradict each other and could not be reconciled.",
  verification_failed: "The draft answer could not be supported by the sources.",
  unauthorized: "The relevant documents are not accessible to you.",
  outdated: "Only outdated versions of the relevant documents were found.",
  unsupported_question: "This kind of question cannot be answered from documents.",
};

const STAGE_LABELS: Record<string, string> = {
  retrieval: "Search",
  rerank: "Re-rank",
  filter: "Filter",
  evidence_gate: "Evidence check",
  context_assembly: "Build context",
  generation: "Write answer",
  citation_parsing: "Citations",
  claim_verification: "Verify claims",
  conflict_detection: "Conflict check",
};

type Tone = "good" | "warn" | "bad" | "neutral";

const TONE_CLASS: Record<Tone, string> = {
  good: "bg-green-50 border-green-200 text-green-900",
  warn: "bg-amber-50 border-amber-200 text-amber-900",
  bad: "bg-red-50 border-red-200 text-red-900",
  neutral: "bg-bg border-border text-text",
};

function Icon({ kind }: { kind: "check" | "warn" | "x" | "dot" }) {
  const common = {
    className: "w-4 h-4 shrink-0",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    viewBox: "0 0 24 24",
    "aria-hidden": true,
  } as const;
  if (kind === "check")
    return (
      <svg {...common}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    );
  if (kind === "x")
    return (
      <svg {...common}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M18 6L6 18" />
      </svg>
    );
  if (kind === "warn")
    return (
      <svg {...common}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 4.3L2.6 18a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 4.3a2 2 0 00-3.4 0z" />
      </svg>
    );
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function verdictOf(m: ChatMessage): { tone: Tone; title: string; detail: string } {
  if (m.streaming && !m.content) {
    return { tone: "neutral", title: "Searching your documents", detail: "Evidence will appear when the answer is ready." };
  }
  if (m.abstained) {
    return {
      tone: "warn",
      title: "Not answered",
      detail:
        (m.abstentionReason && ABSTENTION_COPY[m.abstentionReason]) ||
        "There was not enough evidence to answer reliably. Nothing was guessed.",
    };
  }
  switch (m.verificationStatus) {
    case "unverified":
      return { tone: "warn", title: "Not checked", detail: "The checker could not run, so the claims were not compared against the sources. Verify this answer yourself." };
    case "partial":
      return { tone: "warn", title: "Partly verified", detail: "Statements the sources did not support were removed from the answer." };
    case "skipped":
      return { tone: "neutral", title: "Verification skipped", detail: "Claims were not checked for this answer." };
    default:
      return { tone: "good", title: "Verified", detail: "Every claim in the answer is supported by the cited sources." };
  }
}

const CLAIM_META: Record<ClaimStatus, { label: string; icon: "check" | "warn" | "x"; cls: string }> = {
  supported: { label: "Supported", icon: "check", cls: "text-green-700" },
  partial: { label: "Partly supported", icon: "warn", cls: "text-amber-700" },
  unsupported: { label: "Not supported", icon: "x", cls: "text-red-700" },
};

function SourceCard({ c, highlighted }: { c: Citation; highlighted: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const external = c.source_type === "external";
  const href = external ? safeHttpUrl(c.url) : null;
  return (
    <li
      data-source-index={c.index}
      className={`rounded-lg border p-3 text-xs transition-colors ${
        highlighted ? "border-primary ring-2 ring-primary/30 bg-primary/5" : "border-border bg-bg-white"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary/15 px-1 text-[10px] font-semibold text-primary-dark">
          {c.index}
        </span>
        <span className="truncate font-medium text-text">{c.document_title}</span>
        {c.page_number && <span className="shrink-0 text-text-muted">p.{c.page_number}</span>}
        <span className="ml-auto shrink-0 text-text-muted">{Math.round(c.relevance_score * 100)}% match</span>
      </div>
      {external && (
        <p className="mt-1 font-medium text-amber-800">External web source: lower authority than your documents</p>
      )}
      <p className={`mt-2 whitespace-pre-wrap text-text-muted ${expanded ? "" : "line-clamp-3"}`}>{c.content}</p>
      <div className="mt-1 flex items-center gap-3">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="cursor-pointer text-primary-dark underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-primary"
        >
          {expanded ? "Show less" : "Show full passage"}
        </button>
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="truncate text-primary-dark underline">
            Open page
          </a>
        )}
      </div>
    </li>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="border-t border-border px-4 py-4">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
        {title}
        {count !== undefined && <span className="rounded-full bg-bg px-1.5 py-0.5 text-[10px] normal-case">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

function BuiltDetails({ m }: { m: ChatMessage }) {
  const [copied, setCopied] = useState(false);
  const stages = Object.entries(m.spanMs ?? {}).filter(([, ms]) => typeof ms === "number") as [string, number][];
  const max = Math.max(1, ...stages.map(([, ms]) => ms));
  const searchSteps = m.agent?.steps.filter((s) => s.action !== "finish") ?? [];
  const cost = m.cost?.estimated_cost_usd;

  return (
    <details className="group border-t border-border px-4 py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold uppercase tracking-wide text-text-muted focus-visible:outline-2 focus-visible:outline-primary">
        How this answer was built
        <span className="text-[10px] normal-case group-open:hidden">Show</span>
        <span className="hidden text-[10px] normal-case group-open:inline">Hide</span>
      </summary>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <dt className="text-text-muted">Search method</dt>
        <dd className="text-right text-text">{m.strategy ?? "n/a"}</dd>
        <dt className="text-text-muted">Answer mode</dt>
        <dd className="text-right text-text">{m.answerMode ?? "n/a"}</dd>
        <dt className="text-text-muted">Estimated cost</dt>
        <dd className="text-right text-text">
          {cost === undefined ? "n/a" : cost === 0 ? "$0" : `$${cost.toFixed(cost < 0.01 ? 4 : 3)}`}
        </dd>
      </dl>
      {stages.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-xs" aria-label="Time spent in each stage">
          {stages.map(([name, ms]) => (
            <li key={name}>
              <div className="flex justify-between text-text-muted">
                <span>{STAGE_LABELS[name] ?? name}</span>
                <span className="font-mono">{ms.toFixed(0)} ms</span>
              </div>
              <div className="mt-0.5 h-1.5 rounded bg-bg" aria-hidden>
                <div className="h-1.5 rounded bg-primary/70" style={{ width: `${(ms / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {searchSteps.length > 0 && (
        <div className="mt-3 text-xs">
          <p className="mb-1 font-medium text-text">Deep research steps</p>
          <ol className="list-decimal space-y-0.5 pl-4 text-text-muted">
            {searchSteps.map((s) => (
              <li key={s.step}>
                {s.action}
                {s.detail ? `: ${s.detail}` : ""} ({s.new_chunks} new)
              </li>
            ))}
          </ol>
        </div>
      )}
      {m.traceId && (
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(m.traceId!);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            } catch {
              /* clipboard unavailable */
            }
          }}
          className="mt-3 cursor-pointer text-[11px] text-primary-dark underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-primary"
        >
          {copied ? "Copied" : `Copy trace id ${m.traceId.slice(0, 8)}`}
        </button>
      )}
    </details>
  );
}

export default function EvidencePanel({
  message,
  highlightedSource,
  onClose,
}: {
  message?: ChatMessage;
  highlightedSource?: number | null;
  onClose?: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlightedSource == null) return;
    bodyRef.current
      ?.querySelector(`[data-source-index="${highlightedSource}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [highlightedSource, message?.id]);

  const verdict = message ? verdictOf(message) : null;
  const gate = message?.evidenceGate;
  const citations = message?.citations ?? [];
  const claims = message?.claims ?? [];
  const conflicts = message?.conflicts ?? [];

  return (
    <aside aria-label="Evidence for the selected answer" className="flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-bg-white shadow-sm">
      <div className="flex items-start gap-3 px-4 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-text">Evidence</h2>
          {message?.question && (
            <p className="mt-0.5 line-clamp-2 text-xs text-text-muted" title={message.question}>
              For: {message.question}
            </p>
          )}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close evidence panel"
            className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-lg text-text-muted hover:bg-bg focus-visible:outline-2 focus-visible:outline-primary"
          >
            <Icon kind="x" />
          </button>
        )}
      </div>

      <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto">
        {!message || !verdict ? (
          <div className="px-4 pb-6 text-sm text-text-muted">
            <p className="font-medium text-text">Nothing to show yet</p>
            <p className="mt-1">
              Ask a question and you will see which passages support the answer, whether each claim was
              checked against them, and how the answer was built.
            </p>
          </div>
        ) : (
          <>
            <div className="px-4 pb-4">
              <div role="status" className={`flex gap-2 rounded-lg border px-3 py-2.5 text-xs ${TONE_CLASS[verdict.tone]}`}>
                <Icon kind={verdict.tone === "good" ? "check" : verdict.tone === "neutral" ? "dot" : "warn"} />
                <div>
                  <p className="font-semibold">{verdict.title}</p>
                  <p className="mt-0.5">{verdict.detail}</p>
                </div>
              </div>
              {gate && (
                <div className="mt-3 text-xs">
                  <div className="flex justify-between text-text-muted">
                    <span>Evidence strength</span>
                    <span className="font-mono">{Math.round(gate.confidence * 100)}%</span>
                  </div>
                  <div
                    className="mt-1 h-2 rounded bg-bg"
                    role="meter"
                    aria-label="Evidence strength"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(gate.confidence * 100)}
                  >
                    <div className="h-2 rounded bg-primary" style={{ width: `${Math.round(gate.confidence * 100)}%` }} />
                  </div>
                  <p className="mt-1 text-text-muted">
                    {gate.chunk_count} passage{gate.chunk_count === 1 ? "" : "s"} considered; best match{" "}
                    {Math.round(gate.top_score * 100)}%
                  </p>
                </div>
              )}
            </div>

            {citations.length > 0 && (
              <Section title="Sources" count={citations.length}>
                <ul className="space-y-2">
                  {citations.map((c) => (
                    <SourceCard key={c.index} c={c} highlighted={highlightedSource === c.index} />
                  ))}
                </ul>
              </Section>
            )}

            {claims.length > 0 && (
              <Section title="Claim checks" count={claims.length}>
                <ul className="space-y-2.5">
                  {claims.map((cl, i) => {
                    const meta = CLAIM_META[cl.status] ?? CLAIM_META.supported;
                    return (
                      <li key={i} className="text-xs">
                        <p className={`flex items-center gap-1.5 font-medium ${meta.cls}`}>
                          <Icon kind={meta.icon} />
                          {meta.label}
                          {cl.supporting_sources.length > 0 && (
                            <span className="font-normal text-text-muted">
                              (source {cl.supporting_sources.join(", ")})
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 pl-5 text-text-muted">{cl.claim}</p>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            {conflicts.length > 0 && (
              <Section title="Sources disagree" count={conflicts.length}>
                <ul className="space-y-3 text-xs">
                  {conflicts.map((c, i) => (
                    <li key={i} className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
                      <p className="font-medium">{c.topic}</p>
                      <p className="mt-1">Source {c.source_a}: {c.claim_a}</p>
                      <p>Source {c.source_b}: {c.claim_b}</p>
                      <p className="mt-1 font-medium">
                        {c.resolved && c.winning_source
                          ? `Preferring source ${c.winning_source} (${c.resolution_reason}).`
                          : "Could not be resolved automatically. Check the documents."}
                      </p>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {!(message.streaming && !message.content) && <BuiltDetails m={message} />}
          </>
        )}
      </div>
    </aside>
  );
}
