"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useOrganization } from "@/providers/OrganizationProvider";
import { Skeleton, SkeletonRegion } from "@/components/ui/Skeleton";
import type { EscalationDetail, EscalationSummary } from "@/lib/types";

const TRIGGER_LABELS: Record<string, string> = {
  user_request: "Asked for human",
  frustration: "Frustrated",
  abstain: "Abstained answer",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function EscalationsPage() {
  const { currentOrg } = useOrganization();
  const orgId = currentOrg?.id;
  const searchParams = useSearchParams();
  const idParam = searchParams.get("id");

  const [statusFilter, setStatusFilter] = useState<"open" | "resolved">("open");
  const [selectedId, setSelectedId] = useState<string | null>(idParam);
  // Track the last detail we loaded; derive freshness from selectedId match
  const [loadedDetail, setLoadedDetail] = useState<EscalationDetail | null>(null);
  const [resolving, setResolving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: escalations,
    loading,
    error,
    refresh,
  } = useApiResource<EscalationSummary[]>(
    orgId ? `/api/v1/escalations?status=${statusFilter}` : null,
    orgId,
    "Failed to load escalations",
  );

  useEffect(() => {
    if (!selectedId || !orgId) return;
    let cancelled = false;
    api
      .get<EscalationDetail>(`/api/v1/escalations/${selectedId}`, orgId)
      .then((d) => { if (!cancelled) setLoadedDetail(d); })
      .catch(() => { /* keep stale detail, selectedId mismatch handles rendering */ });
    return () => { cancelled = true; };
  }, [selectedId, orgId]);

  // Derive — only show a detail when it matches the current selection
  const detail = selectedId != null && loadedDetail?.id === selectedId ? loadedDetail : null;
  const detailLoading = selectedId != null && loadedDetail?.id !== selectedId;

  async function resolve(id: string) {
    if (!orgId) return;
    setResolving(true);
    setActionError(null);
    try {
      await api.post<EscalationSummary>(`/api/v1/escalations/${id}/resolve`, {}, orgId);
      setSelectedId(null);
      setLoadedDetail(null);
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to resolve");
    } finally {
      setResolving(false);
    }
  }

  if (!currentOrg || (currentOrg.role !== "owner" && currentOrg.role !== "admin")) {
    return (
      <div className="p-6">
        <p className="text-sm text-gray-500">Only owners and admins can view escalations.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900 mb-1">Escalations</h1>
        <p className="text-gray-500 text-sm">Conversations forwarded to a human.</p>
      </div>

      {actionError && (
        <div role="alert" className="flex items-start justify-between gap-3 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="cursor-pointer shrink-0 text-red-400 hover:text-red-600">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-gray-200">
        {(["open", "resolved"] as const).map((s) => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setSelectedId(null); }}
            className={`cursor-pointer px-4 py-2 text-sm font-medium border-b-2 transition-colors capitalize ${
              statusFilter === s
                ? "border-gray-900 text-gray-900"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="flex gap-5 min-h-0">
        {/* List */}
        <div className="w-80 shrink-0">
          {error && <p className="text-sm text-red-600">{error}</p>}
          {loading ? (
            <SkeletonRegion label="Loading escalations" className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rounded-xl border border-gray-100 p-3">
                  <Skeleton className="h-4 w-3/4 mb-2" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))}
            </SkeletonRegion>
          ) : escalations && escalations.length > 0 ? (
            <ul className="space-y-2">
              {escalations.map((esc) => (
                <li key={esc.id}>
                  <button
                    onClick={() => setSelectedId(esc.id === selectedId ? null : esc.id)}
                    className={`w-full text-left rounded-xl border px-3 py-3 transition-colors cursor-pointer ${
                      selectedId === esc.id
                        ? "border-violet-300 bg-violet-50"
                        : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {esc.conversation_title ?? "Untitled conversation"}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {esc.reasons.map((r) => (
                        <span key={r} className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                          {TRIGGER_LABELS[r] ?? r}
                        </span>
                      ))}
                    </div>
                    <p className="mt-1.5 text-xs text-gray-400">{formatDate(esc.created_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-400 py-4">No {statusFilter} escalations.</p>
          )}
        </div>

        {/* Detail */}
        <div className="flex-1 min-w-0">
          {detailLoading ? (
            <SkeletonRegion label="Loading escalation detail" className="space-y-3">
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="h-48 w-full" />
            </SkeletonRegion>
          ) : detail ? (
            <div className="rounded-2xl border border-border bg-bg-white p-5">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h2 className="font-semibold text-gray-900">
                    {detail.conversation_title ?? "Untitled conversation"}
                  </h2>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Escalated {formatDate(detail.created_at)}
                    {detail.resolved_at && ` · resolved ${formatDate(detail.resolved_at)}`}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {detail.reasons.map((r) => (
                      <span key={r} className="inline-flex items-center rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-xs font-medium text-amber-700">
                        {TRIGGER_LABELS[r] ?? r}
                      </span>
                    ))}
                  </div>
                </div>
                {detail.status === "open" && (
                  <button
                    disabled={resolving}
                    onClick={() => void resolve(detail.id)}
                    className="cursor-pointer shrink-0 rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {resolving ? "Resolving…" : "Mark resolved"}
                  </button>
                )}
              </div>

              {Object.keys(detail.delivery).length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2 text-xs text-gray-500">
                  {Object.entries(detail.delivery).map(([ch, st]) => (
                    <span key={ch} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 border ${
                      st === "sent" ? "bg-green-50 border-green-200 text-green-700" : "bg-gray-50 border-gray-200 text-gray-500"
                    }`}>
                      {ch}: {st}
                    </span>
                  ))}
                </div>
              )}

              <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Transcript</h3>
              <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
                {detail.transcript.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm ${
                      msg.role === "user"
                        ? "bg-violet-600 text-white"
                        : msg.abstained
                          ? "bg-amber-50 border border-amber-200 text-amber-900"
                          : "bg-gray-100 text-gray-800"
                    }`}>
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                      {msg.abstained && (
                        <p className="mt-1 text-xs font-medium text-amber-600">Abstained</p>
                      )}
                      <p className={`mt-1 text-[10px] ${msg.role === "user" ? "text-white/60" : "text-gray-400"}`}>
                        {formatDate(msg.created_at)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-40 text-sm text-gray-400">
              Select an escalation to view its transcript.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
