import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.domains.auth.dependencies import require_org
from app.domains.auth.schemas import CurrentUser
from app.domains.chat.schemas import (
    ChatRequest,
    ConversationDetailResponse,
    ConversationResponse,
    MessageResponse,
)
from app.domains.chat.service import chat_service

router = APIRouter()


@router.post("/")
async def send_message(
    request: ChatRequest,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    if request.stream:
        return StreamingResponse(
            _stream_response(current_user.organization_id, current_user.id, request),
            media_type="text/event-stream",
        )

    return await chat_service.send_message(
        db, current_user.organization_id, current_user.id, request
    )


async def _stream_response(org_id: uuid.UUID, user_id: uuid.UUID, request: ChatRequest):
    """Runs on its own DB session so the connection outlives the route handler's return."""
    async with AsyncSessionLocal() as db:
        try:
            async for event in chat_service.send_message_stream(db, org_id, user_id, request):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            await db.rollback()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    convs = await chat_service.list_conversations(
        db, current_user.organization_id, current_user.id
    )
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/conversations/{conv_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conv_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    conv = await chat_service.get_conversation(db, current_user.organization_id, conv_id)
    messages = await chat_service.get_messages(db, current_user.organization_id, conv_id)
    return ConversationDetailResponse(
        id=conv.id,
        knowledge_base_id=conv.knowledge_base_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.delete_conversation(db, current_user.organization_id, conv_id)
