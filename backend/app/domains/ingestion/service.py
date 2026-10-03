import uuid

import structlog
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import IngestionError, NotFoundError
from app.domains.documents.storage import storage_service
from app.domains.ingestion.chunkers import get_chunker
from app.domains.ingestion.parsers import get_parser
from app.domains.ingestion.summarizer import summarize_tree
from app.domains.ingestion.summary_index import build_summary_rows
from app.domains.retrieval.tree import build_tree, tree_to_json
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.document_row import DocumentRow
from app.models.knowledge_base import ChunkStrategy, KnowledgeBase
from app.models.summary import DocumentSummary
from app.providers.cost import estimate_embedding_cost, estimate_llm_cost
from app.providers.embeddings.registry import get_embedding_provider
from app.providers.llm.registry import get_llm_provider
from app.security.prompt_injection import scan_for_injection_patterns

logger = structlog.get_logger()


class IngestionService:
    async def ingest_document(self, db: AsyncSession, doc_id: uuid.UUID) -> None:
        document = await db.get(Document, doc_id)
        if not document:
            raise NotFoundError(f"Document {doc_id} not found")

        kb = await db.get(KnowledgeBase, document.knowledge_base_id)
        if not kb:
            raise NotFoundError(f"Knowledge base {document.knowledge_base_id} not found")

        try:
            # 1. Download
            content = await storage_service.download_file(document.storage_path)

            # 2. Parse
            document.status = DocumentStatus.parsing
            await db.flush()

            parser = get_parser(document.file_type)
            parsed = await parser.parse(content, document.file_name)

            document.parsing_metadata = {
                "page_count": len(parsed.pages),
                "element_count": len(parsed.all_elements()),
                **parsed.metadata,
            }
            if parsed.metadata.get("vision_calls"):
                document.parsing_metadata["vision_cost_usd"] = round(
                    estimate_llm_cost(
                        parsed.metadata.get("vision_prompt_tokens", 0),
                        parsed.metadata.get("vision_completion_tokens", 0),
                        parsed.metadata.get("vision_model", settings.VISION_MODEL),
                    ),
                    6,
                )
            embedding_token_total = 0
            document.page_count = len(parsed.pages)
            await db.flush()

            # 3. Chunk
            document.status = DocumentStatus.chunking
            await db.flush()

            embedding_provider = get_embedding_provider(kb.embedding_model)
            chunker = get_chunker(
                kb.chunk_strategy,
                embed=embedding_provider.embed_texts,
                llm=(
                    get_llm_provider(settings.CHUNKING_MODEL)
                    if kb.chunk_strategy == ChunkStrategy.agentic
                    else None
                ),
            )
            chunk_data_list = await chunker.achunk(parsed, kb.chunk_size, kb.chunk_overlap)

            if not chunk_data_list:
                if parsed.metadata.get("scanned_pages") and not settings.ENABLE_VISION_INGESTION:
                    raise IngestionError(
                        "Document appears to be scanned images with no extractable text. "
                        "Enable ENABLE_VISION_INGESTION to OCR scanned pages."
                    )
                raise IngestionError("Document produced no chunks — content may be empty")

            # 4. Embed
            document.status = DocumentStatus.embedding
            await db.flush()

            texts = [c.content for c in chunk_data_list]
            embeddings = await embedding_provider.embed_texts(texts)
            embedding_token_total = sum(c.token_count for c in chunk_data_list)
            # Semantic chunking embeds sentences of split sections a second time.
            embedding_token_total += getattr(chunker, "embedding_tokens", 0)
            chunking_llm_cost = 0.0
            if getattr(chunker, "calls", 0):
                chunking_llm_cost = estimate_llm_cost(
                    chunker.prompt_tokens, chunker.completion_tokens, settings.CHUNKING_MODEL
                )

            # 5. Index — bulk insert chunks with embeddings
            chunk_rows = []
            flagged_chunk_count = 0

            for chunk_data, embedding in zip(chunk_data_list, embeddings, strict=True):
                # Audit-only: flag suspicious instruction-like patterns so
                # operators can review, without blocking ingestion — injected
                # text in a document is still legitimate content (see
                # app/security/prompt_injection.py for the actual defense).
                injection_flags = scan_for_injection_patterns(chunk_data.content)
                metadata = dict(chunk_data.metadata)
                # Record how this chunk was made: the KB's config can change later, so
                # each chunk keeps the strategy/size/overlap it was produced with.
                metadata["chunking"] = {
                    "strategy": kb.chunk_strategy.value,
                    "chunk_size": kb.chunk_size,
                    "chunk_overlap": kb.chunk_overlap,
                }
                if injection_flags:
                    metadata["injection_risk_flags"] = injection_flags
                    flagged_chunk_count += 1

                chunk_rows.append(
                    Chunk(
                        organization_id=document.organization_id,
                        document_id=document.id,
                        knowledge_base_id=document.knowledge_base_id,
                        content=chunk_data.content,
                        chunk_index=chunk_data.chunk_index,
                        token_count=chunk_data.token_count,
                        metadata_=metadata,
                        embedding=embedding,
                    )
                )
            db.add_all(chunk_rows)
            await self._store_rows(db, document, parsed.records)

            # Document tree (heading outline -> chunk indices) for tree navigation.
            # Stored in parsing_metadata; no dedicated table.
            tree_nodes = build_tree(chunk_data_list)
            summary_rows: list = []
            summary_stats: dict = {}
            if settings.ENABLE_SECTION_SUMMARIES:
                await summarize_tree(tree_nodes, chunk_data_list)
                summary_rows, summary_stats = await build_summary_rows(
                    document,
                    tree_nodes,
                    llm=get_llm_provider(settings.RERANKER_MODEL),
                    embedder=embedding_provider,
                )
                db.add_all(summary_rows)

            document.chunk_count = len(chunk_rows)
            document.status = DocumentStatus.ready
            document.error_message = None
            document.parsing_metadata = {
                **(document.parsing_metadata or {}),
                "tree": tree_to_json(tree_nodes),
                **({"injection_flagged_chunks": flagged_chunk_count} if flagged_chunk_count else {}),
                "embedding_tokens": embedding_token_total,
                **(
                    {
                        "summaries_indexed": len(summary_rows),
                        "summary_embedding_tokens": summary_stats.get("embedded_tokens", 0),
                    }
                    if summary_rows
                    else {}
                ),
                **(
                    {
                        "chunking_llm_calls": chunker.calls,
                        "chunking_llm_cost_usd": round(chunking_llm_cost, 6),
                    }
                    if chunking_llm_cost
                    else {}
                ),
                "embedding_cost_usd": round(
                    estimate_embedding_cost(embedding_token_total, kb.embedding_model), 6
                ),
            }
            await db.flush()

            if flagged_chunk_count:
                logger.warning(
                    "document_contains_injection_like_patterns",
                    doc_id=str(doc_id),
                    flagged_chunk_count=flagged_chunk_count,
                )

            logger.info(
                "document_ingested",
                doc_id=str(doc_id),
                chunk_count=len(chunk_rows),
                pages=len(parsed.pages),
            )

        except Exception as e:
            logger.error("ingestion_failed", doc_id=str(doc_id), error=str(e))
            document.status = DocumentStatus.failed
            document.error_message = str(e)[:2000]
            await db.flush()
            raise

    async def _store_rows(self, db: AsyncSession, document: Document, records: list[dict]) -> None:
        """Keep tabular rows in queryable form (structured_query). Bulk insert in batches."""
        if not records:
            return
        for start in range(0, len(records), 1000):
            await db.execute(
                insert(DocumentRow),
                [
                    {
                        "organization_id": document.organization_id,
                        "knowledge_base_id": document.knowledge_base_id,
                        "document_id": document.id,
                        "row_index": start + i,
                        "data": rec,
                    }
                    for i, rec in enumerate(records[start : start + 1000])
                ],
            )

    async def reprocess_document(self, db: AsyncSession, doc_id: uuid.UUID) -> None:
        # Remove existing chunks before re-running the pipeline
        await db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        await db.execute(delete(DocumentSummary).where(DocumentSummary.document_id == doc_id))
        await db.execute(delete(DocumentRow).where(DocumentRow.document_id == doc_id))
        document = await db.get(Document, doc_id)
        if document:
            document.status = DocumentStatus.pending
            document.chunk_count = 0
            document.error_message = None
            await db.flush()

        await self.ingest_document(db, doc_id)


ingestion_service = IngestionService()
