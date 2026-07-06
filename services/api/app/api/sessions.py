from fastapi import APIRouter, Depends, HTTPException

from app.core.orchestrator import get_session_orchestrator
from app.schemas.session import CreateSessionRequest, SessionResponse
from app.services.chapter_questioning_service import (
    is_supported_assessment_module,
    list_assessment_options,
)
from app.services.session_orchestrator import (
    LearningSessionOrchestrator,
    SessionNotFoundError,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/modules")
def get_session_modules() -> list[dict]:
    return list_assessment_options()


@router.post("", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    orchestrator: LearningSessionOrchestrator = Depends(get_session_orchestrator),
) -> SessionResponse:
    if not is_supported_assessment_module(request.module):
        raise HTTPException(status_code=400, detail="Unsupported learning module")
    try:
        return await orchestrator.create_session(request)
    except SessionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    orchestrator: LearningSessionOrchestrator = Depends(get_session_orchestrator),
) -> SessionResponse:
    try:
        return orchestrator.get_session_response(session_id)
    except SessionNotFoundError as error:
        raise HTTPException(status_code=404, detail="Session not found") from error
