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

## V2 — Adaptive RAG + Decision Layer

- Query rewriting
- Multi-query
- Sub-query decomposition
- Query routing
- Retrieval strategy routing
- Parent/child retrieval
- Hierarchical summaries
- RAPTOR-style retrieval
- PageIndex-style/tree reasoning
- Adaptive retrieval
- Iterative retrieval
- SQL/structured-data retrieval foundation
- External API/application-data retrieval
- Jev DecisionProvider
- Rules / LLM / Jev decision providers
- Evidence sufficiency decisions
- Retrieval/relevance scoring
- Cost-aware model routing

**Prerequisite before this version starts:** extract `DecisionProvider` as
an ABC (`Rules`, `LLM`, and a `Jev` implementation) so sufficiency/routing
decisions are pluggable instead of hardcoded.

**Redis introduced here**, where it provides measurable value:
- RAG response/query caching
- Retrieval-result caching
- Embedding cache
- Reranker-result cache
- Query normalization/cache keys
- Rate limiting
- Short-lived agent state
- Distributed locks where needed

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

- ~~CRAG-style retrieval correction~~ — **built**: evidence gate +
  sufficiency check triggers a web-search fallback before abstaining (see
  "Current state" above)
- Self-RAG-style reflection
- ~~Evidence grading~~ — **built** (`evidence_gate.py` + `sufficiency.py`)
- ~~Claim extraction~~ — **built** (`claim_verifier.py`)
- ~~Claim-to-evidence verification~~ — **built** (`claim_verifier.py`)
- ~~Answer verification~~ — **built** (`claim_verifier.py`, drives
  rewrite-or-abstain)
- ~~Conflict resolution~~ — **built** (`conflict_detector.py` /
  `conflict_resolver.py`)
- ~~Freshness/version precedence~~ — **built** (`create_new_version()` +
  `sufficiency.py`'s `wants_current` check)
- Multi-hop retrieval — bounded single-hop expansion exists
  (`retrieval/expansion.py`); true multi-hop chaining does not yet
- ~~Agentic retrieval~~ — **built** (`domains/agent/retrieval_agent.py`)
- ~~Bounded agent loops~~ — **built** (max steps, token budget, timeout,
  no-progress cutoff)
- ~~Agent planning~~ — **built** (planner prompt + closed action space)
- ~~Tool selection~~ — **built**
- ~~Tool execution controls~~ — **built** (`tools/base.py`
  `ToolRegistry`/`ToolExecutor`, per-call audit)
- Human escalation
- Agent workflow/report generation
- ~~Prompt-injection defenses (baseline)~~ — **built**
  (`security/prompt_injection.py`); *deepened* defenses still open
- More comprehensive security testing
- **New gap found in this audit:** fine-grained knowledge-strip
  decomposition/recombination — correction today operates at chunk
  granularity, not sub-chunk strips
- **New gap found in this audit:** formal memory/retention guardrails
  (session data lifecycle, retention limits) — not found in the codebase

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

- GraphRAG
- Knowledge graphs
- Multimodal RAG
- PDF page/image/table understanding
- OCR
- SQL retrieval
- Web retrieval
- Cross-lingual retrieval
- CAG for suitable stable knowledge bases
- Google Drive
- Dropbox
- SharePoint/other enterprise sources
- S3/web connectors
- Website ingestion
- WhatsApp/Twilio
- Slack/Teams-style channels
- n8n/workflow integrations
- More ERP/LMS/CRM connectors

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

- Embedding benchmarking
- Reranker benchmarking
- Recall@K
- Precision@K
- MRR
- NDCG
- Answer accuracy
- Faithfulness/groundedness
- Retrieval-vs-answer evaluation
- Latency benchmarking
- Token/cost optimization
- Caching (mature)
- Model routing
- Speculative generation where appropriate
- Retrieval strategy A/B testing
- Automated evaluation datasets
- Regression testing
- Production observability
- Large-scale indexing/performance
- Enterprise reliability/scaling

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

**Guiding rule:** V1 stays on Postgres + pgvector + FastAPI + Next.js +
Supabase. Redis, workers/queues, and heavier observability get introduced
only as actual workload demands it — not preemptively.

---

## Why this doc exists

Ideas surfaced from RAG research, the Jev evaluation, and real client
requirements (Upwork postings for school ERP, legal KB, WhatsApp assistant,
and agent-evaluation POCs) are captured here as planned roadmap items
instead of being forgotten or causing scope creep into V1. When starting
work on any version, re-read the "Current state" section first — it should
be kept accurate rather than aspirational.
