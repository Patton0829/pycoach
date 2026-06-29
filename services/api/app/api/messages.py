from fastapi import APIRouter, Depends, HTTPException, status

from app.core.orchestrator import get_session_orchestrator
from app.schemas.message import MessageAcceptedResponse, StudentMessageRequest
from app.services.session_orchestrator import (
    LearningSessionOrchestrator,
    SessionBusyError,
    SessionNotFoundError,
)

router = APIRouter(prefix="/api/sessions", tags=["messages"])


@router.post(
    "/{session_id}/messages",
    response_model=MessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    session_id: str,
    request: StudentMessageRequest,
    orchestrator: LearningSessionOrchestrator = Depends(get_session_orchestrator),
) -> MessageAcceptedResponse:
    try:
        return orchestrator.accept_message(
            session_id,
            request.content,
            request.client_message_id,
        )
    except SessionNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
    except SessionBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
