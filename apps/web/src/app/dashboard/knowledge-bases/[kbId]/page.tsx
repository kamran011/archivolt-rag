"use client";

import { use, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApiResource } from "@/hooks/useApiResource";
import { useDocuments } from "@/hooks/useDocuments";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { CagInfo, KnowledgeBase } from "@/lib/types";
import DocumentStatusBadge from "@/components/documents/DocumentStatusBadge";
import DocumentUploader from "@/components/documents/DocumentUploader";
import BackLink from "@/components/ui/BackLink";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function KnowledgeBaseDetailPage({
  params,
}: {
  params: Promise<{ kbId: string }>;
}) {
  const { kbId } = use(params);
  const { documents, loading, error, uploadDocument, deleteDocument } = useDocuments(kbId);
  const { currentOrg } = useOrganization();
  const canManage = currentOrg?.role === "owner" || currentOrg?.role === "admin";
  const { data: kb, update: updateKb } = useApiResource<KnowledgeBase>(
    currentOrg ? `/api/v1/knowledge-bases/${kbId}` : null,
    currentOrg?.id,
    "Failed to load knowledge base",
  );
  const { data: cag, refresh: reloadCag } = useApiResource<CagInfo>(
    currentOrg ? `/api/v1/knowledge-bases/${kbId}/cag` : null,
    currentOrg?.id,
    "Failed to load CAG status",
  );
  const [cagError, setCagError] = useState<string | null>(null);

  async function toggleCag(enabled: boolean) {
    if (!currentOrg) return;
    setCagError(null);
    try {
      const next = await api.patch<KnowledgeBase>(
        `/api/v1/knowledge-bases/${kbId}`,
        { cag_enabled: enabled },
        currentOrg.id,
      );
      updateKb(() => next);
      await reloadCag();
    } catch (e) {
      setCagError(e instanceof Error ? e.message : "Could not update");
    }
  }

  return (
    <div>
      <BackLink href="/dashboard/knowledge-bases" label="Knowledge Bases" />

      <h1 className="text-2xl font-semibold text-gray-900 mb-1">{kb?.name ?? "Documents"}</h1>
      {kb && (
        <p className="text-xs text-gray-500 mb-6">
          {kb.chunk_strategy.replace("_", "-")} chunking · {kb.chunk_size} tokens ·{" "}
          {kb.chunk_overlap} overlap · {kb.embedding_model}
        </p>
      )}

      {canManage && (
        <section className="bg-bg-white rounded-2xl border border-border p-6 mb-8">
          <label className="flex items-start gap-3 text-sm cursor-pointer">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={kb?.cag_enabled ?? false}
              disabled={!kb}
              onChange={(e) => void toggleCag(e.target.checked)}
            />
            <span>
              <span className="font-medium text-gray-900">Allow full-context answers (CAG)</span>
              <span className="block text-xs text-gray-500">
                For small, stable knowledge bases the whole content can be placed in the prompt
                instead of retrieving passages.
                {cag && (
                  <>
                    {" "}
                    Currently {cag.tokens.toLocaleString()} of {cag.limit.toLocaleString()} tokens
                    {cag.eligible ? " — fits." : cag.reason ? ` — ${cag.reason}` : " — too large."}
                  </>
                )}
              </span>
            </span>
          </label>
          {cagError && <p className="text-xs text-red-600 mt-2">{cagError}</p>}
        </section>
      )}

      <div className="mb-8">
        <DocumentUploader onUpload={uploadDocument} />
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 text-sm text-center py-8">Loading documents…</div>
      ) : documents.length === 0 ? (
        <div className="bg-bg-white rounded-2xl border border-border p-10 text-center text-gray-500 text-sm">
          No documents uploaded yet.
        </div>
      ) : (
        <div className="bg-bg-white rounded-2xl border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-5 py-3 font-medium">Name</th>
                <th className="text-left px-5 py-3 font-medium">Type</th>
                <th className="text-left px-5 py-3 font-medium">Size</th>
                <th className="text-left px-5 py-3 font-medium">Status</th>
                <th className="text-left px-5 py-3 font-medium">Access &amp; tags</th>
                <th className="text-right px-5 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="px-5 py-3.5 text-gray-900">
                    <Link
                      href={`/dashboard/knowledge-bases/${kbId}/documents/${doc.id}`}
                      className="hover:underline"
                    >
                      {doc.title}
                    </Link>
                    {doc.version > 1 && (
                      <span className="ml-2 text-[10px] text-gray-400">v{doc.version}</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-gray-500 uppercase text-xs">{doc.file_type}</td>
                  <td className="px-5 py-3.5 text-gray-500">{formatBytes(doc.file_size)}</td>
                  <td className="px-5 py-3.5">
                    <DocumentStatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error_message && (
                      <p className="text-red-500 text-xs mt-1">{doc.error_message}</p>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-xs">
                    {doc.restricted && (
                      <span className="mr-1 rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">
                        restricted
                      </span>
                    )}
                    {doc.tags.map((t) => (
                      <span key={t} className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 text-gray-600">
                        {t}
                      </span>
                    ))}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Link
                        href={`/dashboard/knowledge-bases/${kbId}/documents/${doc.id}`}
                        title="Inspect document"
                        aria-label="Inspect document"
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-gray-100 hover:text-primary-dark"
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                      </Link>
                      <button
                        type="button"
                        onClick={() => deleteDocument(doc.id)}
                        title="Delete document"
                        aria-label="Delete document"
                        className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-red-50 hover:text-red-600"
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9.5 7V5a1 1 0 011-1h3a1 1 0 011 1v2m2 0-.7 12.1a2 2 0 01-2 1.9H8.2a2 2 0 01-2-1.9L5.5 7h13z" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
