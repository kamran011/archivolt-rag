"use client";

import { Skeleton, SkeletonRegion } from "@/components/ui/Skeleton";
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
        <SkeletonRegion label="Loading knowledge bases" className="rounded-2xl border border-border bg-bg-white p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="rounded-xl border border-border bg-bg p-4">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="mt-3 h-3 w-full" />
                <Skeleton className="mt-2 h-3 w-1/2" />
                <Skeleton className="mt-4 h-3 w-1/3" />
              </div>
            ))}
          </div>
        </SkeletonRegion>
      ) : !currentOrg ? (
        <div className="bg-bg-white rounded-2xl border border-border p-12 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-primary-tint">
            <svg className="h-7 w-7 text-primary" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 21h18M5 21V7a1 1 0 011-1h5a1 1 0 011 1v14M14 21V4a1 1 0 011-1h4a1 1 0 011 1v17M8 9h1m-1 4h1m-1 4h1m5-10h1m-1 4h1m-1 4h1" />
            </svg>
          </div>
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
        <div role="alert" className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
          {error}
        </div>
      ) : knowledgeBases.length === 0 ? (
        <div className="bg-bg-white rounded-2xl border border-border p-12 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-primary-tint">
            <svg className="h-7 w-7 text-primary" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
          </div>
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
        <div className="rounded-2xl border border-border bg-bg-white p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {knowledgeBases.map((kb) => (
              <Link
                key={kb.id}
                href={`/dashboard/knowledge-bases/${kb.id}`}
                className="rounded-xl border border-border bg-bg p-4 transition-colors hover:bg-white hover:border-primary/30"
              >
                <h3 className="font-medium text-gray-900">{kb.name}</h3>
                {kb.description && (
                  <p className="text-gray-500 text-sm mt-1 line-clamp-2">{kb.description}</p>
                )}
                <div className="flex items-center gap-3 mt-3 text-xs text-gray-500">
                  <span>{kb.document_count} documents</span>
                  <span>·</span>
                  <span>{kb.chunk_strategy === "structure_aware" ? "Structure-aware" : "Fixed"}</span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
