"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { safeHttpUrl } from "@/lib/safeUrl";
import type { Citation } from "@/lib/types";

const POPOVER_WIDTH = 288;
const MARGIN = 8;

export default function CitationChip({
  citation,
  onOpen,
}: {
  citation: Citation;
  /** Called when the chip is opened, e.g. to highlight the source in the evidence panel. */
  onOpen?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const external = citation.source_type === "external";
  const href = external ? safeHttpUrl(citation.url) : null;

  // The chat list scrolls and clips overflow, so the popover is portalled to <body> and
  // positioned against the viewport: above the chip when it fits, otherwise below.
  useLayoutEffect(() => {
    if (!open || !buttonRef.current || !popoverRef.current) return;
    const chip = buttonRef.current.getBoundingClientRect();
    const height = popoverRef.current.offsetHeight;
    const left = Math.min(
      Math.max(MARGIN, chip.left + chip.width / 2 - POPOVER_WIDTH / 2),
      window.innerWidth - POPOVER_WIDTH - MARGIN
    );
    const above = chip.top - height - MARGIN;
    const top =
      above >= MARGIN ? above : Math.min(chip.bottom + MARGIN, window.innerHeight - height - MARGIN);
    setPos({ top: Math.max(MARGIN, top), left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setOpen(false);
      setPos(null);
    };
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!popoverRef.current?.contains(target) && !buttonRef.current?.contains(target)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true); // capture: also fires for inner scroll areas
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  return (
    <span className="relative inline-block">
      <button
        ref={buttonRef}
        onClick={() => {
          if (!open) onOpen?.();
          setOpen(!open);
          setPos(null);
        }}
        aria-expanded={open}
        aria-label={`Source ${citation.index}: ${citation.document_title}`}
        className={`inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full text-[10px] font-medium align-super transition-colors ${
          external
            ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
            : "bg-primary/15 text-primary-dark hover:bg-primary/25"
        }`}
      >
        {citation.index}
      </button>
      {open &&
        createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            style={{
              position: "fixed",
              top: pos?.top ?? 0,
              left: pos?.left ?? 0,
              width: POPOVER_WIDTH,
              visibility: pos ? "visible" : "hidden", // measured first, then shown
            }}
            className="z-50 bg-bg-white rounded-lg border border-border shadow-lg p-3 text-left"
          >
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
          </div>,
          document.body
        )}
    </span>
  );
}
