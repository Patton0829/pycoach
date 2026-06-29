from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import (
    ErrorType,
    GraphUpdateEvent,
    KnowledgeNode,
    LearnerErrorNode,
    LearnerKnowledgeNode,
)
from app.repositories.graph_repository import GraphRepository
from app.schemas.critic import ErrorGraphUpdate, KnowledgeGraphUpdate
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
    "not_started": "尚未学习",
    "needs_review": "需要复习",
}

ERROR_STATUS_LABELS = {
    "new": "新发现",
    "active": "需要巩固",
    "improving": "正在改善",
    "resolved": "已解决",
    "relapsed": "再次出现",
}


def apply_mastery_update(current: float, evidence: str, strength: float) -> float:
    delta = {
        "positive": 0.12,
        "partial": 0.03,
        "negative": -0.10,
        "none": 0.0,
    }[evidence]
    return max(0.0, min(1.0, current + delta * strength))


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
            nodes.append(
                KnowledgeNodeSummary(
                    node_id=node.id,
                    name=node.name,
                    display_status=KNOWLEDGE_STATUS_LABELS[status],
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
        if update.evidence == "none":
            return None
        self._require_learner(learner_id)
        if self.database.get(KnowledgeNode, update.node_id) is None:
            raise GraphNodeNotFoundError(update.node_id)
        learner_node = self.repository.get_learner_knowledge_node(
            learner_id,
            update.node_id,
        )
        if learner_node is None:
            learner_node = LearnerKnowledgeNode(
                learner_id=learner_id,
                knowledge_node_id=update.node_id,
                mastery=0.0,
                status="not_started",
                attempt_count=0,
                positive_evidence_count=0,
                negative_evidence_count=0,
            )
            self.repository.add(learner_node)

        before = learner_node.mastery or 0.0
        learner_node.mastery = apply_mastery_update(
            before,
            update.evidence,
            update.strength,
        )
        learner_node.attempt_count = (learner_node.attempt_count or 0) + 1
        learner_node.last_practiced_at = datetime.utcnow()
        learner_node.updated_at = datetime.utcnow()

        if update.evidence == "positive":
            learner_node.positive_evidence_count = (
                learner_node.positive_evidence_count or 0
            ) + 1
            learner_node.status = (
                "mastered" if learner_node.mastery >= 0.8 else "learning"
            )
        elif update.evidence == "partial":
            learner_node.status = "learning"
        else:
            learner_node.negative_evidence_count = (
                learner_node.negative_evidence_count or 0
            ) + 1
            learner_node.status = (
                "needs_review" if before >= 0.8 else "weak"
            )

        event = GraphUpdateEvent(
            learner_id=learner_id,
            round_id=round_id,
            graph_type="knowledge",
            node_id=update.node_id,
            before_value=before,
            after_value=learner_node.mastery,
            reason=update.reason,
        )
        self.repository.add_graph_update_event(event)
        self.database.flush()
        return event

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
