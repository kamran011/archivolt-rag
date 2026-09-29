"use client";

import Link from "next/link";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { useOrganization } from "@/providers/OrganizationProvider";

export default function KnowledgeBasesPage() {
  const { currentOrg, loading: orgLoading } = useOrganization();
  const { knowledgeBases, loading, error } = useKnowledgeBases();

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Knowledge Bases</h1>
          <p className="text-gray-500 text-sm mt-1">
            Organize your documents into searchable collections
          </p>
        </div>
        <Link
          href="/dashboard/knowledge-bases/new"
          className="rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
        >
          New knowledge base
        </Link>
      </div>

      {orgLoading || loading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-gray-400 text-sm">
          Loading…
        </div>
      ) : !currentOrg ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="text-4xl mb-3">🏢</div>
          <h2 className="font-medium text-gray-900 mb-1">No organization yet</h2>
          <p className="text-gray-500 text-sm mb-4">
            You need to create a workspace first.
          </p>
          <Link
            href="/dashboard/onboarding"
            className="inline-block rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            Create workspace
          </Link>
        </div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
          {error}
        </div>
      ) : knowledgeBases.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <div className="text-4xl mb-3">📚</div>
          <h2 className="font-medium text-gray-900 mb-1">No knowledge bases yet</h2>
          <p className="text-gray-500 text-sm mb-4">
            Create your first knowledge base to start uploading documents.
          </p>
          <Link
            href="/dashboard/knowledge-bases/new"
            className="inline-block rounded-lg bg-blue-600 text-white px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            Create knowledge base
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {knowledgeBases.map((kb) => (
            <Link
              key={kb.id}
              href={`/dashboard/knowledge-bases/${kb.id}`}
              className="bg-white rounded-xl border border-gray-200 p-5 hover:border-blue-300 transition-colors"
            >
              <h3 className="font-medium text-gray-900">{kb.name}</h3>
              {kb.description && (
                <p className="text-gray-500 text-sm mt-1 line-clamp-2">{kb.description}</p>
              )}
              <div className="flex items-center gap-3 mt-3 text-xs text-gray-400">
                <span>{kb.document_count} documents</span>
                <span>·</span>
                <span>{kb.chunk_strategy === "structure_aware" ? "Structure-aware" : "Fixed"}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
