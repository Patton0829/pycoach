from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.graph import ErrorGraphResponse, KnowledgeGraphResponse
from app.services.graph_service import GraphService, LearnerNotFoundError

router = APIRouter(prefix="/api/learners", tags=["graphs"])


@router.get(
    "/{learner_id}/knowledge-graph",
    response_model=KnowledgeGraphResponse,
)
def get_knowledge_graph(
    learner_id: str,
    database: Session = Depends(get_db),
) -> KnowledgeGraphResponse:
    try:
        return GraphService(database).get_knowledge_graph(learner_id)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=404, detail="Learner not found") from error


@router.get(
    "/{learner_id}/error-graph",
    response_model=ErrorGraphResponse,
)
def get_error_graph(
    learner_id: str,
    database: Session = Depends(get_db),
) -> ErrorGraphResponse:
    try:
        return GraphService(database).get_error_graph(learner_id)
    except LearnerNotFoundError as error:
        raise HTTPException(status_code=404, detail="Learner not found") from error
