from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.dialects.mysql import DATETIME, DOUBLE, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

LONG_TEXT = Text().with_variant(LONGTEXT(), "mysql")
PRECISE_FLOAT = Float().with_variant(DOUBLE(asdecimal=False), "mysql")


def uuid_string() -> str:
    return str(uuid4())


class Learner(Base):
    __tablename__ = "learners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class CurriculumChapter(Base):
    __tablename__ = "curriculum_chapters"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    reference_url: Mapped[Optional[str]] = mapped_column(String(500))


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    chapter_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("curriculum_chapters.id", name="fk_knowledge_chapter"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(LONG_TEXT)
    difficulty: Mapped[int] = mapped_column(Integer)
    learning_objective: Mapped[str] = mapped_column(LONG_TEXT)
    reference_url: Mapped[Optional[str]] = mapped_column(String(500))
    reference_section: Mapped[Optional[str]] = mapped_column(String(40))
    is_supplementary: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    runtime_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("source_node_id", "target_node_id", "relation_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    target_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    relation_type: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(PRECISE_FLOAT, default=1.0)


class LearnerKnowledgeNode(Base):
    __tablename__ = "learner_knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("learner_id", "knowledge_node_id"),
        CheckConstraint(
            "correct_question_count >= 0 AND evaluated_question_count >= correct_question_count",
            name="ck_learner_knowledge_counts",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    knowledge_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    mastery: Mapped[float] = mapped_column(PRECISE_FLOAT, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    positive_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_question_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    correct_question_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    score_policy_version: Mapped[str] = mapped_column(
        String(64), default="correct_over_max_20_v1", server_default="correct_over_max_20_v1"
    )
    legacy_mastery: Mapped[Optional[float]] = mapped_column(PRECISE_FLOAT)
    legacy_status: Mapped[Optional[str]] = mapped_column(String(30))
    last_practiced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )
    next_review_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class ErrorType(Base):
    __tablename__ = "error_types"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(LONG_TEXT)
    related_knowledge_nodes: Mapped[list] = mapped_column(JSON)
    remediation_strategy: Mapped[str] = mapped_column(LONG_TEXT)


class LearnerErrorNode(Base):
    __tablename__ = "learner_error_nodes"
    __table_args__ = (UniqueConstraint("learner_id", "error_type_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    error_type_id: Mapped[str] = mapped_column(ForeignKey("error_types.id"))
    severity: Mapped[float] = mapped_column(PRECISE_FLOAT, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="new")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_streak: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class LearningSession(Base):
    __tablename__ = "learning_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    status: Mapped[str] = mapped_column(String(40))
    current_question_id: Mapped[Optional[str]] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )


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
    average_mastery: Mapped[float] = mapped_column(PRECISE_FLOAT, default=0.0)
    blueprint_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class LearningRound(Base):
    __tablename__ = "learning_rounds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    question_id: Mapped[Optional[str]] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(40))
    initial_verdict: Mapped[Optional[str]] = mapped_column(String(40))
    final_verdict: Mapped[Optional[str]] = mapped_column(String(40))
    discussion_summary_json: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )
    finalized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")
    )


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    bank_question_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("bank_question_revisions.id", name="fk_question_bank_revision")
    )
    question_type: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[int] = mapped_column(Integer)
    student_content_json: Mapped[dict] = mapped_column(JSON)
    critic_content_json: Mapped[dict] = mapped_column(JSON)
    knowledge_node_ids: Mapped[list] = mapped_column(JSON)
    target_error_ids: Mapped[list] = mapped_column(JSON)
    pedagogical_strategy: Mapped[str] = mapped_column(LONG_TEXT)
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class QuestionReviewRecord(Base):
    __tablename__ = "question_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    status: Mapped[str] = mapped_column(String(30))
    quality_score: Mapped[float] = mapped_column(PRECISE_FLOAT)
    issues_json: Mapped[list] = mapped_column(JSON)
    grading_notes: Mapped[Optional[str]] = mapped_column(LONG_TEXT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    role: Mapped[str] = mapped_column(String(20))
    content_markdown: Mapped[str] = mapped_column(LONG_TEXT)
    critic_intent: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class CriticTurnResultRecord(Base):
    __tablename__ = "critic_turn_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    message_id: Mapped[str] = mapped_column(ForeignKey("conversation_messages.id"))
    intent: Mapped[str] = mapped_column(String(40))
    verdict: Mapped[str] = mapped_column(String(40))
    round_action: Mapped[str] = mapped_column(String(40))
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class GraphUpdateEvent(Base):
    __tablename__ = "graph_update_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    graph_type: Mapped[str] = mapped_column(String(20))
    node_id: Mapped[str] = mapped_column(String(120))
    before_value: Mapped[float] = mapped_column(PRECISE_FLOAT)
    after_value: Mapped[float] = mapped_column(PRECISE_FLOAT)
    reason: Mapped[str] = mapped_column(LONG_TEXT)
    assessment_evidence_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("assessment_evidence.id", name="fk_graph_event_evidence")
    )
    before_evaluated_count: Mapped[Optional[int]] = mapped_column(Integer)
    after_evaluated_count: Mapped[Optional[int]] = mapped_column(Integer)
    before_correct_count: Mapped[Optional[int]] = mapped_column(Integer)
    after_correct_count: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_source_document_sha256"),
        CheckConstraint("page_count > 0", name="ck_source_document_pages"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    title: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(30))
    exam_year: Mapped[Optional[int]] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    sha256: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class BankQuestion(Base):
    __tablename__ = "bank_questions"
    __table_args__ = (
        UniqueConstraint("source_document_id", "question_number", name="uq_bank_source_number"),
    )
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    question_number: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class BankQuestionRevision(Base):
    __tablename__ = "bank_question_revisions"
    __table_args__ = (
        UniqueConstraint("bank_question_id", "revision", name="uq_bank_question_revision"),
        CheckConstraint("revision > 0", name="ck_bank_revision_positive"),
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_bank_difficulty"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    bank_question_id: Mapped[str] = mapped_column(ForeignKey("bank_questions.id"))
    revision: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[int] = mapped_column(Integer)
    difficulty_origin: Mapped[str] = mapped_column(String(40), default="project_annotation")
    difficulty_reason: Mapped[str] = mapped_column(LONG_TEXT, default="")
    cognitive_goal: Mapped[str] = mapped_column(String(80), default="recognize")
    original_content_json: Mapped[dict] = mapped_column(JSON)
    student_content_json: Mapped[dict] = mapped_column(JSON)
    critic_content_json: Mapped[dict] = mapped_column(JSON)
    source_locations_json: Mapped[dict] = mapped_column(JSON)
    answer_provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    normalizations_json: Mapped[list] = mapped_column(JSON, default=list)
    target_error_ids: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(30), default="draft")
    topic_tags: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )


class QuestionKnowledgeMapping(Base):
    __tablename__ = "question_knowledge_mappings"
    __table_args__ = (
        UniqueConstraint("bank_question_revision_id", "knowledge_node_id", name="uq_question_node"),
        CheckConstraint("role IN ('assessed', 'prerequisite')", name="ck_question_node_role"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    bank_question_revision_id: Mapped[str] = mapped_column(ForeignKey("bank_question_revisions.id"))
    knowledge_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    role: Mapped[str] = mapped_column(String(20), default="assessed")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_criterion: Mapped[str] = mapped_column(LONG_TEXT, default="")


class AssessmentEvidence(Base):
    __tablename__ = "assessment_evidence"
    __table_args__ = (
        UniqueConstraint("round_id", "knowledge_node_id", name="uq_evidence_round_node"),
        UniqueConstraint("counted_question_key", name="uq_evidence_counted_question"),
        CheckConstraint(
            "outcome IN ('correct', 'incorrect', 'partial', 'unassessable')",
            name="ck_evidence_outcome",
        ),
        CheckConstraint(
            "assistance IN ('none', 'hint', 'answer_visible')", name="ck_evidence_help"
        ),
        CheckConstraint(
            "(counted = true AND counted_question_key IS NOT NULL) OR "
            "(counted = false AND counted_question_key IS NULL)",
            name="ck_evidence_count_key",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("learning_rounds.id"))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    bank_question_id: Mapped[Optional[str]] = mapped_column(ForeignKey("bank_questions.id"))
    bank_question_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("bank_question_revisions.id")
    )
    knowledge_node_id: Mapped[str] = mapped_column(ForeignKey("knowledge_nodes.id"))
    basis_message_id: Mapped[Optional[str]] = mapped_column(ForeignKey("conversation_messages.id"))
    outcome: Mapped[str] = mapped_column(String(20))
    assistance: Mapped[str] = mapped_column(String(20), default="none")
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)
    counted_question_key: Mapped[Optional[str]] = mapped_column(String(64))
    exclusion_reason: Mapped[Optional[str]] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(LONG_TEXT)
    score_policy_version: Mapped[str] = mapped_column(String(64), default="correct_over_max_20_v1")
    finalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql"), default=datetime.utcnow
    )
