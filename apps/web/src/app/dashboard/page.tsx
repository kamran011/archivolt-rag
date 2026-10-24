"use client";

import Link from "next/link";
import { useConversations } from "@/hooks/useConversations";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";
import { useOrganization } from "@/providers/OrganizationProvider";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DashboardPage() {
  const { currentOrg, loading: orgLoading } = useOrganization();
  const { knowledgeBases, loading: kbLoading } = useKnowledgeBases();
  const { conversations, loading: convLoading } = useConversations();

  const loading = orgLoading || (!!currentOrg && (kbLoading || convLoading));
  const format = (n: number) => (currentOrg ? n.toLocaleString() : "—");

  const stats = [
    { label: "Knowledge Bases", value: format(knowledgeBases.length), href: "/dashboard/knowledge-bases" },
    {
      label: "Documents",
      value: format(knowledgeBases.reduce((n, kb) => n + kb.document_count, 0)),
      href: "/dashboard/knowledge-bases",
    },
    { label: "Conversations", value: format(conversations.length), href: "/dashboard/chat" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Dashboard</h1>
      <p className="text-gray-500 text-sm mb-8">
        Welcome to Ragix.
      </p>

      <div className="rounded-2xl border border-border bg-bg-white p-5 mb-6" aria-busy={loading}>
        <div className="grid grid-cols-1 divide-y divide-gray-100 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          {stats.map((stat) => (
            <Link
              key={stat.label}
              href={stat.href}
              className="rounded-xl p-4 transition-colors hover:bg-gray-50 sm:first:pl-0 sm:last:pr-0"
            >
              <p className="text-sm text-gray-500">{stat.label}</p>
              {loading ? (
                <>
                  <span className="sr-only">Loading</span>
                  <Skeleton className="mt-2 h-7 w-14" />
                </>
              ) : (
                <p className="text-2xl font-semibold text-gray-900 mt-1">{stat.value}</p>
              )}
            </Link>
          ))}
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
        <h2 className="font-medium text-blue-900 mb-1">Get started</h2>
        <ol className="list-decimal list-inside text-sm text-blue-800 space-y-1">
          <li>
            <Link href="/dashboard/knowledge-bases/new" className="underline">
              Create a knowledge base
            </Link>
          </li>
          <li>Upload documents (PDF, DOCX, Markdown, TXT)</li>
          <li>
            <Link href="/dashboard/chat" className="underline">
              Start chatting
            </Link>{" "}
            with your documents
          </li>
        </ol>
      </div>
    </div>
  );
}
