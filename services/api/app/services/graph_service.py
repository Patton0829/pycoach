from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import (
    ErrorType,
    GraphUpdateEvent,
    LearnerErrorNode,
)
from app.repositories.graph_repository import GraphRepository
from app.schemas.critic import ErrorGraphUpdate, KnowledgeGraphUpdate
from app.schemas.assessment import assessment_metrics
from app.schemas.graph import (
    ErrorGraphResponse,
    ErrorNodeSummary,
    KnowledgeGraphResponse,
    KnowledgeNodeSummary,
)

KNOWLEDGE_STATUS_LABELS = {
    "mastered": "基本掌握",
    "learning": "正在学习",
    "weak": "需要巩固",
    "not_started": "尚未测评",
    "needs_review": "需要复习",
}

ERROR_STATUS_LABELS = {
    "new": "新发现",
    "active": "需要巩固",
    "improving": "正在改善",
    "resolved": "已解决",
    "relapsed": "再次出现",
}


def apply_error_update(current: float, action: str, strength: float) -> float:
    if action in {"activate", "strengthen", "relapse"}:
        delta = 0.12
    elif action in {"weaken", "resolve"}:
        delta = -0.10
    else:
        delta = 0.0
    return max(0.0, min(1.0, current + delta * strength))


class LearnerNotFoundError(LookupError):
    pass


class GraphNodeNotFoundError(LookupError):
    pass


class GraphService:
    def __init__(self, database: Session) -> None:
        self.database = database
        self.repository = GraphRepository(database)

    def get_knowledge_graph(self, learner_id: str) -> KnowledgeGraphResponse:
        self._require_learner(learner_id)
        nodes = []
        for node, learner_node in self.repository.list_knowledge_nodes(learner_id):
            status = learner_node.status if learner_node else "not_started"
            metrics = assessment_metrics(
                (learner_node.evaluated_question_count or 0) if learner_node else 0,
                (learner_node.correct_question_count or 0) if learner_node else 0,
            )
            nodes.append(
                KnowledgeNodeSummary(
                    node_id=node.id,
                    name=node.name,
                    chapter_id=node.chapter_id,
                    display_status=KNOWLEDGE_STATUS_LABELS[status],
                    **metrics.model_dump(),
                )
            )
        return KnowledgeGraphResponse(learner_id=learner_id, nodes=nodes)

    def get_error_graph(self, learner_id: str) -> ErrorGraphResponse:
        self._require_learner(learner_id)
        nodes = [
            ErrorNodeSummary(
                error_id=error_type.id,
                name=error_type.name,
                display_status=ERROR_STATUS_LABELS[learner_error.status],
            )
            for error_type, learner_error in self.repository.list_error_nodes(learner_id)
        ]
        return ErrorGraphResponse(learner_id=learner_id, nodes=nodes)

    def commit_knowledge_update(
        self,
        learner_id: str,
        round_id: str,
        update: KnowledgeGraphUpdate,
    ) -> Optional[GraphUpdateEvent]:
        raise ValueError(
            "KnowledgeGraphUpdate is not a question result; "
            "use AssessmentService.commit_assessment with finalized per-node evidence"
        )

    def commit_error_update(
        self,
        learner_id: str,
        round_id: str,
        update: ErrorGraphUpdate,
    ) -> Optional[GraphUpdateEvent]:
        if update.action == "none":
            return None
        self._require_learner(learner_id)
        if self.database.get(ErrorType, update.error_id) is None:
            raise GraphNodeNotFoundError(update.error_id)
        learner_error = self.repository.get_learner_error_node(
            learner_id,
            update.error_id,
        )
        if learner_error is None:
            learner_error = LearnerErrorNode(
                learner_id=learner_id,
                error_type_id=update.error_id,
                severity=0.0,
                status="new",
                occurrence_count=0,
                resolved_streak=0,
            )
            self.repository.add(learner_error)

        now = datetime.utcnow()
        before = learner_error.severity or 0.0
        learner_error.severity = apply_error_update(
            before,
            update.action,
            update.strength,
        )
        learner_error.updated_at = now

        if update.action in {"activate", "strengthen", "relapse"}:
            learner_error.occurrence_count = (
                learner_error.occurrence_count or 0
            ) + 1
            learner_error.first_seen_at = learner_error.first_seen_at or now
            learner_error.last_seen_at = now
            learner_error.resolved_streak = 0
        if update.action == "relapse":
            learner_error.status = "relapsed"
        elif update.action in {"activate", "strengthen"}:
            learner_error.status = "active"
        elif update.action == "weaken":
            learner_error.status = "improving"
            learner_error.resolved_streak = (
                learner_error.resolved_streak or 0
            ) + 1
        elif update.action == "resolve":
            learner_error.status = "resolved"
            learner_error.resolved_streak = (
                learner_error.resolved_streak or 0
            ) + 1

        event = GraphUpdateEvent(
            learner_id=learner_id,
            round_id=round_id,
            graph_type="error",
            node_id=update.error_id,
            before_value=before,
            after_value=learner_error.severity,
            reason=update.reason,
        )
        self.repository.add_graph_update_event(event)
        self.database.flush()
        return event

    def _require_learner(self, learner_id: str) -> None:
        if not self.repository.learner_exists(learner_id):
            raise LearnerNotFoundError(learner_id)
