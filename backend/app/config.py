from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ENVIRONMENT: str = "development"

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_DB_URL: str  # postgresql+asyncpg://...

    # Auth
    JWT_SECRET: str = ""  # legacy shared-secret (HS256) projects; empty disables HS256
    JWT_ALGORITHM: str = "HS256"
    JWT_JWKS_URL: str | None = None  # default: {SUPABASE_URL}/auth/v1/.well-known/jwks.json
    JWT_AUDIENCE: str = "authenticated"  # Supabase user access tokens

    # AI Providers
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: str = ""
    # Chat/rerank/vision LLM endpoint. Any OpenAI-compatible API works, e.g. OpenRouter:
    #   LLM_BASE_URL=https://openrouter.ai/api/v1  LLM_API_KEY=<openrouter key>
    #   DEFAULT_LLM_MODEL=<an OpenRouter model id>  RERANKER_MODEL=<same or another>
    # Unset = OpenAI with OPENAI_API_KEY.
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None  # falls back to OPENAI_API_KEY
    # Embeddings are configured separately: OpenRouter's free models are chat-only, so
    # embeddings usually stay on OpenAI (or another OpenAI-compatible embeddings endpoint).
    EMBEDDING_BASE_URL: str | None = None
    EMBEDDING_API_KEY: str | None = None  # falls back to OPENAI_API_KEY

    # App
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    FRONTEND_URL: str = "http://localhost:3000"

    # Email (Resend) — used for transactional emails sent directly from the backend
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@archivolt.dev"

    # Embedding
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_BATCH_SIZE: int = 100

    # Chunking
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64

    # Retrieval
    RETRIEVAL_TOP_K: int = 20
    RERANK_TOP_K: int = 10
    MIN_RELEVANCE_SCORE: float = 0.25
    SCORE_FILTER_THRESHOLD: float = 0.3
    CHUNKING_MODEL: str = "gpt-4o-mini"  # used by the agentic chunker
    MAX_AGENTIC_CHUNK_CALLS: int = 20  # LLM calls per document for agentic chunking
    MAX_CHUNKS_PER_DOCUMENT: int = 4  # 0 disables the per-document diversity cap
    MAX_CONTEXT_TOKENS: int = 4096

    # LLM
    DEFAULT_LLM_MODEL: str = "gpt-4o"
    RERANKER_MODEL: str = "gpt-4o-mini"
    RERANKER_PROVIDER: str = "llm"  # llm | cohere | none
    COHERE_API_KEY: str = ""
    COHERE_RERANK_MODEL: str = "rerank-v3.5"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 2048

    # Advanced retrieval
    ENABLE_ADAPTIVE_ROUTING: bool = True
    # CAG (full-context answering) token budget. A KB whose current, visible content exceeds
    # this is not CAG-eligible and falls back to RAG (never silently truncated).
    CAG_MAX_TOKENS: int = 12000
    # Sufficiency gate: does the evidence cover what the question needs?
    ENABLE_SUFFICIENCY_GATE: bool = True
    DECISION_PROVIDER: str = "rules"  # rules | llm | jev (llm/jev land in V2)
    SUFFICIENCY_MIN_COVERAGE: float = 0.5  # share of the question's key terms found in evidence
    SUFFICIENCY_HIGH_CONFIDENCE: float = 0.8  # a reranker score this high overrides lexical gaps
    MAX_RETRIEVAL_EXPANSIONS: int = 2  # extra strategies tried when evidence is insufficient
    # Documents still in an in-flight ingestion status after this long are marked failed.
    INGESTION_STUCK_AFTER_MINUTES: int = 30
    # Background jobs (see domains/jobs). Failed jobs retry with exponential backoff.
    JOB_MAX_ATTEMPTS: int = 3
    JOB_RETRY_BASE_S: float = 5.0
    JOB_RETRY_MAX_S: float = 300.0
    JOB_TIMEOUT_S: float = 600.0  # a single attempt is cancelled after this long
    JOB_LOCK_TIMEOUT_S: float = 900.0  # a 'running' job older than this is presumed orphaned
    JOB_POLL_INTERVAL_S: float = 2.0
    # Run the polling worker inside the API process (retries, orphan recovery). Turn off when
    # running dedicated workers with `python -m app.worker`.
    JOB_WORKER_IN_PROCESS: bool = True
    # If the claim verifier itself fails, abstain instead of returning the answer flagged
    # as 'unverified'.
    REQUIRE_VERIFICATION: bool = False
    # Abstain (instead of answering and exposing the conflict) when sources disagree
    # and the resolver cannot pick a winner.
    ABSTAIN_ON_UNRESOLVED_CONFLICT: bool = False
    ENABLE_NEIGHBOR_EXPANSION: bool = True
    # Also pull in the rest of a hit's section (parent context). Off by default: it can add
    # a lot of text; the context budget still bounds what reaches the LLM.
    ENABLE_PARENT_EXPANSION: bool = False
    # Flag (never block) a new upload sharing at least this fraction of chunks with another
    # current document in the same KB. 0 disables the check.
    NEAR_DUPLICATE_THRESHOLD: float = 0.9
    ENABLE_SECTION_SUMMARIES: bool = False  # costs one LLM call per section at ingest

    # Agentic retrieval (opt-in per request; hard bounds on every run)
    ENABLE_AGENTIC_RAG: bool = True
    AGENT_MAX_STEPS: int = 4
    AGENT_MAX_TOKENS: int = 8000  # total planner tokens (prompt + completion) per run
    AGENT_TIMEOUT_S: float = 30.0
    # Web search is an explicitly controlled external source. It only runs when ALL hold:
    # this flag, the organization's admin opt-in (settings.web_search_enabled) and the
    # user's per-request toggle. Only the search query leaves the system.
    ENABLE_WEB_SEARCH: bool = False
    WEB_SEARCH_PROVIDER: str = "brave"  # brave | none
    BRAVE_API_KEY: str = ""
    WEB_SEARCH_MAX_RESULTS: int = 5
    TOOL_TIMEOUT_S: float = 10.0  # default per-call timeout for agent tools

    # Multimodal ingestion (vision-model OCR + figure descriptions; costs per image)
    ENABLE_VISION_INGESTION: bool = False  # also gates image-file ingestion (OCR)
    OCR_PROVIDER: str = "vision"
    VISION_MODEL: str = "gpt-4o"
    MAX_VISION_CALLS_PER_DOC: int = 30
    MIN_FIGURE_PIXELS: int = 150  # skip embedded images smaller than this on either side
    SCANNED_PAGE_MIN_CHARS: int = 25  # pages with less text than this, plus an image, are OCR'd

    # Storage
    STORAGE_BUCKET: str = "documents"
    MAX_UPLOAD_SIZE_MB: int = 50
    # Per user, per organization, per minute (in-process; each worker counts separately).
    # 0 disables the limit.
    RATE_LIMIT_CHAT_PER_MIN: int = 20
    RATE_LIMIT_SEARCH_PER_MIN: int = 60
    RATE_LIMIT_UPLOAD_PER_MIN: int = 20
    # Estimated LLM spend cap per organization per UTC day, in USD. 0 disables it.
    ORG_DAILY_LLM_BUDGET_USD: float = 0.0
    MAX_PDF_PAGES: int = 500


settings = Settings()
