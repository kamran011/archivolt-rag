import { createClient } from "@/lib/supabase/client";
import type {
  AbstentionReason,
  AnswerMode,
  AgentSummary,
  Citation,
  ClaimVerification,
  ConflictInfo,
  CostMetadata,
  EvidenceGateResult,
  TraceMeta,
  VerificationStatus,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatStreamEvent {
  type: "token" | "done" | "error" | "handoff";
  content?: string;
  conversation_id?: string;
  abstained?: boolean;
  abstention_reason?: AbstentionReason | null;
  verification_status?: VerificationStatus;
  // Set when verification changed the answer after it was streamed; replaces the shown text.
  final_answer?: string | null;
  citations?: Citation[];
  claim_verifications?: ClaimVerification[];
  cost_metadata?: CostMetadata;
  trace_id?: string;
  span_ms?: Record<string, number | null>;
  trace_stages?: { meta?: TraceMeta };
  conflicts?: ConflictInfo[];
  agent?: AgentSummary;
  evidence_gate?: EvidenceGateResult;
  message?: string;
  // "handoff" events: the conversation was handed to a human (message = text for the user).
  status?: "created" | "already_open";
  reasons?: Array<"user_request" | "frustration" | "abstain">;
}

interface StreamChatParams {
  message: string;
  knowledgeBaseIds: string[];
  conversationId?: string;
  organizationId: string;
  model?: string;
  agentic?: boolean;
  webSearch?: boolean;
  mode?: AnswerMode;
}

/**
 * Streams a chat response via SSE over a POST request (native EventSource
 * doesn't support POST bodies or custom auth headers, so we read the
 * fetch ReadableStream and parse "data: {...}" lines ourselves).
 */
export async function* streamChat(
  params: StreamChatParams
): AsyncGenerator<ChatStreamEvent, void, unknown> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const response = await fetch(`${API_URL}/api/v1/chat/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      "X-Organization-Id": params.organizationId,
    },
    body: JSON.stringify({
      message: params.message,
      knowledge_base_ids: params.knowledgeBaseIds,
      conversation_id: params.conversationId,
      // Omitted unless set: the server applies its configured DEFAULT_LLM_MODEL.
      ...(params.model ? { model: params.model } : {}),
      stream: true,
      agentic: params.agentic ?? false,
      web_search: params.webSearch ?? false,
      mode: params.mode ?? "rag",
    }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    throw new Error(`Chat request failed (${response.status}): ${text}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const jsonStr = trimmed.slice(5).trim();
      if (!jsonStr) continue;
      try {
        yield JSON.parse(jsonStr) as ChatStreamEvent;
      } catch {
        // Skip malformed frames rather than crashing the stream
      }
    }
  }
}
