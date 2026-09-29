"use client";

import { useCallback, useState } from "react";
import { streamChat } from "@/lib/streamChat";
import { useOrganization } from "@/providers/OrganizationProvider";
import type {
  AbstentionReason,
  AgentSummary,
  Citation,
  ConflictInfo,
  EvidenceGateResult,
  MessageRole,
  VerificationStatus,
} from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  citations?: Citation[];
  abstained?: boolean;
  abstentionReason?: AbstentionReason | null;
  verificationStatus?: VerificationStatus;
  evidenceGate?: EvidenceGateResult;
  conflicts?: ConflictInfo[];
  agent?: AgentSummary;
  streaming?: boolean;
}

export function useChat(knowledgeBaseIds: string[], agentic = false) {
  const { currentOrg } = useOrganization();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!currentOrg || !content.trim()) return;

      setError(null);
      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
      };
      const assistantId = crypto.randomUUID();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);

      try {
        for await (const event of streamChat({
          message: content,
          knowledgeBaseIds,
          conversationId: conversationId || undefined,
          organizationId: currentOrg.id,
          agentic,
        })) {
          if (event.type === "token") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + (event.content || "") } : m
              )
            );
          } else if (event.type === "done") {
            if (event.conversation_id) setConversationId(event.conversation_id);
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      streaming: false,
                      content: event.final_answer ?? m.content,
                      citations: event.citations,
                      abstained: event.abstained,
                      abstentionReason: event.abstention_reason,
                      verificationStatus: event.verification_status,
                      evidenceGate: event.evidence_gate,
                      conflicts: event.conflicts,
                      agent: event.agent,
                    }
                  : m
              )
            );
          } else if (event.type === "error") {
            setError(event.message || "Something went wrong");
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m))
            );
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to send message");
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m))
        );
      } finally {
        setIsStreaming(false);
      }
    },
    [currentOrg, knowledgeBaseIds, conversationId, agentic]
  );

  function resetConversation() {
    setMessages([]);
    setConversationId(null);
    setError(null);
  }

  return { messages, sendMessage, isStreaming, error, conversationId, resetConversation };
}
