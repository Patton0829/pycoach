from typing import List

from app.schemas.base import StrictModel


class KnowledgeNodeSummary(StrictModel):
    node_id: str
    name: str
    display_status: str


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

