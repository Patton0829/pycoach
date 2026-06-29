from sqlalchemy.orm import Session

from app.models.entities import Question, QuestionReviewRecord
from app.schemas.critic import QuestionReview


class QuestionReviewRepository:
    def __init__(self, database: Session) -> None:
        self.database = database

    def get_question(self, question_id: str) -> Question | None:
        return self.database.get(Question, question_id)

    def save(
        self,
        question: Question,
        review: QuestionReview,
        update_question_status: bool = True,
    ) -> QuestionReviewRecord:
        record = QuestionReviewRecord(
            question_id=question.id,
            status=review.status,
            quality_score=review.quality_score,
            issues_json=review.issues,
            grading_notes=review.grading_notes,
        )
        if update_question_status:
            question.status = review.status
        self.database.add(record)
        self.database.flush()
        return record
