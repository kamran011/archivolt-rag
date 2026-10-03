"use client";

import Link from "next/link";
import { useKnowledgeBases } from "@/hooks/useKnowledgeBases";

interface KBSelectorProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

export default function KBSelector({ selectedIds, onChange }: KBSelectorProps) {
  const { knowledgeBases, loading } = useKnowledgeBases();

  function toggle(id: string) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((i) => i !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  }

  if (loading) {
    return <div className="text-xs text-gray-400">Loading knowledge bases…</div>;
  }

  if (knowledgeBases.length === 0) {
    return (
      <div className="text-xs text-gray-400">
        No knowledge bases yet —{" "}
        <Link href="/dashboard/knowledge-bases/new" className="text-blue-600 hover:underline">
          create one
        </Link>
        .
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {knowledgeBases.map((kb) => {
        const selected = selectedIds.includes(kb.id);
        return (
          <button
            key={kb.id}
            onClick={() => toggle(kb.id)}
            className={`cursor-pointer text-xs px-2.5 py-1 rounded-full border transition-colors focus-visible:outline-2 focus-visible:outline-primary ${
              selected
                ? "bg-blue-600 border-blue-600 text-white"
                : "bg-white border-gray-300 text-gray-600 hover:border-gray-400"
            }`}
          >
            {kb.name}
          </button>
        );
      })}
    </div>
  );
}
