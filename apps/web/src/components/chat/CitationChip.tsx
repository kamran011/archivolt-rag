"use client";

import { useState } from "react";
import { safeHttpUrl } from "@/lib/safeUrl";
import type { Citation } from "@/lib/types";

export default function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  const external = citation.source_type === "external";
  const href = external ? safeHttpUrl(citation.url) : null;

  return (
    <span className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full text-[10px] font-medium align-super transition-colors ${
          external
            ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
            : "bg-primary/15 text-primary-dark hover:bg-primary/25"
        }`}
      >
        {citation.index}
      </button>
      {open && (
        <div className="absolute z-10 bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 bg-bg-white rounded-lg border border-border shadow-lg p-3 text-left">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-text truncate">
              {citation.document_title}
            </span>
            {citation.page_number && (
              <span className="text-[10px] text-text-muted shrink-0 ml-2">
                p.{citation.page_number}
              </span>
            )}
          </div>
          {external && (
            <p className="text-[10px] font-medium text-amber-800 mb-1">
              External web source — lower authority than your knowledge base
            </p>
          )}
          <p className="text-xs text-text-muted line-clamp-4">{citation.content}</p>
          {href && (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="mt-2 block text-[10px] text-primary-dark underline truncate"
            >
              {href}
            </a>
          )}
          <div className="mt-2 text-[10px] text-text-muted">
            Relevance: {(citation.relevance_score * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </span>
  );
}
