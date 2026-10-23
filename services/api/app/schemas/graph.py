from typing import List, Optional

from app.schemas.base import StrictModel
from app.schemas.assessment import AssessmentMetrics


class KnowledgeNodeSummary(AssessmentMetrics):
    node_id: str
    name: str
    display_status: str
    chapter_id: Optional[str] = None


class ErrorNodeSummary(StrictModel):
    error_id: str
    name: str
    display_status: str


class KnowledgeGraphResponse(StrictModel):
    learner_id: str
    nodes: List[KnowledgeNodeSummary]


class ErrorGraphResponse(StrictModel):
    learner_id: str
    nodes: List[ErrorNodeSummary]

