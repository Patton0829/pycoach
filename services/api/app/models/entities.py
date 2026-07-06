from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def uuid_string() -> str:
    return str(uuid4())


class Learner(Base):
    __tablename__ = "learners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer)
    learning_objective: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    target_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    relation_type: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class LearnerKnowledgeNode(Base):
    __tablename__ = "learner_knowledge_nodes"
    __table_args__ = (UniqueConstraint("learner_id", "knowledge_node_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    knowledge_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    last_practiced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ErrorType(Base):
    __tablename__ = "error_types"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    related_knowledge_nodes: Mapped[list] = mapped_column(JSON)
    remediation_strategy: Mapped[str] = mapped_column(Text)


class LearnerErrorNode(Base):
    __tablename__ = "learner_error_nodes"
    __table_args__ = (UniqueConstraint("learner_id", "error_type_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    error_type_id: Mapped[str] = mapped_column(ForeignKey("error_types.id"))
    severity: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="new")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_streak: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class LearningSession(Base):
    __tablename__ = "learning_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    status: Mapped[str] = mapped_column(String(40))
    current_question_id: Mapped[Optional[str]] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ChapterQuestionSet(Base):
    __tablename__ = "chapter_question_sets"
    __table_args__ = (UniqueConstraint("session_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    chapter_id: Mapped[str] = mapped_column(String(120))
    chapter_title: Mapped[str] = mapped_column(String(200))
    target_question_count: Mapped[int] = mapped_column(Integer, default=10)
    learner_level: Mapped[str] = mapped_column(String(30))
    average_mastery: Mapped[float] = mapped_column(Float, default=0.0)
    blueprint_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class LearningRound(Base):
    __tablename__ = "learning_rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    question_id: Mapped[Optional[str]] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(40))
    initial_verdict: Mapped[Optional[str]] = mapped_column(String(40))
    final_verdict: Mapped[Optional[str]] = mapped_column(String(40))
    discussion_summary_json: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    question_type: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[int] = mapped_column(Integer)
    student_content_json: Mapped[dict] = mapped_column(JSON)
    critic_content_json: Mapped[dict] = mapped_column(JSON)
    knowledge_node_ids: Mapped[list] = mapped_column(JSON)
    target_error_ids: Mapped[list] = mapped_column(JSON)
    pedagogical_strategy: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class QuestionReviewRecord(Base):
    __tablename__ = "question_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    status: Mapped[str] = mapped_column(String(30))
    quality_score: Mapped[float] = mapped_column(Float)
    issues_json: Mapped[list] = mapped_column(JSON)
    grading_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    role: Mapped[str] = mapped_column(String(20))
    content_markdown: Mapped[str] = mapped_column(Text)
    critic_intent: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CriticTurnResultRecord(Base):
    __tablename__ = "critic_turn_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    message_id: Mapped[str] = mapped_column(ForeignKey("conversation_messages.id"))
    intent: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(40))
    round_action: Mapped[str] = mapped_column(String(40))
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class GraphUpdateEvent(Base):
    __tablename__ = "graph_update_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    graph_type: Mapped[str] = mapped_column(String(20))
    node_id: Mapped[str] = mapped_column(String(120))
    before_value: Mapped[float] = mapped_column(Float)
    after_value: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
