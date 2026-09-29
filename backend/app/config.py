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
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str = "authenticated"  # Supabase user access tokens

    # AI Providers
    OPENAI_API_KEY: str
    ANTHROPIC_API_KEY: str = ""

    # App
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

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
    MAX_CONTEXT_TOKENS: int = 4096

    # LLM
    DEFAULT_LLM_MODEL: str = "gpt-4o"
    RERANKER_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 2048

    # Advanced retrieval
    ENABLE_ADAPTIVE_ROUTING: bool = True
    # Documents still in an in-flight ingestion status after this long are marked failed.
    INGESTION_STUCK_AFTER_MINUTES: int = 30
    # If the claim verifier itself fails, abstain instead of returning the answer flagged
    # as 'unverified'.
    REQUIRE_VERIFICATION: bool = False
    # Abstain (instead of answering and exposing the conflict) when sources disagree
    # and the resolver cannot pick a winner.
    ABSTAIN_ON_UNRESOLVED_CONFLICT: bool = False
    ENABLE_NEIGHBOR_EXPANSION: bool = True
    ENABLE_SECTION_SUMMARIES: bool = False  # costs one LLM call per section at ingest

    # Agentic retrieval (opt-in per request; hard bounds on every run)
    ENABLE_AGENTIC_RAG: bool = True
    AGENT_MAX_STEPS: int = 4
    AGENT_MAX_TOKENS: int = 8000  # total planner tokens (prompt + completion) per run
    AGENT_TIMEOUT_S: float = 30.0

    # Multimodal ingestion (vision-model OCR + figure descriptions; costs per image)
    ENABLE_VISION_INGESTION: bool = False
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
