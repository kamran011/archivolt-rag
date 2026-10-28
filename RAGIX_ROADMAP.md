# Ragix Master Roadmap

This is the canonical, versioned roadmap for Ragix. It exists so that
implementation work (by Claude Code, Cursor, or anyone else) always knows
what belongs in the current version, what must be preserved as an extension
point for a later version, and what should explicitly **not** be built yet.

**Rule for every implementation pass:** implement the current version only.
Preserve extension points for later versions. Do not implement later-version
features until they are explicitly requested, even if they look easy to add
while you're already in that file.

---

## Current state (reality check, as of this doc's creation)

V1 is implemented and running. A direct audit of `backend/app/domains/` and
`backend/app/providers/` against the architecture below found:

**Ahead of plan** — these V2 items are already implemented in V1:
- `SummaryRetriever` (`retrieval/engines/summary_engine.py`)
- `TreeRetriever` (`retrieval/engines/tree_engine.py`)
- Query analysis (`retrieval/analyzer.py`)
- Query routing / retrieval-strategy routing (`retrieval/query_router.py`, `retrieval/router.py`)
- Evidence sufficiency decisions (`retrieval/sufficiency.py`)
- Bounded iterative/expansion retrieval (`retrieval/expansion.py`)

**Most of V3 is also already implemented** (re-audited 2026-10-08 against
the actual retrieval/rag/agent code, not just the plan):
- Evidence grading — `retrieval/evidence_gate.py` (score threshold) +
  `retrieval/sufficiency.py` (term coverage, freshness/authority-aware)
- CRAG-style retrieval correction — when the gate/sufficiency check fails,
  `rag/service.py`'s web-search fallback executor runs before the system
  abstains (gated behind user request + org opt-in)
- Claim extraction, claim-to-evidence verification, answer verification —
  `rag/claim_verifier.py` (supported/partial/unsupported, drives
  rewrite-or-abstain)
- Conflict resolution — `rag/conflict_detector.py` / `conflict_resolver.py`
- Freshness/version precedence — `documents/service.py`'s
  `create_new_version()` (new version re-embedded fresh through the normal
  pipeline, old version excluded from retrieval by default but still
  queryable via `include_superseded`) + `sufficiency.py`'s `wants_current`
  check
- Agentic retrieval, bounded agent loops, agent planning, tool selection —
  `domains/agent/retrieval_agent.py`: closed tool set, max steps, planner
  token budget, wall-clock timeout, no-repeat-queries, no-progress cutoff
- Tool execution controls — `domains/tools/base.py`
  (`ToolRegistry`/`ToolExecutor`, closed action space, per-call audit)
- Prompt-injection defenses (baseline) — `security/prompt_injection.py`

**Still genuinely open from V3** (confirmed gaps, not just unaudited):
- Fine-grained knowledge-strip decomposition/recombination — today's
  correction operates at chunk granularity, not sub-chunk strips
- Self-RAG-style reflection
- True multi-hop retrieval (beyond the bounded single-hop expansion in
  `retrieval/expansion.py`)
- Human escalation
- Agent workflow/report generation
- Prompt-injection defenses *deepened*, and more comprehensive security
  testing generally
- Formal memory/retention guardrails (session data lifecycle, retention
  limits) — not found anywhere in the codebase

Treat the version labels as the *target architecture a feature belongs to*,
not a strict claim about what's unbuilt; this doc should be re-audited
whenever a new phase starts.

**Gaps against the extension-point rule — now closed:**
1. ~~No `DecisionProvider` abstraction~~ — **closed.**
   `retrieval/decisions/base.py` defines the ABC; `rules_provider.py` wraps
   the existing lexical-coverage logic unchanged (`sufficiency.py` is
   untouched, still the source of truth for the rules implementation);
   `registry.py` resolves it from `settings.DECISION_PROVIDER` (default
   `"rules"`). `rag/service.py`'s main RAG evidence path now calls the
   registry-resolved provider. V2 adding `llm`/`jev` is a new file +
   registry entry, not a call-site change.
2. ~~No `KnowledgeConnector` abstraction~~ — **closed.**
   `documents/connectors/base.py` defines the ABC and a `RawFile` result
   type; `upload_connector.py` wraps the existing bounded multipart read
   (`upload_safety.read_limited`) unchanged; `registry.py` resolves it by
   name (default `"upload"`). `DocumentService` now acquires upload bytes
   through the connector. V4 adding Drive/Dropbox/SharePoint/S3/Website is
   a new connector file + registry entry.

Both were introduced as pure wrapping refactors with no behavior change:
the full backend test suite (501 passed) and the relevant integration
tests (upload → ingest → search, tenant isolation) pass unmodified, and a
live chat query and the existing upload integration test were used to
confirm the new code paths work end-to-end through the real HTTP routers,
not just in unit tests.

Everything else already follows the pattern: `parsers/base.py`,
`chunkers/base.py`, `retrieval/engines/base.py`, `providers/llm/base.py`,
`providers/embeddings/base.py`, `providers/reranker/base.py`,
`providers/ocr/base.py`, `providers/web_search/base.py` are all real ABCs
with a registry and multiple implementations already. New strategies slot
in by adding a file + registering it, not by touching callers.

---

## V1 — Production RAG Foundation *(shipped)*

- Document ingestion/parsing
- Natural/structure-aware chunking
- Canonical document structure/tree
- Embeddings
- PostgreSQL + pgvector
- PostgreSQL FTS
- Hybrid search + RRF
- Reranking
- Metadata filtering
- Permission-aware retrieval
- Evidence selection/filtering
- Context budgeting
- Citations
- Abstention/refusal
- Conversations
- Retrieval debugger/tracing
- Multi-tenancy/RLS
- Basic evaluation foundation

**Infrastructure for V1:** PostgreSQL/pgvector + PostgreSQL FTS + Supabase +
FastAPI + Next.js. Basic application-level caching where useful, but cache
interfaces stay abstract — no Redis dependency.

---

## V2 — Adaptive RAG + Decision Layer *(shipped 2026-10-27)*

V2 is complete. Everything below is built and verified in production logs
(Jev gate, answer cache hits, cost routing). Items that were deliberately not
built were moved to **V6 — Deferred until needed**, each with the trigger that
would justify building it.

- ~~Query rewriting~~ / ~~Multi-query~~ / ~~Sub-query decomposition~~ —
  **built** (`retrieval/query_transform.py`, one bounded LLM call, opt-in via
  `ENABLE_QUERY_TRANSFORM`; extra queries fused with RRF in `rag/service.py`;
  falls back to the original query on any failure)
- ~~Incremental, content-hash-based re-embedding~~ — **built**
  (`ingestion/dedup.py`: `chunks.content_hash`; a new version reuses the
  superseded version's vectors for unchanged chunks and records
  `chunks_embedded` / `chunks_reused` / `index_lag_seconds`). Stable
  chunk-ID upsert and webhook/CDC triggers moved to V6
- ~~Corpus-level near-duplicate document detection at ingestion~~ —
  **built** (flag-only: `parsing_metadata.near_duplicates`, threshold
  `NEAR_DUPLICATE_THRESHOLD`, exact chunk-hash overlap; no fuzzy matching).
  Original gap (audited 2026-10-08): `evidence.py`'s Jaccard dedup only runs at
  query time on already-retrieved chunks. Nothing detects "this new
  upload is 90% the same content as an existing document" at ingestion
  time, so the same paragraph can sit indexed under several documents and
  silently compete/contradict at query time
- ~~Adaptive retrieval / Iterative retrieval / Query routing / Retrieval
  strategy routing / Retrieval-relevance scoring / Evidence sufficiency
  decisions~~ — **built** (V1-era: `analyzer.py`, `query_router.py`,
  `expansion.py`, `evidence_gate.py`, `sufficiency.py`)
- ~~Cost-aware model routing~~ — **built** (`providers/llm/model_router.py`,
  opt-in `ENABLE_COST_AWARE_ROUTING` + `CHEAP_LLM_MODEL`; only downgrades the
  default model for simple, small-context questions)
- ~~Jev DecisionProvider~~ / ~~Rules / LLM / Jev decision providers~~ —
  **built** (`decisions/llm_provider.py`, `decisions/jev_provider.py`;
  `DECISION_PROVIDER=rules|llm|jev`). Both fall back to the rules verdict on
  any failure. Jev uses TypeSafe's real System One API
  (`providers/typesafe/client.py`); see `docs/TYPESAFE_JEV.md`
- ~~Parent/child retrieval~~, ~~Hierarchical summaries~~, ~~PageIndex-style
  tree reasoning~~ — **built** (`expansion.py` parents, `summary_engine.py`,
  `tree_engine.py`)
- RAPTOR-style retrieval — **partial**: bottom-up summaries over the
  document's own heading tree exist (`summarizer.py`, `summary_index.py`);
  clustering-based summary trees across chunks/documents moved to V6
- ~~SQL/structured-data retrieval foundation~~ — **built**
  (`tools/structured_query.py`, over CSV/JSON rows); a free-form SQL
  retriever against external databases is V4
- ~~External API/application-data retrieval~~ — **built**
  (`tools/external_api.py`: allowlisted, read-only, HTTPS-only, org opt-in)

**Prerequisite before this version starts:** extract `DecisionProvider` as
an ABC (`Rules`, `LLM`, and a `Jev` implementation) so sufficiency/routing
decisions are pluggable instead of hardcoded.

**Freshness: correctness is done, efficiency is not (confirmed gap,
audited 2026-10-08).** V1's `documents/service.py` `create_new_version()`
already guarantees no stale answers: an edited document becomes a new
version, goes through the full pipeline, and the old version is excluded
from retrieval by default. What it does *not* do is cheap: every edit
re-parses, re-chunks, and re-embeds the entire document, even if only one
paragraph changed, and there's no stable per-section chunk ID to upsert
against. There's also no webhook/CDC ingestion trigger (V1 is upload-only)
or index-lag/freshness-SLA tracking. V2 closes this by adding, per chunk:
a content hash (skip re-embedding unchanged chunks), a stable chunk ID
(so an edit upserts its own vectors instead of the whole document's), and
an index-lag metric. This is additive to `create_new_version()`, not a
replacement — document-level versioning stays the source of truth for
"what does the reader see," chunk-hash diffing is purely an embedding-cost
optimization on top of it.

**Redis introduced here** (`core/cache.py`: `Cache` ABC with `MemoryCache`
default and `RedisCache`, `CACHE_BACKEND=memory|redis`) — **built** for the items
below except where noted (all opt-in; defaults keep V1 behavior):
- ~~RAG response/query caching~~ — built (`rag/response_cache.py`,
  `ENABLE_RESPONSE_CACHE`): invalidate-on-write via document/KB reverse
  indexes, verify-on-hit against current document version + caller access,
  volatility-scaled TTL, key includes the caller's access scope, never
  caches abstentions, history-bearing, agentic or web answers
- Retrieval-result caching — moved to V6
- ~~Embedding cache~~ — built (`ENABLE_EMBEDDING_CACHE`, keyed by text hash)
- ~~Reranker-result cache~~ — built (`ENABLE_RERANK_CACHE`, keyed by chunk
  ids, which change whenever content changes)
- ~~Query normalization/cache keys~~ — built (whitespace/case-normalized)
- ~~Rate limiting~~ — built (shared fixed-window counter when
  `CACHE_BACKEND=redis`; fails open on cache outage)
- Short-lived agent state — V3 (agent state/workflow state live there)
- ~~Distributed locks where needed~~ — built (per-document ingestion lock
  in `ingestion/jobs.py`)

**Caching must be correctness-safe, not just a TTL.** A naive "cache by
embedding similarity above a threshold" or "cache for N minutes" design
will confidently serve stale/wrong answers — this bit someone in a recent
interview-question breakdown, worth designing against explicitly:
- Invalidate on write, not on a timer: keep a reverse index from
  `document_id` → every cached answer that cited it, so a `create_new_version()`
  call evicts every dependent cache entry immediately, not after a TTL
  expires
- TTL (when used at all) should scale with the data's volatility, not be
  one global number
- Verify-on-hit: a cheap check that a cache hit's cited source versions
  still match the current ones before serving it, not just on write

```
User Query
   |
Cache?
 |-- HIT -> cached result
 |-- MISS
       |
    Retrieval
       |
    Reranking
       |
    LLM
       |
    Store result in Redis
```

```
Document chunk
      |
Embedding cache
 |-- HIT -> reuse embedding
 |-- MISS -> embedding model -> Redis/cache
```

---

## V3 — Corrective + Agentic RAG

- ~~Evidence grading~~ — **built** (`evidence_gate.py` + `sufficiency.py`)
- ~~CRAG-style retrieval correction~~ — **built**: evidence gate +
  sufficiency check triggers a web-search fallback before abstaining (see
  "Current state" above)
- ~~Claim extraction~~ — **built** (`claim_verifier.py`)
- ~~Claim-to-evidence verification~~ — **built** (`claim_verifier.py`)
- ~~Answer verification~~ — **built** (`claim_verifier.py`, drives
  rewrite-or-abstain)
- ~~Conflict resolution~~ — **built** (`conflict_detector.py` /
  `conflict_resolver.py`)
- ~~Prompt-injection defenses (baseline)~~ — **built**
  (`security/prompt_injection.py`); *deepened* defenses still open
- ~~Tool execution controls~~ — **built** (`tools/base.py`
  `ToolRegistry`/`ToolExecutor`, per-call audit)
- ~~Bounded agent loops~~ — **built** (max steps, token budget, timeout,
  no-progress cutoff)
- ~~Agentic retrieval~~ — **built** (`domains/agent/retrieval_agent.py`)
- ~~Agent planning~~ — **built** (planner prompt + closed action space)
- ~~Tool selection~~ — **built**
- ~~Freshness/version precedence~~ — **built** (`create_new_version()` +
  `sufficiency.py`'s `wants_current` check)
- **New gap found in this audit:** formal memory/retention guardrails
  (session data lifecycle, retention limits) — not found in the codebase
- **New gap found in this audit:** answer reproducibility/audit trail is
  partial. `RagTrace` ([observability/store.py](backend/app/domains/observability/store.py))
  already records chunk IDs, scores, model name, cost, tokens and
  per-stage drop reasons (`rag/stages.py`'s `brief()`, deliberately IDs
  and reasons, not chunk text) — solid for debugging. What's missing for
  a compliance-grade "reproduce this exact answer" request: `DEFAULT_LLM_MODEL`
  is a floating alias (`"gpt-4o"`, [config.py:58](backend/app/config.py:58)),
  not a dated/pinned snapshot, so the trace records which alias was used
  but not which underlying model version actually ran; and there's no
  prompt-template version/hash stored per trace, so a later prompt edit
  makes historical traces ambiguous about exactly what was sent
- **New gap found in this audit:** action-tiering + human-approval
  workflow for agent tool calls. Not a current bug — `domains/agent/retrieval_agent.py`'s
  tool set is deliberately read-only (search/outline/read_section/finish),
  so there is nothing irreversible to approve today. But there's no
  reversibility/blast-radius tiering framework in place, so the first
  write-capable tool added (e.g. an ERP/CRM action in V4) would need this
  built from scratch rather than slotting into an existing policy layer
- More comprehensive security testing
- Multi-hop retrieval — bounded single-hop expansion exists
  (`retrieval/expansion.py`); true multi-hop chaining does not yet
- Self-RAG-style reflection
- **New gap found in this audit:** fine-grained knowledge-strip
  decomposition/recombination — correction today operates at chunk
  granularity, not sub-chunk strips
- Human escalation — make it concrete (added 2026-10-13, from a
  customer-support chatbot job spec):
  - Triggers: the user asks for a human, the user seems frustrated, or the
    answer abstains (no supporting evidence in the knowledge base)
  - Handoff: send the full conversation (messages, cited sources, abstain
    reason) to the team via Slack or email, with a link back to the trace
  - Escalation rules (trigger list, destination) are per-organization
    settings, not code, so an admin can change them without a deploy
  - Reuse the existing abstain/evidence-gate signals; don't add a new
    classifier unless frustration detection can't be done with a rule
- Agent workflow/report generation

**Redis for agentic workloads:**
- Agent state/cache
- Workflow state
- Temporary retrieval results
- Tool-result caching
- Conversation/session acceleration
- Distributed locks
- Background job coordination where appropriate

```
Agent
 |
Redis state
 |
Tool
 |
Redis tool-result cache
 |
Agent
```

---

## V4 — Enterprise Retrieval & Integrations

- Self-hosted/open-weight LLM option (vLLM + Llama/Mistral or similar) for
  air-gapped or regulated deployments — confirmed gap (audited 2026-10-08):
  `providers/llm/` only has `openai_provider.py` and `anthropic_provider.py`;
  `base.py` is already an ABC with a registry, so this is a new provider
  file + registry entry, not a call-site change, but "no third-party AI
  provider reachable" scenarios (banking/healthcare RFPs) can't be met
  today
- PDF page/image/table understanding
- OCR
- Multimodal RAG
- SQL retrieval
- Google Drive
- SharePoint/other enterprise sources
- Dropbox
- S3/web connectors
- Website ingestion
- Web retrieval
- CAG for suitable stable knowledge bases
- Knowledge graphs
- GraphRAG
- Cross-lingual retrieval
- More ERP/LMS/CRM connectors
- Slack/Teams-style channels
- WhatsApp/Twilio
- n8n/workflow integrations
- Embeddable website chat widget (added 2026-10-13) — one script tag, answers
  from a chosen KB, anonymous visitors scoped to that KB only (never an org
  member's access scope). Ship this before WhatsApp: no third-party
  approval, cheaper, and it exercises the same public-chat API
- Lead capture from chat (added 2026-10-13) — collect name, email and issue
  type during a conversation and push it to a CRM or Google Sheets through
  the CRM-connector item above. Collection must be consent-aware and
  covered by the V3 retention guardrails

**Prerequisite before this version starts:** extract `KnowledgeConnector` as
an ABC (`Upload`, `Website`, `S3`, `External APIs` already; `Google Drive`,
`Dropbox`, `SharePoint` added here) so new sources slot in without touching
the ingestion pipeline.

**Redis/infra at production scale:**

```
                    RAGIX
                        |
              +---------+---------+
              v                   v
         PostgreSQL             Redis
         Source of Truth        Fast State
              |                   |
              |            +------+------+
              |            v      v      v
              |          Cache  Locks  Queues*
              |
              v
         RAG / Agents
```

`*` For queues, choose deliberately between Redis-based infrastructure and
something like SQS rather than defaulting to Redis for everything.

---

## V5 — Optimization, Evaluation & Scale

- Regression testing — specifically: run the golden eval set automatically
  whenever the LLM/embedding provider updates its default model, and
  canary-compare old-vs-new output distributions on a traffic slice before
  promoting, instead of only evaluating at launch/upload time. Confirmed
  gap (audited 2026-10-08): the eval harness (`backend/app/evals/`) exists
  and can run datasets on demand, but nothing triggers it on a schedule or
  on a provider-side model change — drift (provider or corpus) would only
  surface from a user complaint, not a metric
- Production observability
- Failure alerting (added 2026-10-13) — notify admins by Slack or email
  when ingestion jobs fail repeatedly, chat requests error out, or the
  provider is unreachable. Today failures only show in logs and in the
  document's `failed` status. Alert on rates over a window, not every
  single error, so it doesn't become noise
- Faithfulness/groundedness
- Answer accuracy
- Retrieval-vs-answer evaluation
- Automated evaluation datasets
- Recall@K
- Precision@K
- MRR
- NDCG
- Retrieval strategy A/B testing
- Large-scale indexing/performance
- Enterprise reliability/scaling
- Latency benchmarking
- Token/cost optimization
- Caching (mature)
- Model routing
- Embedding benchmarking
- Reranker benchmarking
- Speculative generation where appropriate

---

## V6 — Deferred until needed

Items moved out of V2 on purpose. Each is cheap to describe and expensive or
risky to build, and none would change what users see today. Build one only when
its trigger happens, not preemptively.

- **Stable chunk-ID upserts on document edits.** Unchanged chunks already reuse
  their embeddings (content hash), so the only saving left is database rows.
  Upserting chunks in place conflicts with `create_new_version()`, which keeps
  the old version's chunks for historical queries and for traces/citations that
  reference chunk ids. Trigger: V4 sync connectors (Drive, SharePoint) editing
  large documents often, or version storage becoming a real cost.
- **Webhook/CDC ingestion triggers.** Uploads are the only ingestion source
  today. Trigger: the V4 connectors (webhook processing is already a V4 infra
  item).
- **Retrieval-result caching.** A repeated question is served by the answer
  cache before retrieval runs, and a different question has a different key,
  so it would rarely hit; it would also need the same scope- and
  version-aware invalidation as the answer cache. Trigger: profiling shows
  retrieval itself dominating latency for non-repeated questions.
- **RAPTOR-style clustering across chunks/documents.** Needs global
  re-clustering and LLM summarization on every upload or edit, which conflicts
  with per-document incremental ingestion. Heading-tree summaries already cover
  structured documents. Trigger: evals show failures on broad, cross-document
  questions.
- **Jev threshold tuning.** The 0.7 / 0.3 Noul thresholds are TypeSafe's
  suggested starting points. Trigger: an eval set built from real customer
  documents (rules vs jev comparison), e.g. via Ragas.

---

## Target architecture (extension points to preserve from V1 onward)

```
Retriever
├── VectorRetriever
├── KeywordRetriever
├── HybridRetriever
├── SummaryRetriever       (already built)
├── TreeRetriever          (already built)
├── SQLRetriever           <- V2/V4
├── GraphRetriever         <- V4
├── WebRetriever           <- V4
└── MultimodalRetriever    <- V4
```

```
DecisionProvider            (abstracted: retrieval/decisions/)
├── Rules                   (built - rules_provider.py)
├── LLM                     <- V2
└── Jev                     <- V2
```

```
KnowledgeConnector           (abstracted: documents/connectors/)
├── Upload                   (built - upload_connector.py)
├── Website                 <- V4
├── S3                      <- V4
├── Google Drive            <- V4
├── Dropbox                 <- V4
├── SharePoint               <- V4
└── External APIs           <- V4
```

---

## Infrastructure checklist (track, don't build until needed)

| Component | Purpose | Version |
|---|---|---|
| PostgreSQL | Source of truth | V1 |
| pgvector | Vector retrieval | V1 |
| Redis | Caching/state/rate limiting | V2+ |
| SQS or equivalent | Durable background jobs | as needed |
| Object storage | Documents/raw files | V1 |
| CDN | Frontend/static assets | as needed |
| Search engine (beyond PG FTS) | If FTS becomes insufficient | as needed |
| Observability (logs/traces/metrics) | Production visibility | V5, earlier if needed |
| Secrets/config management | Already via env + Supabase | ongoing |
| Job workers | Background processing | V1 (basic), matures later |
| Scheduled jobs | Periodic tasks | as needed |
| Distributed locks | Coordination at scale | V3+ |
| Idempotency | Safe retries | ongoing |
| Retry/dead-letter handling | Reliability | V3+ |
| Webhook processing | Integrations | V4 |
| API rate limiting | Already partially built (per-user limits) | V1 (basic), Redis-backed in V2 |
| Usage/cost tracking | Already built (usage ledger) | V1 |
| Content-hash chunk diffing | Skip re-embedding unchanged chunks on document edit | V2 |

**Guiding rule:** V1 stays on Postgres + pgvector + FastAPI + Next.js +
Supabase. Redis, workers/queues, and heavier observability get introduced
only as actual workload demands it — not preemptively.

---

## Upwork RAG quality issues — gap analysis (2026-10-26)

Three Upwork job postings were analyzed for RAG failure patterns. All nine
issues map to features that are already implemented or explicitly on the roadmap:

| Issue | Status |
|---|---|
| Wrong document retrieved | **Built** — hybrid search + LLM reranker + RRF |
| Hallucination / ignores context | **Built** — grounding prompt (7 explicit rules in `rag/prompts.py`), claim verifier, sufficiency gate |
| Says "can't find" when answer exists | **Built** — adaptive query rewriting + sub-query decomposition (`retrieval/query_transform.py`) |
| Old version quoted after update | **Fixed on main (2026-10-28)** — the previous version is superseded only after the new one is ingested successfully (`IngestionService._supersede_previous`), in the same transaction as the new chunks; a failed ingestion leaves the old version current |
| Users get answers from restricted docs | **Built** — `visible_document_clause(scope)` in `retrieval/access.py`, cache key includes scope |
| Chunking strategy | **Built** — 4 strategies: fixed, structure-aware, semantic, agentic (default: structure-aware) |
| Prompts need rewriting | **Built** — strong grounding prompt already in place; Step 0c eval provides measurable baseline |
| Source citations with page numbers | **Built** — all chunkers store `page_number` in metadata; citation parser reads it; frontend shows `p.N` in EvidencePanel and CitationChip |
| Eval test set | **Built** — `backend/evals/datasets/v2.jsonl` (30 cases: follow-ups, comparisons, abstain cases) over `backend/evals/corpus/` |

One configuration flag to enable once a live eval run passes (not done yet: needs real API keys):
- `REQUIRE_VERIFICATION=True` (currently `False`) — makes the system abstain when the
  claim verifier itself errors, rather than returning an unverified answer. Safe to flip
  once the gpt-4o-mini verifier eval shows no regression on `evals/datasets/v2.jsonl`.

---

## Why this doc exists

Ideas surfaced from RAG research, the Jev evaluation, and real client
requirements (Upwork postings for school ERP, legal KB, WhatsApp assistant,
and agent-evaluation POCs) are captured here as planned roadmap items
instead of being forgotten or causing scope creep into V1. When starting
work on any version, re-read the "Current state" section first — it should
be kept accurate rather than aspirational.
