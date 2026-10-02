"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/hooks/useChat";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { AnswerMode } from "@/lib/types";
import MessageBubble from "@/components/chat/MessageBubble";
import ChatInput from "@/components/chat/ChatInput";
import KBSelector from "@/components/chat/KBSelector";
import ChatAvatar from "@/components/chat/ChatAvatar";

export default function ChatInterface() {
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [agentic, setAgentic] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [mode, setMode] = useState<AnswerMode>("rag");
  const { currentOrg } = useOrganization();
  // Web search needs the deployment flag AND this opt-in; the server enforces both.
  const webSearchAllowed = currentOrg?.settings?.web_search_enabled === true;
  const { messages, sendMessage, isStreaming, error } = useChat(selectedKbIds, {
    agentic,
    webSearch: webSearch && webSearchAllowed,
    mode,
  });
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col h-full bg-bg-white rounded-2xl border border-border shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4">
        <ChatAvatar size={40} />
        <div>
          <h2 className="text-sm font-semibold text-text">Archivolt Assistant</h2>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-secondary" />
            <span className="text-xs text-secondary">Online</span>
          </div>
        </div>
      </div>
      <div className="border-t border-border" />

      {/* Knowledge base scope */}
      <div className="px-5 py-3 border-b border-border">
        <p className="text-xs font-medium text-text-muted mb-2">Searching in:</p>
        <KBSelector selectedIds={selectedKbIds} onChange={setSelectedKbIds} />
        <label className="mt-3 flex items-start gap-2 text-xs text-text-muted cursor-pointer">
          <input
            type="checkbox"
            checked={agentic}
            onChange={(e) => setAgentic(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            <span className="font-medium text-text">Deep research</span> - runs several
            searches for multi-part questions. Slower and costs more.
          </span>
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-text-muted">
          <label className="flex items-center gap-2">
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
            className={`flex items-center gap-2 ${webSearchAllowed ? "cursor-pointer" : "opacity-60"}`}
            title={
              webSearchAllowed
                ? undefined
                : "An organization admin must enable web search in Settings"
            }
          >
            <input
              type="checkbox"
              checked={webSearch && webSearchAllowed}
              disabled={!webSearchAllowed}
              onChange={(e) => setWebSearch(e.target.checked)}
            />
            <span>
              <span className="font-medium text-text">Web search</span> when the knowledge base
              falls short
            </span>
          </label>
        </div>
        {mode !== "rag" && (
          <p className="mt-2 text-[11px] text-text-muted">
            Full-context mode only works for knowledge bases an admin enabled for it and that fit
            the context budget; otherwise it falls back to retrieval.
          </p>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-center">
            <div>
              <div className="text-4xl mb-3">💬</div>
              <h2 className="font-medium text-text mb-1">Ask a question</h2>
              <p className="text-text-muted text-sm">
                {selectedKbIds.length === 0
                  ? "Select a knowledge base above to get started."
                  : "Ask anything about the selected documents."}
              </p>
            </div>
          </div>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      {error && (
        <div className="mx-5 mb-3 rounded-lg bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Input */}
      <div className="border-t border-border px-5 py-4">
        <ChatInput onSend={sendMessage} disabled={isStreaming || selectedKbIds.length === 0} />
      </div>
    </div>
  );
}
