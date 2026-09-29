import uuid
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.domains.chat.schemas import ChatRequest, ConversationCreate
from app.domains.rag.schemas import RAGRequest, RAGResponse
from app.domains.rag.service import rag_service
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole

logger = structlog.get_logger()

MAX_HISTORY_MESSAGES = 10


class ChatService:
    async def create_conversation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ConversationCreate,
    ) -> Conversation:
        conv = Conversation(
            organization_id=org_id,
            knowledge_base_id=data.knowledge_base_id,
            user_id=user_id,
            title=data.title,
        )
        db.add(conv)
        await db.flush()
        return conv

    async def get_conversation(
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID
    ) -> Conversation:
        stmt = select(Conversation).where(
            Conversation.id == conv_id, Conversation.organization_id == org_id
        )
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            raise NotFoundError(f"Conversation {conv_id} not found")
        return conv

    async def list_conversations(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.organization_id == org_id, Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_messages(
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID
    ) -> list[Message]:
        conv = await self.get_conversation(db, org_id, conv_id)
        return list(conv.messages)

    async def delete_conversation(
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID
    ) -> None:
        conv = await self.get_conversation(db, org_id, conv_id)
        await db.delete(conv)
        await db.flush()

    async def _resolve_conversation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        request: ChatRequest,
    ) -> Conversation:
        if request.conversation_id:
            return await self.get_conversation(db, org_id, request.conversation_id)

        kb_id = request.knowledge_base_ids[0] if request.knowledge_base_ids else None
        title = request.message[:80]
        conv = Conversation(
            organization_id=org_id,
            knowledge_base_id=kb_id,
            user_id=user_id,
            title=title,
        )
        db.add(conv)
        await db.flush()
        return conv

    async def _build_history(self, conv: Conversation) -> list[dict]:
        recent = list(conv.messages)[-MAX_HISTORY_MESSAGES:]
        return [
            {"role": m.role.value, "content": m.content}
            for m in recent
            if m.role in (MessageRole.user, MessageRole.assistant)
        ]

    async def send_message(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        request: ChatRequest,
    ) -> RAGResponse:
        conv = await self._resolve_conversation(db, org_id, user_id, request)
        history = await self._build_history(conv)

        db.add(
            Message(conversation_id=conv.id, role=MessageRole.user, content=request.message)
        )
        await db.flush()

        rag_response = await rag_service.query(
            db,
            org_id,
            RAGRequest(
                query=request.message,
                knowledge_base_ids=request.knowledge_base_ids,
                conversation_history=history,
                model=request.model,
                agentic=request.agentic,
            ),
        )

        db.add(
            Message(
                conversation_id=conv.id,
                role=MessageRole.assistant,
                content=rag_response.answer,
                citations=[c.model_dump(mode="json") for c in rag_response.citations],
                retrieval_metadata={
                    **rag_response.retrieval_metadata,
                    "abstention_reason": (
                        rag_response.abstention_reason.value
                        if rag_response.abstention_reason
                        else None
                    ),
                    "verification_status": rag_response.verification_status,
                },
                token_usage={
                    "prompt_tokens": rag_response.retrieval_metadata.get("prompt_tokens"),
                    "completion_tokens": rag_response.retrieval_metadata.get("completion_tokens"),
                    "estimated_cost_usd": rag_response.retrieval_metadata.get("estimated_cost_usd"),
                },
                abstained=rag_response.abstained,
            )
        )
        await db.flush()

        return rag_response

    async def send_message_stream(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        conv = await self._resolve_conversation(db, org_id, user_id, request)
        history = await self._build_history(conv)

        db.add(
            Message(conversation_id=conv.id, role=MessageRole.user, content=request.message)
        )
        await db.flush()
        await db.commit()  # ensure conversation/user message are visible before streaming starts

        full_answer_parts: list[str] = []
        final_event: dict = {}

        async for event in rag_service.query_stream(
            db,
            org_id,
            RAGRequest(
                query=request.message,
                knowledge_base_ids=request.knowledge_base_ids,
                conversation_history=history,
                model=request.model,
                agentic=request.agentic,
            ),
        ):
            if event["type"] == "token":
                full_answer_parts.append(event["content"])
            else:
                final_event = event
            yield {**event, "conversation_id": str(conv.id)}

        db.add(
            Message(
                conversation_id=conv.id,
                role=MessageRole.assistant,
                # Verification may have replaced what was streamed (partial -> rewritten,
                # unsupported -> abstention); history must keep the final text, not the draft.
                content=final_event.get("final_answer") or "".join(full_answer_parts),
                citations=final_event.get("citations"),
                retrieval_metadata={
                    "abstention_reason": final_event.get("abstention_reason"),
                    "verification_status": final_event.get("verification_status"),
                    "evidence_gate": final_event.get("evidence_gate"),
                    "conflicts": final_event.get("conflicts"),
                    "agent": final_event.get("agent"),
                    "trace_id": final_event.get("trace_id"),
                    "span_ms": final_event.get("span_ms"),
                    **(final_event.get("cost_metadata") or {}),
                },
                token_usage=final_event.get("cost_metadata"),
                abstained=final_event.get("abstained", False),
            )
        )
        await db.flush()
        await db.commit()


chat_service = ChatService()
