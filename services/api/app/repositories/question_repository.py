from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ErrorType,
    KnowledgeEdge,
    KnowledgeNode,
    Learner,
    LearnerErrorNode,
    LearnerKnowledgeNode,
)


class QuestionRepository:
    def __init__(self, database: Session) -> None:
        self.database = database

    def learner_exists(self, learner_id: str) -> bool:
        return self.database.get(Learner, learner_id) is not None

    def list_knowledge_nodes(self) -> Sequence[KnowledgeNode]:
        return self.database.scalars(
            select(KnowledgeNode).order_by(KnowledgeNode.difficulty, KnowledgeNode.id)
        ).all()

    def list_knowledge_edges(self) -> Sequence[KnowledgeEdge]:
        return self.database.scalars(
            select(KnowledgeEdge).order_by(
                KnowledgeEdge.source_node_id,
                KnowledgeEdge.relation_type,
                KnowledgeEdge.target_node_id,
            )
        ).all()

    def list_error_types(self) -> Sequence[ErrorType]:
        return self.database.scalars(select(ErrorType).order_by(ErrorType.id)).all()

    def list_personal_knowledge(
        self,
        learner_id: str,
    ) -> Sequence[LearnerKnowledgeNode]:
        return self.database.scalars(
            select(LearnerKnowledgeNode).where(
                LearnerKnowledgeNode.learner_id == learner_id
            )
        ).all()

    def list_personal_errors(
        self,
        learner_id: str,
    ) -> Sequence[LearnerErrorNode]:
        return self.database.scalars(
            select(LearnerErrorNode).where(
                LearnerErrorNode.learner_id == learner_id
            )
        ).all()
