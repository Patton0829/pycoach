"""Project public labels without exposing answers, rubrics or file paths."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import BankQuestion, BankQuestionRevision, KnowledgeNode, Question, SourceDocument
from app.schemas.public_question import PublicKnowledgePoint, PublicQuestionMetadata, PublicQuestionSource


def question_metadata_batch(
    database: Session, questions: Sequence[Question]
) -> dict[str, PublicQuestionMetadata]:
    node_ids = {node_id for question in questions for node_id in question.knowledge_node_ids}
    names = dict(database.execute(
        select(KnowledgeNode.id, KnowledgeNode.name).where(KnowledgeNode.id.in_(node_ids))
    ).all()) if node_ids else {}
    revision_ids = {
        question.bank_question_revision_id for question in questions
        if question.bank_question_revision_id is not None
    }
    sources = {}
    if revision_ids:
        rows = database.execute(
            select(
                BankQuestionRevision.id, BankQuestionRevision.source_locations_json,
                BankQuestion.question_number, SourceDocument.title,
                SourceDocument.document_type, SourceDocument.exam_year,
            )
            .join(BankQuestion, BankQuestion.id == BankQuestionRevision.bank_question_id)
            .join(SourceDocument, SourceDocument.id == BankQuestion.source_document_id)
            .where(BankQuestionRevision.id.in_(revision_ids))
        ).all()
        sources = {
            row.id: PublicQuestionSource(
                title=row.title, document_type=row.document_type,
                exam_year=row.exam_year, question_number=row.question_number,
                pdf_pages=row.source_locations_json.get("question_pdf_pages", []),
            )
            for row in rows
        }
    return {
        question.id: PublicQuestionMetadata(
            difficulty=question.difficulty,
            knowledge_points=[
                PublicKnowledgePoint(id=node_id, name=names.get(node_id, node_id))
                for node_id in question.knowledge_node_ids
            ],
            source=sources.get(question.bank_question_revision_id),
        )
        for question in questions
    }


def question_metadata(database: Session, question: Question) -> PublicQuestionMetadata:
    return question_metadata_batch(database, [question])[question.id]
