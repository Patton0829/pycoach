from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models.entities import (
    BankQuestionRevision,
    QuestionKnowledgeMapping,
    SourceDocument,
)
from app.schemas.question_bank import QuestionBankQuery


class QuestionBankRepository:
    def __init__(self, database: Session) -> None:
        self.database = database

    def document_by_sha256(self, sha256: str) -> SourceDocument | None:
        return self.database.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha256))

    def revision(self, bank_question_id: str, revision: int) -> BankQuestionRevision | None:
        return self.database.scalar(
            select(BankQuestionRevision).where(
                BankQuestionRevision.bank_question_id == bank_question_id,
                BankQuestionRevision.revision == revision,
            )
        )

    def mappings(self, revision_id: str) -> list[QuestionKnowledgeMapping]:
        return list(
            self.database.scalars(
                select(QuestionKnowledgeMapping)
                .where(QuestionKnowledgeMapping.bank_question_revision_id == revision_id)
                .order_by(
                    QuestionKnowledgeMapping.is_primary.desc(),
                    QuestionKnowledgeMapping.knowledge_node_id,
                )
            ).all()
        )

    def candidates(
        self, query: QuestionBankQuery, allowed_node_ids: set[str]
    ) -> list[BankQuestionRevision]:
        newer = aliased(BankQuestionRevision)
        latest_approved = (
            select(func.max(newer.revision))
            .where(
                newer.bank_question_id == BankQuestionRevision.bank_question_id,
                newer.review_status == "approved",
            )
            .correlate(BankQuestionRevision)
            .scalar_subquery()
        )
        mapping = QuestionKnowledgeMapping
        statement = select(BankQuestionRevision).where(
            BankQuestionRevision.review_status == "approved",
            BankQuestionRevision.revision == latest_approved,
            BankQuestionRevision.difficulty.between(query.difficulty_min, query.difficulty_max),
            exists().where(
                mapping.bank_question_revision_id == BankQuestionRevision.id,
                mapping.role == "assessed",
            ),
            ~exists().where(
                mapping.bank_question_revision_id == BankQuestionRevision.id,
                mapping.role == "assessed",
                mapping.knowledge_node_id.not_in(sorted(allowed_node_ids)),
            ),
        )
        if query.knowledge_node_ids:
            statement = statement.where(
                exists().where(
                    mapping.bank_question_revision_id == BankQuestionRevision.id,
                    mapping.role == "assessed",
                    mapping.knowledge_node_id.in_(query.knowledge_node_ids),
                )
            )
        if query.question_types:
            statement = statement.where(
                BankQuestionRevision.question_type.in_(query.question_types)
            )
        if query.exclude_bank_question_ids:
            statement = statement.where(
                BankQuestionRevision.bank_question_id.not_in(query.exclude_bank_question_ids)
            )
        return list(
            self.database.scalars(
                statement.order_by(
                    BankQuestionRevision.difficulty,
                    BankQuestionRevision.bank_question_id,
                ).limit(query.limit)
            ).all()
        )
