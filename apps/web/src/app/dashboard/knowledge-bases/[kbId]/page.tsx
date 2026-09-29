"use client";

import { use } from "react";
import Link from "next/link";
import { useDocuments } from "@/hooks/useDocuments";
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

  return (
    <div>
      <Link href="/dashboard/knowledge-bases" className="text-sm text-gray-500 hover:text-gray-900">
        ← Knowledge Bases
      </Link>

      <h1 className="text-2xl font-semibold text-gray-900 mt-2 mb-6">Documents</h1>

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
                <th className="text-right px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className="px-4 py-2.5 text-gray-900">{doc.title}</td>
                  <td className="px-4 py-2.5 text-gray-500 uppercase text-xs">{doc.file_type}</td>
                  <td className="px-4 py-2.5 text-gray-500">{formatBytes(doc.file_size)}</td>
                  <td className="px-4 py-2.5">
                    <DocumentStatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error_message && (
                      <p className="text-red-500 text-xs mt-1">{doc.error_message}</p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => deleteDocument(doc.id)}
                      className="text-red-500 hover:text-red-700 text-xs"
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
