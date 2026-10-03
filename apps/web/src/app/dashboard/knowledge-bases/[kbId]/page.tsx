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
      <Link href="/dashboard/knowledge-bases" className="text-sm text-gray-500 hover:text-gray-900">
        ← Knowledge Bases
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mt-2 mb-1">{kb?.name ?? "Documents"}</h1>
      {kb && (
        <p className="text-xs text-gray-500 mb-6">
          {kb.chunk_strategy.replace("_", "-")} chunking · {kb.chunk_size} tokens ·{" "}
          {kb.chunk_overlap} overlap · {kb.embedding_model}
        </p>
      )}

      <section className="bg-white rounded-xl border border-gray-200 p-4 mb-6">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={kb?.cag_enabled ?? false}
            disabled={!canManage || !kb}
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
        {!canManage && <p className="text-xs text-gray-400 mt-2">Only admins can change this.</p>}
      </section>

      <div className="mb-6">
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
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-500 text-sm">
          No documents uploaded yet.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">Name</th>
                <th className="text-left px-4 py-2.5 font-medium">Type</th>
                <th className="text-left px-4 py-2.5 font-medium">Size</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium">Access &amp; tags</th>
                <th className="text-right px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="px-4 py-2.5 text-gray-900">
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
                  <td className="px-4 py-2.5 text-gray-500 uppercase text-xs">{doc.file_type}</td>
                  <td className="px-4 py-2.5 text-gray-500">{formatBytes(doc.file_size)}</td>
                  <td className="px-4 py-2.5">
                    <DocumentStatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error_message && (
                      <p className="text-red-500 text-xs mt-1">{doc.error_message}</p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs">
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
                  <td className="px-4 py-2.5 text-right">
                    <Link
                      href={`/dashboard/knowledge-bases/${kbId}/documents/${doc.id}`}
                      className="mr-3 text-blue-600 hover:text-blue-800 text-xs"
                    >
                      Inspect
                    </Link>
                    <button
                      onClick={() => deleteDocument(doc.id)}
                      className="cursor-pointer text-red-500 hover:text-red-700 text-xs"
                    >
                      Delete
                    </button>
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
