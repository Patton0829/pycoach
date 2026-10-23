"""Internal, deterministic import and retrieval of source-preserving exam items.

Methods flush their changes, but the caller owns the transaction. Neither import
nor retrieval executes question code or calls an LLM.
"""

import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    BankQuestion,
    BankQuestionRevision,
    CurriculumChapter,
    ErrorType,
    KnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionKnowledgeMapping,
    SourceDocument,
)
from app.repositories.question_bank_repository import QuestionBankRepository
from app.schemas.question import QuestionPacket, StudentQuestionContent
from app.schemas.question_bank import (
    BankCandidateSummary,
    BankQuestionRevisionInput,
    CatalogChapterInput,
    CatalogKnowledgeNodeInput,
    QuestionBankQuery,
    QuestionKnowledgeTarget,
    SourceDocumentInput,
)

ITERATOR_ASSESSMENT_NODE_IDS = frozenset(
    {
        "python.iterable",
        "python.iterator",
        "python.iterator.iter",
        "python.iterator.next",
        "python.iterator.state",
        "python.iterator.exhaustion",
        "python.stop_iteration",
    }
)


class QuestionBankError(ValueError):
    pass


class ImmutableQuestionRevisionError(QuestionBankError):
    pass


class QuestionBankService:
    def __init__(self, database: Session) -> None:
        self.database = database
        self.repository = QuestionBankRepository(database)

    def register_catalog(
        self, chapters: list[CatalogChapterInput], nodes: list[CatalogKnowledgeNodeInput]
    ) -> None:
        """Add reviewed taxonomy references; importing a bank never activates a lesson."""
        for item in chapters:
            item = CatalogChapterInput.model_validate(item.model_dump())
            existing = self.database.get(CurriculumChapter, item.id)
            if existing is None:
                self.database.add(CurriculumChapter(**item.model_dump()))
            elif any(getattr(existing, field) != value for field, value in item.model_dump().items()):
                raise QuestionBankError(f"catalog chapter conflicts with existing definition: {item.id}")
        self.database.flush()
        for item in nodes:
            item = CatalogKnowledgeNodeInput.model_validate(item.model_dump())
            if self.database.get(CurriculumChapter, item.chapter_id) is None:
                raise QuestionBankError(f"unknown catalog chapter: {item.chapter_id}")
            existing = self.database.get(KnowledgeNode, item.id)
            if existing is None:
                self.database.add(KnowledgeNode(**item.model_dump()))
            elif any(getattr(existing, field) != value for field, value in item.model_dump().items()):
                raise QuestionBankError(f"catalog node conflicts with existing definition: {item.id}")
        self.database.flush()

    def register_document(self, payload: SourceDocumentInput) -> SourceDocument:
        payload = SourceDocumentInput.model_validate(payload.model_dump())
        existing = self.repository.document_by_sha256(payload.sha256)
        if existing is not None:
            return existing
        if self.database.get(SourceDocument, payload.id) is not None:
            raise QuestionBankError("document ID already refers to another source file")
        document = SourceDocument(**payload.model_dump())
        self.database.add(document)
        self.database.flush()
        return document

    def create_revision(
        self, source_document_id: str, payload: BankQuestionRevisionInput
    ) -> BankQuestionRevision:
        payload = BankQuestionRevisionInput.model_validate(payload.model_dump())
        document = self.database.get(SourceDocument, source_document_id)
        if document is None:
            raise QuestionBankError("source document does not exist")
        self._validate_references(document, payload)
        identity = self.database.get(BankQuestion, payload.bank_question_id)
        if identity is not None and (
            identity.source_document_id != source_document_id
            or identity.question_number != payload.question_number
        ):
            raise QuestionBankError("stable question ID already refers to another source item")
        other_identity = self.database.scalar(
            select(BankQuestion).where(
                BankQuestion.source_document_id == source_document_id,
                BankQuestion.question_number == payload.question_number,
            )
        )
        if other_identity is not None and other_identity.id != payload.bank_question_id:
            raise QuestionBankError("source question already has a stable bank question ID")
        content_hash = self._content_hash(payload)
        existing = self.repository.revision(payload.bank_question_id, payload.revision)
        if existing is not None:
            if existing.content_hash != content_hash:
                raise ImmutableQuestionRevisionError(
                    "question revision is immutable; import a new revision number"
                )
            if existing.review_status != payload.review_status:
                raise ImmutableQuestionRevisionError(
                    "use review_revision() to change a revision's review status"
                )
            return existing
        if identity is None:
            identity = BankQuestion(
                id=payload.bank_question_id,
                source_document_id=source_document_id,
                question_number=payload.question_number,
            )
            self.database.add(identity)
            self.database.flush()
        revision = BankQuestionRevision(
            bank_question_id=identity.id,
            revision=payload.revision,
            question_type=payload.question_type,
            difficulty=payload.difficulty,
            difficulty_origin=payload.difficulty_origin,
            difficulty_reason=payload.difficulty_reason,
            cognitive_goal=payload.cognitive_goal,
            original_content_json=payload.original_content.model_dump(mode="json"),
            student_content_json=payload.student_content.model_dump(mode="json"),
            critic_content_json=payload.critic_content.model_dump(mode="json"),
            source_locations_json=payload.source_locations.model_dump(mode="json"),
            answer_provenance_json=payload.answer_provenance.model_dump(mode="json"),
            normalizations_json=[item.model_dump(mode="json") for item in payload.normalizations],
            target_error_ids=payload.target_error_ids,
            topic_tags=payload.topic_tags,
            review_status=payload.review_status,
            content_hash=content_hash,
        )
        self.database.add(revision)
        self.database.flush()
        for target in payload.knowledge_targets:
            self.database.add(
                QuestionKnowledgeMapping(
                    bank_question_revision_id=revision.id,
                    **target.model_dump(),
                )
            )
        self.database.flush()
        return revision

    def review_revision(self, revision_id: str, status: str) -> BankQuestionRevision:
        revision = self._get_revision(revision_id)
        definition = self._definition(revision)
        definition = BankQuestionRevisionInput.model_validate(
            {**definition.model_dump(), "review_status": status}
        )
        identity = self.database.get(BankQuestion, revision.bank_question_id)
        document = self.database.get(SourceDocument, identity.source_document_id)
        self._validate_references(document, definition)
        revision.review_status = definition.review_status
        self.database.flush()
        return revision

    def find_candidates(self, query: QuestionBankQuery) -> list[BankCandidateSummary]:
        query = QuestionBankQuery.model_validate(query.model_dump())
        allowed = set(self.database.scalars(
            select(KnowledgeNode.id).where(
                KnowledgeNode.id.in_(ITERATOR_ASSESSMENT_NODE_IDS),
                KnowledgeNode.runtime_enabled.is_(True),
            )
        ).all())
        if query.allowed_knowledge_node_ids is not None:
            allowed.intersection_update(query.allowed_knowledge_node_ids)
        if not allowed:
            return []
        revisions = self.repository.candidates(query, allowed)
        return [
            BankCandidateSummary(
                revision_id=revision.id,
                bank_question_id=revision.bank_question_id,
                revision=revision.revision,
                question_type=revision.question_type,
                difficulty=revision.difficulty,
                knowledge_node_ids=[
                    mapping.knowledge_node_id
                    for mapping in self.repository.mappings(revision.id)
                    if mapping.role == "assessed"
                ],
                topic_tags=revision.topic_tags,
                student_content=StudentQuestionContent.model_validate(
                    revision.student_content_json
                ),
            )
            for revision in revisions
        ]

    def materialize(self, revision_id: str) -> QuestionPacket:
        """Return an internal runtime packet; its ID is not the stable source ID."""
        revision = self._get_revision(revision_id)
        if revision.review_status != "approved":
            raise QuestionBankError("only approved revisions may be shown for assessment")
        definition = self._definition(revision)
        assessed_ids = {
            target.knowledge_node_id for target in definition.knowledge_targets
            if target.role == "assessed"
        }
        runtime_ids = set(self.database.scalars(
            select(KnowledgeNode.id).where(
                KnowledgeNode.id.in_(ITERATOR_ASSESSMENT_NODE_IDS),
                KnowledgeNode.runtime_enabled.is_(True),
            )
        ).all())
        if not assessed_ids.issubset(runtime_ids):
            raise QuestionBankError("reviewed item is outside the active iterator curriculum")
        identity = self.database.get(BankQuestion, revision.bank_question_id)
        document = self.database.get(SourceDocument, identity.source_document_id)
        self._validate_references(document, definition)
        return QuestionPacket.model_validate(
            {
                "question_id": uuid4(),
                "question_type": revision.question_type,
                "difficulty": revision.difficulty,
                "knowledge_node_ids": [
                    target.knowledge_node_id
                    for target in definition.knowledge_targets
                    if target.role == "assessed"
                ],
                "target_error_ids": revision.target_error_ids,
                "pedagogical_strategy": "authentic_exam_practice",
                "student_content": revision.student_content_json,
                "critic_content": revision.critic_content_json,
            }
        )

    def attach_to_round(self, revision_id: str, session_id: str, round_id: str) -> Question:
        session = self.database.get(LearningSession, session_id)
        learning_round = self.database.get(LearningRound, round_id)
        if session is None or learning_round is None or learning_round.session_id != session_id:
            raise QuestionBankError("round must belong to the supplied learning session")
        if learning_round.question_id is not None:
            existing = self.database.get(Question, learning_round.question_id)
            if existing is not None and existing.bank_question_revision_id == revision_id:
                return existing
            raise QuestionBankError("round already contains another question")
        packet = self.materialize(revision_id)
        question = Question(
            id=str(packet.question_id),
            session_id=session_id,
            round_id=round_id,
            bank_question_revision_id=revision_id,
            question_type=packet.question_type,
            difficulty=packet.difficulty,
            student_content_json=packet.student_content.model_dump(mode="json"),
            critic_content_json=packet.critic_content.model_dump(mode="json"),
            knowledge_node_ids=packet.knowledge_node_ids,
            target_error_ids=packet.target_error_ids,
            pedagogical_strategy=packet.pedagogical_strategy,
            status="active",
        )
        self.database.add(question)
        self.database.flush()
        learning_round.question_id = question.id
        self.database.flush()
        return question

    def _get_revision(self, revision_id: str) -> BankQuestionRevision:
        revision = self.database.get(BankQuestionRevision, revision_id)
        if revision is None:
            raise QuestionBankError("question revision does not exist")
        return revision

    def _definition(self, revision: BankQuestionRevision) -> BankQuestionRevisionInput:
        identity = self.database.get(BankQuestion, revision.bank_question_id)
        if identity is None:
            raise QuestionBankError("question identity is missing")
        return BankQuestionRevisionInput.model_validate(
            {
                "bank_question_id": revision.bank_question_id,
                "question_number": identity.question_number,
                "revision": revision.revision,
                "question_type": revision.question_type,
                "difficulty": revision.difficulty,
                "difficulty_origin": revision.difficulty_origin,
                "difficulty_reason": revision.difficulty_reason,
                "cognitive_goal": revision.cognitive_goal,
                "original_content": revision.original_content_json,
                "student_content": revision.student_content_json,
                "critic_content": revision.critic_content_json,
                "source_locations": revision.source_locations_json,
                "answer_provenance": revision.answer_provenance_json,
                "normalizations": revision.normalizations_json,
                "topic_tags": revision.topic_tags,
                "target_error_ids": revision.target_error_ids,
                "knowledge_targets": [
                    QuestionKnowledgeTarget(
                        knowledge_node_id=mapping.knowledge_node_id,
                        role=mapping.role,
                        is_primary=mapping.is_primary,
                        assessment_criterion=mapping.assessment_criterion,
                    )
                    for mapping in self.repository.mappings(revision.id)
                ],
                "review_status": revision.review_status,
            }
        )

    def _validate_references(
        self, document: SourceDocument, payload: BankQuestionRevisionInput
    ) -> None:
        pages = (
            payload.source_locations.question_pdf_pages + payload.source_locations.answer_pdf_pages
        )
        if any(page > document.page_count for page in pages):
            raise QuestionBankError("question or answer page is outside the source PDF")
        for target in payload.knowledge_targets:
            if self.database.get(KnowledgeNode, target.knowledge_node_id) is None:
                raise QuestionBankError(f"unknown knowledge point: {target.knowledge_node_id}")
        for error_id in payload.target_error_ids:
            if self.database.get(ErrorType, error_id) is None:
                raise QuestionBankError(f"unknown error type: {error_id}")
        if payload.review_status == "approved" and payload.question_type == "multiple_choice":
            labels = set(
                re.findall(r"(?m)^\s*([A-Z])\s*[.．、:：）)]", payload.student_content.markdown)
            )
            if not {"A", "B", "C", "D"}.issubset(labels):
                raise QuestionBankError("approved multiple choice question must display A/B/C/D")

    @staticmethod
    def _content_hash(payload: BankQuestionRevisionInput) -> str:
        serialized = json.dumps(
            payload.model_dump(mode="json", exclude={"review_status"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
