import tiktoken

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk

_encoding = tiktoken.get_encoding("cl100k_base")


class EvidenceFilter:
    @staticmethod
    def filter_by_score(
        chunks: list[RetrievedChunk],
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        threshold = min_score if min_score is not None else settings.SCORE_FILTER_THRESHOLD
        return [c for c in chunks if c.score >= threshold]

    @staticmethod
    def deduplicate(
        chunks: list[RetrievedChunk],
        similarity_threshold: float = 0.9,
    ) -> list[RetrievedChunk]:
        """Removes near-duplicate chunks using Jaccard similarity over token sets.
        Chunks are processed in input order (assumed pre-sorted by relevance),
        so the higher-ranked chunk of any near-duplicate pair is kept."""
        kept: list[RetrievedChunk] = []
        kept_token_sets: list[set[str]] = []

        for chunk in chunks:
            tokens = set(chunk.content.lower().split())
            is_duplicate = False
            for existing_tokens in kept_token_sets:
                if _jaccard_similarity(tokens, existing_tokens) >= similarity_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(chunk)
                kept_token_sets.append(tokens)

        return kept


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


class ContextAssembler:
    @staticmethod
    def assemble(
        chunks: list[RetrievedChunk],
        max_tokens: int | None = None,
    ) -> tuple[list[RetrievedChunk], int]:
        """Greedily packs chunks (assumed pre-sorted by descending relevance)
        into a token budget. Returns the selected chunks and total token count."""
        budget = max_tokens if max_tokens is not None else settings.MAX_CONTEXT_TOKENS
        selected: list[RetrievedChunk] = []
        total_tokens = 0

        for chunk in chunks:
            chunk_tokens = len(_encoding.encode(chunk.content))
            if total_tokens + chunk_tokens > budget:
                continue  # skip chunks that don't fit rather than truncating mid-content
            selected.append(chunk)
            total_tokens += chunk_tokens

        return selected, total_tokens

    @staticmethod
    def format_with_citations(chunks: list[RetrievedChunk]) -> str:
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            page = chunk.metadata.get("page_number")
            location = f", p.{page}" if page else ""
            parts.append(f"[Source {i} - {chunk.document_title}{location}]:\n{chunk.content}")
        return "\n\n".join(parts)
