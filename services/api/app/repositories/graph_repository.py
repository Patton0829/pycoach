from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ErrorType,
    GraphUpdateEvent,
    KnowledgeNode,
    Learner,
    LearnerErrorNode,
    LearnerKnowledgeNode,
)


class GraphRepository:
    def __init__(self, database: Session) -> None:
        self.database = database

    def learner_exists(self, learner_id: str) -> bool:
        return self.database.get(Learner, learner_id) is not None

    def list_knowledge_nodes(
        self,
        learner_id: str,
    ) -> Sequence[tuple[KnowledgeNode, Optional[LearnerKnowledgeNode]]]:
        statement = (
            select(KnowledgeNode, LearnerKnowledgeNode)
            .outerjoin(
                LearnerKnowledgeNode,
                (LearnerKnowledgeNode.knowledge_node_id == KnowledgeNode.id)
                & (LearnerKnowledgeNode.learner_id == learner_id),
            )
            .order_by(KnowledgeNode.difficulty, KnowledgeNode.id)
        )
        return self.database.execute(statement).all()

    def list_error_nodes(
        self,
        learner_id: str,
    ) -> Sequence[tuple[ErrorType, LearnerErrorNode]]:
        statement = (
            select(ErrorType, LearnerErrorNode)
            .join(
                LearnerErrorNode,
                LearnerErrorNode.error_type_id == ErrorType.id,
            )
            .where(LearnerErrorNode.learner_id == learner_id)
            .order_by(LearnerErrorNode.severity.desc(), ErrorType.id)
        )
        return self.database.execute(statement).all()

    def get_learner_knowledge_node(
        self,
        learner_id: str,
        node_id: str,
    ) -> Optional[LearnerKnowledgeNode]:
        statement = select(LearnerKnowledgeNode).where(
            LearnerKnowledgeNode.learner_id == learner_id,
            LearnerKnowledgeNode.knowledge_node_id == node_id,
        )
        return self.database.scalar(statement)

    def get_learner_error_node(
        self,
        learner_id: str,
        error_id: str,
    ) -> Optional[LearnerErrorNode]:
        statement = select(LearnerErrorNode).where(
            LearnerErrorNode.learner_id == learner_id,
            LearnerErrorNode.error_type_id == error_id,
        )
        return self.database.scalar(statement)

    def add(self, entity: object) -> None:
        self.database.add(entity)

    def add_graph_update_event(self, event: GraphUpdateEvent) -> None:
        self.database.add(event)
