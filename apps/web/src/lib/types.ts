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
  role: OrgRole;
  created_at: string;
}

// ─── Knowledge Bases ──────────────────────────────────────────────────────────

export type ChunkStrategy = "fixed" | "structure_aware" | "semantic" | "agentic";
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
  cag_enabled: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Documents ────────────────────────────────────────────────────────────────

export type FileType = "pdf" | "docx" | "md" | "txt" | "html" | "csv" | "json" | "image";
export type AuthorityTier = "official" | "standard" | "draft" | "informal";
export type AnswerMode = "rag" | "cag" | "hybrid";
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
  version: number;
  is_current: boolean;
  supersedes_document_id: string | null;
  superseded_at: string | null;
  effective_date: string | null;
  authority_tier: AuthorityTier;
  tags: string[];
  restricted: boolean;
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
  // 'external' = public web result (lower authority); url is only set for those.
  source_type?: "internal" | "external";
  url?: string | null;
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

export type AbstentionReason =
  | "insufficient_evidence"
  | "conflicting_sources"
  | "verification_failed"
  | "unauthorized"
  | "outdated"
  | "unsupported_question";

// verified: all claims supported. partial: unsupported claims were removed.
// unverified: the verifier failed, so the answer was NOT checked.
export type VerificationStatus = "verified" | "partial" | "unsupported" | "unverified" | "skipped";

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
  abstention_reason?: AbstentionReason | null;
  verification_status?: VerificationStatus;
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

// ─── Knowledge-base extras, document inspector ───────────────────────────────

export interface CagInfo {
  enabled: boolean;
  eligible: boolean;
  reason: string | null;
  tokens: number;
  limit: number;
}

export interface DocumentChunk {
  id: string;
  chunk_index: number;
  token_count: number;
  content: string;
  metadata: Record<string, unknown>;
  has_embedding: boolean;
}

export interface ChunkPage {
  total: number;
  items: DocumentChunk[];
}

export interface TreeNode {
  node_id: string;
  title: string;
  level: number;
  chunk_indices: number[];
  summary?: string | null;
  children: TreeNode[];
}

export interface DocumentTree {
  document_id: string;
  nodes: TreeNode[];
}

export interface DocumentSummaryItem {
  level: string;
  node_id: string | null;
  title: string;
  summary: string;
}

export interface DocumentSummaries {
  document_id: string;
  items: DocumentSummaryItem[];
}

export interface DocumentUpdate {
  authority_tier?: AuthorityTier;
  effective_date?: string | null;
  tags?: string[];
  restricted?: boolean;
}

// ─── Evaluation ──────────────────────────────────────────────────────────────

export type RetrievalStrategyName = "semantic" | "keyword" | "hybrid" | "tree" | "summary";

export interface EvalDataset {
  id: string;
  name: string;
  case_count: number;
  created_at: string;
}

export interface EvalRunConfig {
  strategy: RetrievalStrategyName;
  mode: AnswerMode;
  agentic: boolean;
  k: number;
  retrieval_only: boolean;
  access: "restricted" | "admin";
}

export interface EvalCaseResult {
  case_id: string;
  tags: string[];
  metrics: Record<string, number | null>;
  error: string | null;
}

export interface EvalRun {
  id: string;
  dataset_id: string;
  config: EvalRunConfig;
  status: "queued" | "running" | "succeeded" | "failed";
  summary: Record<string, number | null> | null;
  total_cases: number | null;
  failed_cases: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  results?: EvalCaseResult[] | null;
}

export interface MetricDelta {
  metric: string;
  baseline: number;
  candidate: number;
  delta: number;
  regressed: boolean;
}

// --- Evidence panel ---

export type ClaimStatus = "supported" | "partial" | "unsupported";

export interface ClaimVerification {
  claim: string;
  supported: boolean;
  supporting_sources: number[];
  confidence: number;
  status: ClaimStatus;
}

export interface CostMetadata {
  estimated_prompt_tokens: number;
  estimated_completion_tokens: number;
  estimated_cost_usd: number;
  token_count_method: string;
}

export interface TraceMeta {
  strategy?: string;
  answer_mode?: string;
  total_ms?: number;
}
