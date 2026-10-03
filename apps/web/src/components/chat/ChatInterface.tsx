"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChat } from "@/hooks/useChat";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { AnswerMode } from "@/lib/types";
import MessageBubble from "@/components/chat/MessageBubble";
import ChatInput from "@/components/chat/ChatInput";
import KBSelector from "@/components/chat/KBSelector";
import ChatAvatar from "@/components/chat/ChatAvatar";
import EvidencePanel from "@/components/chat/EvidencePanel";

const MODE_LABEL: Record<AnswerMode, string> = {
  rag: "Retrieval",
  cag: "Full context",
  hybrid: "Full context, then retrieval",
};

function OptionChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary-dark">
      {children}
    </span>
  );
}

export default function ChatInterface({
  initialConversationId,
}: {
  initialConversationId?: string;
}) {
  const router = useRouter();
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [agentic, setAgentic] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [mode, setMode] = useState<AnswerMode>("rag");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The panel follows the newest answer. A pin is only honoured while no newer answer exists,
  // so it expires on its own when the next question is asked (no effect needed to reset it).
  const [pin, setPin] = useState<{ afterId: string | null; id: string } | null>(null);
  const [highlight, setHighlight] = useState<{ id: string; index: number } | null>(null);
  const { currentOrg } = useOrganization();
  // Web search needs the deployment flag AND this opt-in; the server enforces both.
  const webSearchAllowed = currentOrg?.settings?.web_search_enabled === true;
  const { messages, sendMessage, isStreaming, error, conversationId, loading, restoredKbId } =
    useChat(
      selectedKbIds,
      { agentic, webSearch: webSearch && webSearchAllowed, mode },
      initialConversationId
    );

  // Reopening a past conversation: restore the KB it was scoped to instead of
  // leaving the picker empty (which silently disables the send button).
  useEffect(() => {
    if (restoredKbId) setSelectedKbIds((prev) => (prev.length === 0 ? [restoredKbId] : prev));
  }, [restoredKbId]);

  // After the first reply in a new conversation, update the URL so a refresh restores it.
  const pushedRef = useRef<string | null>(initialConversationId ?? null);
  useEffect(() => {
    if (conversationId && conversationId !== pushedRef.current) {
      pushedRef.current = conversationId;
      router.replace(`/dashboard/chat/${conversationId}`);
    }
  }, [conversationId, router]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const assistants = messages.filter((m) => m.role === "assistant");
  const latest = assistants[assistants.length - 1];
  const pinned = pin && pin.afterId === (latest?.id ?? null) ? assistants.find((m) => m.id === pin.id) : undefined;
  const selected = pinned ?? latest;
  const highlightedSource = highlight && selected?.id === highlight.id ? highlight.index : null;
  const sourceCount = selected?.citations?.length ?? 0;

  function select(id: string, sourceIndex?: number) {
    setPin({ afterId: latest?.id ?? null, id });
    setHighlight(sourceIndex === undefined ? null : { id, index: sourceIndex });
  }

  return (
    <div className="flex h-full gap-4">
      <section
        aria-label="Conversation"
        className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-bg-white"
        style={{ boxShadow: "0 0 40px 4px rgba(112, 144, 176, 0.2)" }}
      >
        <div className="flex items-center gap-3 px-5 py-3">
          <ChatAvatar size={36} />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-text">Archivolt Assistant</h2>
            <div className="mt-0.5 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
              <span className="text-xs text-secondary">Online</span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="min-h-9 cursor-pointer rounded-lg border border-border px-3 text-xs font-medium text-text transition-colors hover:bg-bg focus-visible:outline-2 focus-visible:outline-primary xl:hidden"
          >
            Evidence{sourceCount > 0 ? ` (${sourceCount})` : ""}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-y border-border px-5 py-2.5">
          <span className="text-xs font-medium text-text-muted">Searching in</span>
          <KBSelector selectedIds={selectedKbIds} onChange={setSelectedKbIds} />
        </div>

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex h-full items-center justify-center">
              <div className="flex flex-col items-center gap-2 text-text-muted">
                <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden>
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-sm">Loading conversation…</span>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-center">
              <div>
                <svg
                  className="mx-auto mb-3 h-9 w-9 text-primary/60"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  viewBox="0 0 24 24"
                  aria-hidden
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h8M8 14h5m-9 6l2.5-3H18a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v14z" />
                </svg>
                <h2 className="mb-1 font-medium text-text">Ask a question</h2>
                <p className="text-sm text-text-muted">
                  {selectedKbIds.length === 0
                    ? "Select a knowledge base above to get started."
                    : "Ask anything about the selected documents. The evidence for each answer appears alongside."}
                </p>
              </div>
            </div>
          ) : (
            messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                selected={m.role === "assistant" && selected?.id === m.id}
                onSelect={m.role === "assistant" ? () => select(m.id) : undefined}
                onCitationOpen={m.role === "assistant" ? (index) => select(m.id, index) : undefined}
              />
            ))
          )}
        </div>

        {error && (
          <div role="alert" className="mx-5 mb-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="border-t border-border px-5 py-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setOptionsOpen(!optionsOpen)}
              aria-expanded={optionsOpen}
              aria-controls="chat-options"
              className="min-h-8 cursor-pointer rounded-lg px-2 text-xs font-medium text-text-muted transition-colors hover:bg-bg hover:text-text focus-visible:outline-2 focus-visible:outline-primary"
            >
              Options {optionsOpen ? "(hide)" : ""}
            </button>
            {agentic && <OptionChip>Deep research</OptionChip>}
            {mode !== "rag" && <OptionChip>{MODE_LABEL[mode]}</OptionChip>}
            {webSearch && webSearchAllowed && <OptionChip>Web search</OptionChip>}
          </div>
          {optionsOpen && (
            <div id="chat-options" className="mb-3 space-y-3 rounded-lg bg-bg px-3 py-3 text-xs text-text-muted">
              <label className="flex cursor-pointer items-start gap-2">
                <input type="checkbox" checked={agentic} onChange={(e) => setAgentic(e.target.checked)} className="mt-0.5" />
                <span>
                  <span className="font-medium text-text">Deep research</span>: runs several searches for
                  multi-part questions. Slower and costs more.
                </span>
              </label>
              <label className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-text">Answer mode</span>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as AnswerMode)}
                  className="rounded-md border border-border bg-bg-white px-2 py-1 text-xs"
                >
                  <option value="rag">Retrieval (RAG)</option>
                  <option value="cag">Full context (CAG)</option>
                  <option value="hybrid">Full context, fall back to RAG</option>
                </select>
              </label>
              <label
                className={`flex items-start gap-2 ${webSearchAllowed ? "cursor-pointer" : "opacity-60"}`}
                title={webSearchAllowed ? undefined : "An organization admin must enable web search in Settings"}
              >
                <input
                  type="checkbox"
                  checked={webSearch && webSearchAllowed}
                  disabled={!webSearchAllowed}
                  onChange={(e) => setWebSearch(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium text-text">Web search</span> when the knowledge base falls
                  short
                </span>
              </label>
              {mode !== "rag" && (
                <p className="text-[11px]">
                  Full-context mode only works for knowledge bases an admin enabled for it and that fit the
                  context budget; otherwise it falls back to retrieval.
                </p>
              )}
            </div>
          )}
          <ChatInput onSend={sendMessage} disabled={isStreaming || selectedKbIds.length === 0} />
        </div>
      </section>

      <div className="hidden w-[380px] shrink-0 xl:block">
        <EvidencePanel message={selected} highlightedSource={highlightedSource} />
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 xl:hidden" role="dialog" aria-modal="true" aria-label="Evidence">
          <button
            type="button"
            aria-label="Close evidence panel"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 cursor-default bg-black/30"
          />
          <div className="absolute inset-y-0 right-0 w-[min(380px,100vw)] p-2">
            <EvidencePanel
              message={selected}
              highlightedSource={highlightedSource}
              onClose={() => setDrawerOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
