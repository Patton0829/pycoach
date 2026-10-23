"""Validated import and retrieval contracts for the internal question bank."""

from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.question import QuestionCriticContent, StudentQuestionContent

BankQuestionType = Literal[
    "multiple_choice", "code_blank", "output_prediction", "short_explanation", "programming"
]


class CatalogChapterInput(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    course_id: str = "python"
    title: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    reference_url: str | None = Field(default=None, max_length=500)


class CatalogKnowledgeNodeInput(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    chapter_id: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    learning_objective: str = Field(min_length=1)
    reference_url: str | None = Field(default=None, max_length=500)
    reference_section: str | None = Field(default=None, max_length=40)
    is_supplementary: bool = False
    runtime_enabled: Literal[False] = False


class SourceDocumentInput(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=255)
    document_type: Literal["sample_exam", "past_exam"]
    exam_year: int | None = Field(default=None, ge=1900, le=9999)
    file_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)


class OriginalOption(StrictModel):
    label: str = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1)


class OriginalQuestionContent(StrictModel):
    stem: str = Field(min_length=1)
    code: str | None = None
    options: list[OriginalOption] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_options(self) -> "OriginalQuestionContent":
        labels = [option.label for option in self.options]
        if len(labels) != len(set(labels)):
            raise ValueError("option labels must be unique")
        return self


class SourceLocations(StrictModel):
    question_pdf_pages: list[int] = Field(min_length=1)
    stem_pdf_pages: list[int] = Field(default_factory=list)
    options_pdf_pages: list[int] = Field(default_factory=list)
    answer_pdf_pages: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def positive_unique_pages(self) -> "SourceLocations":
        for pages in (
            self.question_pdf_pages,
            self.stem_pdf_pages,
            self.options_pdf_pages,
            self.answer_pdf_pages,
        ):
            if any(page < 1 for page in pages) or len(pages) != len(set(pages)):
                raise ValueError("PDF page numbers must be positive and unique")
        if not set(self.stem_pdf_pages + self.options_pdf_pages).issubset(self.question_pdf_pages):
            raise ValueError("stem and option pages must belong to question_pdf_pages")
        return self


class AnswerProvenance(StrictModel):
    origin: Literal["provided_pdf_reference_answers", "project_annotation", "unknown"]
    correct_option: str | None = Field(default=None, min_length=1, max_length=8)
    source_text: str | None = None
    explanation_origin: Literal[
        "provided_pdf_reference_answers", "project_annotation", "unknown"
    ] = "project_annotation"
    source_correct_option: str | None = Field(default=None, min_length=1, max_length=8)
    review_note: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    verification_sources: list[str] = Field(default_factory=list)


class ContentNormalization(StrictModel):
    field: str = Field(min_length=1)
    before: str
    after: str
    reason: str = Field(min_length=1)


class QuestionKnowledgeTarget(StrictModel):
    knowledge_node_id: str = Field(min_length=1, max_length=120)
    role: Literal["assessed", "prerequisite"] = "assessed"
    is_primary: bool = False
    assessment_criterion: str = ""

    @model_validator(mode="after")
    def validate_assessed_target(self) -> "QuestionKnowledgeTarget":
        if self.role == "assessed" and not self.assessment_criterion.strip():
            raise ValueError("assessed targets need a per-node assessment criterion")
        if self.role == "prerequisite" and self.is_primary:
            raise ValueError("prerequisites cannot be primary assessment targets")
        return self


class BankQuestionRevisionInput(StrictModel):
    bank_question_id: str = Field(min_length=1, max_length=120)
    question_number: str = Field(min_length=1, max_length=40)
    revision: int = Field(default=1, ge=1)
    question_type: BankQuestionType
    difficulty: int = Field(ge=1, le=5)
    difficulty_origin: Literal["project_annotation", "source_document", "calibrated"] = (
        "project_annotation"
    )
    difficulty_reason: str = Field(min_length=1)
    cognitive_goal: str = Field(min_length=1)
    original_content: OriginalQuestionContent
    student_content: StudentQuestionContent
    critic_content: QuestionCriticContent
    source_locations: SourceLocations
    answer_provenance: AnswerProvenance
    normalizations: list[ContentNormalization] = Field(default_factory=list)
    topic_tags: list[str] = Field(default_factory=list)
    target_error_ids: list[str] = Field(default_factory=list)
    knowledge_targets: list[QuestionKnowledgeTarget] = Field(default_factory=list)
    review_status: Literal["draft", "approved", "invalid"] = "draft"

    @model_validator(mode="after")
    def validate_knowledge_targets(self) -> "BankQuestionRevisionInput":
        node_ids = [target.knowledge_node_id for target in self.knowledge_targets]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("each knowledge point may have only one mapping per revision")
        assessed = [target for target in self.knowledge_targets if target.role == "assessed"]
        if len(assessed) > 2:
            raise ValueError("a question can assess at most two knowledge points")
        if assessed and sum(target.is_primary for target in assessed) != 1:
            raise ValueError("mapped questions need exactly one primary assessment target")
        if self.review_status == "approved" and not assessed:
            raise ValueError("approved questions need at least one assessed knowledge point")
        if self.question_type == "multiple_choice" and len(self.original_content.options) < 2:
            raise ValueError("multiple choice questions need their original options")
        return self


class QuestionBankImport(StrictModel):
    document: SourceDocumentInput
    questions: list[BankQuestionRevisionInput] = Field(min_length=1)
    catalog_chapters: list[CatalogChapterInput] = Field(default_factory=list)
    catalog_knowledge_nodes: list[CatalogKnowledgeNodeInput] = Field(default_factory=list)


class QuestionBankQuery(StrictModel):
    knowledge_node_ids: list[str] = Field(default_factory=list)
    allowed_knowledge_node_ids: list[str] | None = None
    difficulty_min: int = Field(default=1, ge=1, le=5)
    difficulty_max: int = Field(default=5, ge=1, le=5)
    question_types: list[BankQuestionType] = Field(default_factory=list)
    exclude_bank_question_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_difficulty_range(self) -> "QuestionBankQuery":
        if self.difficulty_min > self.difficulty_max:
            raise ValueError("difficulty_min cannot exceed difficulty_max")
        return self


class BankCandidateSummary(StrictModel):
    revision_id: str
    bank_question_id: str
    revision: int
    question_type: BankQuestionType
    difficulty: int
    knowledge_node_ids: list[str]
    topic_tags: list[str]
    student_content: StudentQuestionContent


def import_from_exam_example(raw: dict[str, Any]) -> QuestionBankImport:
    """Adapt the previously generated, source-preserving PDF example as draft data.

    Natural-language tags are retained, but never turned into invented curriculum
    IDs or automatically approved assessment targets.
    """
    if raw.get("schema_version") != "exam-bank-example.v1":
        return QuestionBankImport.model_validate(raw)
    source = raw["source_document"]
    document = SourceDocumentInput.model_validate(
        {
            "title": source["title"],
            "document_type": source["document_type"],
            "exam_year": source.get("exam_year"),
            "file_path": source["relative_path"],
            "sha256": source["sha256"],
            "page_count": source["page_count"],
        }
    )
    questions = []
    for item in raw["questions"]:
        annotations = item["annotations"]
        provenance = item["answer_provenance"]
        questions.append(
            BankQuestionRevisionInput.model_validate(
                {
                    "bank_question_id": item["question_id"],
                    "question_number": str(item["source"]["question_number"]),
                    "question_type": item["question_type"],
                    "difficulty": annotations["difficulty"],
                    "difficulty_reason": annotations["difficulty_reason"],
                    "cognitive_goal": "recognize_or_trace",
                    "original_content": item["original_content"],
                    "student_content": item["student_content"],
                    "critic_content": item["critic_content"],
                    "source_locations": {
                        "question_pdf_pages": item["source"]["question_pdf_pages"],
                        "stem_pdf_pages": item["source"].get("stem_pdf_pages", []),
                        "options_pdf_pages": item["source"].get("options_pdf_pages", []),
                        "answer_pdf_pages": item["source"]["answer_pdf_pages"],
                    },
                    "answer_provenance": {
                        "origin": provenance["origin"],
                        "correct_option": provenance.get("correct_option"),
                        "source_text": provenance.get("source_text"),
                        "explanation_origin": provenance["explanation_origin"],
                    },
                    "normalizations": item.get("normalizations", []),
                    "topic_tags": annotations.get("topic_tags", []),
                    "knowledge_targets": [],
                    "review_status": "draft",
                }
            )
        )
    return QuestionBankImport(document=document, questions=questions)
