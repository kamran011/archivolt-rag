import dataclasses
import uuid
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.rate_limit import org_budget
from app.domains.chat.schemas import ChatRequest, ConversationCreate
from app.domains.escalation.service import maybe_escalate
from app.domains.observability.store import save_rag_trace
from app.domains.rag.schemas import RAGRequest, RAGResponse
from app.domains.rag.service import rag_service
from app.domains.retrieval.access import AccessScope, Actor
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.organization import Organization

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
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID, user_id: uuid.UUID
    ) -> Conversation:
        """Conversations are private to their author: scoped by org AND user. Anything
        else looks like it does not exist."""
        stmt = select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.organization_id == org_id,
            Conversation.user_id == user_id,
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

    async def _load_messages(self, db: AsyncSession, conv_id: uuid.UUID) -> list[Message]:
        # Explicit query: touching conv.messages lazy-loads, which raises MissingGreenlet
        # under AsyncSession.
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at, Message.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_messages(
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Message]:
        await self.get_conversation(db, org_id, conv_id, user_id)
        return await self._load_messages(db, conv_id)

    async def delete_conversation(
        self, db: AsyncSession, org_id: uuid.UUID, conv_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        conv = await self.get_conversation(db, org_id, conv_id, user_id)
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
            return await self.get_conversation(
                db, org_id, request.conversation_id, user_id
            )

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

    async def _with_org_settings(
        self, db: AsyncSession, org_id: uuid.UUID, actor: Actor | None
    ) -> Actor | None:
        """Attach the organization's settings (e.g. whether web search is enabled) to the
        actor. Read from the database, never from the request."""
        if actor is None:
            return None
        org = await db.get(Organization, org_id)
        return dataclasses.replace(actor, org_settings=dict(org.settings or {}) if org else {})

    async def _build_history(self, db: AsyncSession, conv: Conversation) -> list[dict]:
        recent = (await self._load_messages(db, conv.id))[-MAX_HISTORY_MESSAGES:]
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
        scope: AccessScope | None = None,
        actor: Actor | None = None,
    ) -> RAGResponse:
        conv = await self._resolve_conversation(db, org_id, user_id, request)
        history = await self._build_history(db, conv)
        actor = await self._with_org_settings(db, org_id, actor)

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
                web_search=request.web_search,
                mode=request.mode,
            ),
            scope,
            actor,
        )

        assistant = Message(
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
                    "claim_verifications": [
                        c.model_dump(mode="json") for c in rag_response.claim_verifications
                    ],
                    "conflicts": [c.model_dump(mode="json") for c in rag_response.conflicts],
                    "evidence_gate": rag_response.evidence_gate.model_dump(mode="json"),
                },
                token_usage={
                    "prompt_tokens": rag_response.retrieval_metadata.get("prompt_tokens"),
                    "completion_tokens": rag_response.retrieval_metadata.get("completion_tokens"),
                    "estimated_cost_usd": rag_response.retrieval_metadata.get("estimated_cost_usd"),
                },
                abstained=rag_response.abstained,
            )
        db.add(assistant)
        await db.flush()

        handoff = await maybe_escalate(
            db,
            org_id=org_id,
            conversation_id=conv.id,
            user_id=user_id,
            message=request.message,
            earlier_user_messages=[h["content"] for h in history if h["role"] == "user"],
            abstained=rag_response.abstained,
            assistant_message_id=assistant.id,
            trace_id=rag_response.retrieval_metadata.get("trace_id"),
        )
        if handoff:
            assistant.retrieval_metadata = {**(assistant.retrieval_metadata or {}),
                                            "handoff": handoff}
            rag_response.handoff = handoff
            await db.flush()

        md = rag_response.retrieval_metadata
        await save_rag_trace(
            db,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conv.id,
            query=request.message,
            trace_id=md.get("trace_id"),
            stages=rag_response.trace_stages,
            abstained=rag_response.abstained,
            abstention_reason=(
                rag_response.abstention_reason.value if rag_response.abstention_reason else None
            ),
            verification_status=rag_response.verification_status,
            cost_usd=md.get("estimated_cost_usd"),
            prompt_tokens=md.get("prompt_tokens"),
            completion_tokens=md.get("completion_tokens"),
            model=request.model,
        )
        org_budget.record(org_id, rag_response.retrieval_metadata.get("estimated_cost_usd"))
        return rag_response

    async def send_message_stream(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        request: ChatRequest,
        scope: AccessScope | None = None,
        actor: Actor | None = None,
    ) -> AsyncIterator[dict]:
        conv = await self._resolve_conversation(db, org_id, user_id, request)
        history = await self._build_history(db, conv)
        actor = await self._with_org_settings(db, org_id, actor)

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
                web_search=request.web_search,
                mode=request.mode,
            ),
            scope,
            actor,
        ):
            if event["type"] == "token":
                full_answer_parts.append(event["content"])
            else:
                final_event = event
            # trace_stages is persisted server-side only.
            yield {**{k: v for k, v in event.items() if k != "trace_stages"},
                   "conversation_id": str(conv.id)}

        cost = final_event.get("cost_metadata") or {}
        await save_rag_trace(
            db,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conv.id,
            query=request.message,
            trace_id=final_event.get("trace_id"),
            stages=final_event.get("trace_stages"),
            abstained=final_event.get("abstained", False),
            abstention_reason=final_event.get("abstention_reason"),
            verification_status=final_event.get("verification_status"),
            cost_usd=cost.get("estimated_cost_usd"),
            prompt_tokens=cost.get("estimated_prompt_tokens"),
            completion_tokens=cost.get("estimated_completion_tokens"),
            model=request.model,
        )
        org_budget.record(org_id, cost.get("estimated_cost_usd"))

        assistant = Message(
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
                    "claim_verifications": final_event.get("claim_verifications"),
                    "agent": final_event.get("agent"),
                    "trace_id": final_event.get("trace_id"),
                    "span_ms": final_event.get("span_ms"),
                    "strategy": final_event.get("trace_stages", {}).get("meta", {}).get("strategy"),
                    "answer_mode": final_event.get("trace_stages", {})
                    .get("meta", {})
                    .get("answer_mode"),
                    **(final_event.get("cost_metadata") or {}),
                },
                token_usage=final_event.get("cost_metadata"),
                abstained=final_event.get("abstained", False),
            )
        db.add(assistant)
        await db.flush()

        handoff = await maybe_escalate(
            db,
            org_id=org_id,
            conversation_id=conv.id,
            user_id=user_id,
            message=request.message,
            earlier_user_messages=[h["content"] for h in history if h["role"] == "user"],
            abstained=bool(final_event.get("abstained", False)),
            assistant_message_id=assistant.id,
            trace_id=final_event.get("trace_id"),
        )
        if handoff:
            assistant.retrieval_metadata = {**(assistant.retrieval_metadata or {}),
                                            "handoff": handoff}
        await db.flush()
        await db.commit()
        if handoff:
            yield {"type": "handoff", **handoff, "conversation_id": str(conv.id)}


chat_service = ChatService()
