import uuid

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import IngestionError, NotFoundError
from app.domains.documents.storage import storage_service
from app.domains.ingestion.chunkers import get_chunker
from app.domains.ingestion.parsers import get_parser
from app.domains.ingestion.summarizer import summarize_tree
from app.domains.retrieval.tree import build_tree, tree_to_json
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.providers.cost import estimate_embedding_cost, estimate_llm_cost
from app.providers.embeddings.registry import get_embedding_provider
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

            chunker = get_chunker(kb.chunk_strategy)
            chunk_data_list = chunker.chunk(parsed, kb.chunk_size, kb.chunk_overlap)

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

            embedding_provider = get_embedding_provider(kb.embedding_model)
            texts = [c.content for c in chunk_data_list]
            embeddings = await embedding_provider.embed_texts(texts)
            embedding_token_total = sum(c.token_count for c in chunk_data_list)

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

            # Document tree (heading outline -> chunk indices) for tree navigation.
            # Stored in parsing_metadata; no dedicated table.
            tree_nodes = build_tree(chunk_data_list)
            if settings.ENABLE_SECTION_SUMMARIES:
                await summarize_tree(tree_nodes, chunk_data_list)

            document.chunk_count = len(chunk_rows)
            document.status = DocumentStatus.ready
            document.error_message = None
            document.parsing_metadata = {
                **(document.parsing_metadata or {}),
                "tree": tree_to_json(tree_nodes),
                **({"injection_flagged_chunks": flagged_chunk_count} if flagged_chunk_count else {}),
                "embedding_tokens": embedding_token_total,
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

    async def reprocess_document(self, db: AsyncSession, doc_id: uuid.UUID) -> None:
        # Remove existing chunks before re-running the pipeline
        await db.execute(delete(Chunk).where(Chunk.document_id == doc_id))
        document = await db.get(Document, doc_id)
        if document:
            document.status = DocumentStatus.pending
            document.chunk_count = 0
            document.error_message = None
            await db.flush()

        await self.ingest_document(db, doc_id)


ingestion_service = IngestionService()
