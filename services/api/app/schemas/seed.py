from typing import List, Literal

from pydantic import Field

from app.schemas.base import StrictModel


class KnowledgeNodeSeed(StrictModel):
    id: str
    name: str
    description: str
    difficulty: int = Field(ge=1)
    learning_objective: str


class KnowledgeEdgeSeed(StrictModel):
    source_node_id: str
    target_node_id: str
    relation_type: Literal[
        "prerequisite_of",
        "contains",
        "related_to",
        "often_confused_with",
        "transfer_to",
    ]
    weight: float = Field(ge=0.0, le=1.0)


class ErrorTypeSeed(StrictModel):
    id: str
    name: str
    description: str
    related_knowledge_nodes: List[str]
    remediation_strategy: str


class SeedResult(StrictModel):
    knowledge_nodes: int
    knowledge_edges: int
    error_types: int
    learners: int
    learner_knowledge_nodes: int
    learner_error_nodes: int
