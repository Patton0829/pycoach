from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from app.models.entities import (
    ConversationMessage,
    CriticTurnResultRecord,
)
from app.schemas.critic import CriticConversationMessage, CriticTurnResult
from app.schemas.message import StudentVisibleMessage


def create_message(
    session_id: str,
    round_id: str,
    role: str,
    content_markdown: str,
    message_id: Optional[str] = None,
    critic_intent: Optional[str] = None,
) -> ConversationMessage:
    return ConversationMessage(
        id=message_id or str(uuid4()),
        session_id=session_id,
        round_id=round_id,
        role=role,
        content_markdown=content_markdown,
        critic_intent=critic_intent,
    )


def create_turn_result_record(
    message_id: str,
    result: CriticTurnResult,
) -> CriticTurnResultRecord:
    return CriticTurnResultRecord(
        message_id=message_id,
        intent=result.intent,
        verdict=result.verdict,
        round_action=result.round_action,
        result_json=result.model_dump(mode="json"),
    )


def to_student_visible_message(message: ConversationMessage) -> StudentVisibleMessage:
    return StudentVisibleMessage(
        id=UUID(message.id),
        role=message.role,
        content_markdown=message.content_markdown,
        created_at=message.created_at or datetime.utcnow(),
    )


def to_critic_context_message(
    message: ConversationMessage,
) -> CriticConversationMessage:
    return CriticConversationMessage(
        role=message.role,
        content_markdown=message.content_markdown,
        critic_intent=message.critic_intent,
    )
