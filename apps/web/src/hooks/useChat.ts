"use client";

import { useCallback, useEffect, useState } from "react";
import { streamChat } from "@/lib/streamChat";
import { api } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";
import type {
  AbstentionReason,
  AnswerMode,
  AgentSummary,
  Citation,
  ClaimVerification,
  ConflictInfo,
  CostMetadata,
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
  claims?: ClaimVerification[];
  cost?: CostMetadata;
  traceId?: string;
  spanMs?: Record<string, number | null>;
  strategy?: string;
  answerMode?: string;
  /** The user question this answer responds to (shown in the evidence panel). */
  question?: string;
  streaming?: boolean;
}

export interface ChatOptions {
  agentic: boolean;
  webSearch: boolean;
  mode: AnswerMode;
}

interface ApiRetrievalMetadata {
  strategy?: string;
  answer_mode?: string;
  trace_id?: string;
  span_ms?: Record<string, number | null>;
  verification_status?: VerificationStatus;
  evidence_gate?: EvidenceGateResult;
  conflicts?: ConflictInfo[];
  claim_verifications?: ClaimVerification[];
  agent?: AgentSummary;
  estimated_cost_usd?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  estimated_prompt_tokens?: number;
  estimated_completion_tokens?: number;
}

interface ApiMessage {
  id: string;
  role: MessageRole;
  content: string;
  citations: Citation[] | null;
  abstained: boolean;
  created_at: string;
  retrieval_metadata?: ApiRetrievalMetadata | null;
  token_usage?: CostMetadata | null;
}

interface ApiConversationDetail {
  id: string;
  knowledge_base_id: string | null;
  title: string | null;
  messages: ApiMessage[];
}

function apiMessageToChatMessage(m: ApiMessage, allMessages: ApiMessage[]): ChatMessage {
  const userBefore = [...allMessages]
    .slice(0, allMessages.indexOf(m))
    .reverse()
    .find((x) => x.role === "user");
  const md = m.retrieval_metadata ?? undefined;
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations ?? undefined,
    abstained: m.abstained || undefined,
    question: m.role === "assistant" ? userBefore?.content : undefined,
    abstentionReason: (md as { abstention_reason?: AbstentionReason | null })?.abstention_reason,
    verificationStatus: md?.verification_status,
    evidenceGate: md?.evidence_gate,
    conflicts: md?.conflicts,
    claims: md?.claim_verifications,
    agent: md?.agent,
    traceId: md?.trace_id,
    spanMs: md?.span_ms,
    strategy: md?.strategy,
    answerMode: md?.answer_mode,
    cost:
      md?.estimated_cost_usd !== undefined
        ? {
            estimated_prompt_tokens: md.estimated_prompt_tokens ?? md.prompt_tokens ?? 0,
            estimated_completion_tokens:
              md.estimated_completion_tokens ?? md.completion_tokens ?? 0,
            estimated_cost_usd: md.estimated_cost_usd,
            token_count_method: "stored",
          }
        : undefined,
  };
}

export function useChat(
  knowledgeBaseIds: string[],
  { agentic, webSearch, mode }: ChatOptions,
  initialConversationId?: string,
) {
  const { currentOrg } = useOrganization();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(
    initialConversationId ?? null
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!initialConversationId);
  // The knowledge base this conversation was scoped to, read back from the
  // server so the KB picker can be restored instead of landing on "none
  // selected" (and therefore a disabled send button) when reopening a chat.
  const [restoredKbId, setRestoredKbId] = useState<string | null>(null);

  // Load existing conversation on mount
  useEffect(() => {
    if (!initialConversationId || !currentOrg) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<ApiConversationDetail>(
        `/api/v1/chat/conversations/${initialConversationId}`,
        currentOrg.id
      )
      .then((conv) => {
        if (cancelled) return;
        setMessages(conv.messages.map((m) => apiMessageToChatMessage(m, conv.messages)));
        setConversationId(conv.id);
        setRestoredKbId(conv.knowledge_base_id);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load conversation history.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialConversationId, currentOrg]);

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
        question: content,
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
          webSearch,
          mode,
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
                      claims: event.claim_verifications,
                      cost: event.cost_metadata,
                      traceId: event.trace_id,
                      spanMs: event.span_ms,
                      strategy: event.trace_stages?.meta?.strategy,
                      answerMode: event.trace_stages?.meta?.answer_mode,
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
    [currentOrg, knowledgeBaseIds, conversationId, agentic, webSearch, mode]
  );

  function resetConversation() {
    setMessages([]);
    setConversationId(null);
    setError(null);
  }

  return {
    messages,
    sendMessage,
    isStreaming,
    error,
    conversationId,
    resetConversation,
    loading,
    restoredKbId,
  };
}
