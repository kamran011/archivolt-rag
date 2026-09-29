/**
 * TypeScript interfaces matching the FastAPI backend Pydantic response models.
 * These will be expanded as each backend domain is built.
 * Aligned with docs/ARCHIVOLT_DATABASE_SPEC.md.
 */

// ─── Auth ────────────────────────────────────────────────────────────────────

export type OrgRole = "owner" | "admin" | "member" | "viewer";

export interface CurrentUser {
  id: string;
  email: string;
  organization_id: string | null;
  role: OrgRole | null;
}

// ─── Organizations ────────────────────────────────────────────────────────────

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  member_count?: number;
  role?: OrgRole;
}

export interface OrgMember {
  id: string;
  user_id: string;
  email: string;
  role: OrgRole;
  created_at: string;
}

// ─── Knowledge Bases ──────────────────────────────────────────────────────────

export type ChunkStrategy = "fixed" | "structure_aware";
export type KBStatus = "active" | "archived";

export interface KnowledgeBase {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  embedding_model: string;
  chunk_strategy: ChunkStrategy;
  chunk_size: number;
  chunk_overlap: number;
  status: KBStatus;
  document_count: number;
  created_at: string;
  updated_at: string;
}

// ─── Documents ────────────────────────────────────────────────────────────────

export type FileType = "pdf" | "docx" | "md" | "txt" | "html" | "csv" | "json";
export type DocumentStatus =
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "ready"
  | "failed";

export interface Document {
  id: string;
  organization_id: string;
  knowledge_base_id: string;
  title: string;
  file_name: string;
  file_type: FileType;
  file_size: number;
  status: DocumentStatus;
  page_count: number | null;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Chat & RAG ───────────────────────────────────────────────────────────────

export interface Conversation {
  id: string;
  organization_id: string;
  knowledge_base_id: string | null;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export type MessageRole = "user" | "assistant" | "system";

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  page_number: number | null;
  relevance_score: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  citations: Citation[] | null;
  abstained: boolean;
  created_at: string;
}

export interface EvidenceGateResult {
  pass_gate: boolean;
  reason: string | null;
  confidence: number;
  top_score: number;
  chunk_count: number;
}

export interface RAGResponse {
  answer: string;
  citations: Citation[];
  evidence_gate: EvidenceGateResult;
  abstained: boolean;
  retrieval_metadata: Record<string, unknown>;
}

// ─── Retrieval ────────────────────────────────────────────────────────────────

export type RetrievalStrategy = "semantic" | "keyword" | "hybrid" | "tree";

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
  retrieval_method: string;
}

export interface RetrievalResult {
  chunks: RetrievedChunk[];
  query: string;
  strategy: RetrievalStrategy;
  total_candidates: number;
  retrieval_time_ms: number;
}

// --- Conflicts & agent (Phase 2 / 5) ---

export interface ConflictInfo {
  topic: string;
  source_a: number;
  claim_a: string;
  source_b: number;
  claim_b: string;
  resolved: boolean;
  winning_source: number | null;
  resolution_reason: string | null;
}

export interface AgentStep {
  step: number;
  action: string;
  detail: string;
  new_chunks: number;
}

export interface AgentSummary {
  steps: AgentStep[];
  stop_reason: string;
  planner_tokens: number;
  planner_cost_usd: number;
}

// --- Retrieval debugger (Phase 6) ---

export interface DebugChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  preview: string;
  score: number;
  method: string;
  page: number | null;
  is_current: boolean;
  authority_tier: string;
  tokens: number | null;
  verdict: string | null;
}

export interface DebugStage {
  name: string;
  duration_ms: number;
  chunks: DebugChunk[];
  note: string | null;
}

export interface DebugResponse {
  query: string;
  route: { strategy: RetrievalStrategy; reason: string };
  routed: boolean;
  stages: DebugStage[];
  gate: EvidenceGateResult;
  final_context_chunks: number;
  final_context_tokens: number;
}

// --- Usage analytics (Phase 6) ---

export interface DailyUsage {
  date: string;
  answers: number;
  abstained: number;
  cost_usd: number;
}

export interface UsageSummary {
  days: number;
  total_answers: number;
  abstained: number;
  abstention_rate: number | null;
  total_cost_usd: number;
  avg_cost_usd: number | null;
  avg_citations: number | null;
  conflicts_flagged: number;
  agentic_answers: number;
  strategy_counts: Record<string, number>;
  avg_stage_ms: Record<string, number>;
  daily: DailyUsage[];
  truncated: boolean;
}
