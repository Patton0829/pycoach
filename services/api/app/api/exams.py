from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.exam import ExamPaperSummary
from app.services.exam_practice_service import ExamPracticeService

router = APIRouter(prefix="/api/exams", tags=["exams"])


@router.get("", response_model=list[ExamPaperSummary])
def list_exam_papers(database: Session = Depends(get_db)) -> list[ExamPaperSummary]:
    return ExamPracticeService(database).list_papers()
