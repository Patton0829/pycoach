import logging
import io
import keyword
import re
import token
import tokenize
from collections import Counter
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.agents.questioner import Questioner
from app.core.config import settings
from app.llm.base import LLMProvider, LLMProviderError
from app.repositories.question_repository import QuestionRepository
from app.schemas.question import (
    CandidateConstraints,
    RecentAttempt,
    RecentQuestion,
    QuestionGenerationResult,
    QuestionPacket,
    QuestionType,
    QuestionerContext,
)

logger = logging.getLogger(__name__)

QUESTION_TYPE_RATIOS: dict[QuestionType, float] = {
    "multiple_choice": 0.40,
    "code_blank": 0.35,
    "output_prediction": 0.15,
    "short_explanation": 0.10,
}

DEFAULT_TEACHING_POLICY = {
    "retrieval_practice": True,
    "generation_effect": True,
    "desirable_difficulty": True,
    "interleaving": True,
    "spacing": True,
    "variation": True,
    "transfer": True,
    "chunking": True,
}


class QuestionConstraintError(ValueError):
    pass


class QuestionContextError(LookupError):
    pass


class QuestionContextBuilder:
    def __init__(self, database: Session) -> None:
        self.repository = QuestionRepository(database)

    def build(
        self,
        learner_id: str,
        recent_questions: Optional[List[RecentQuestion]] = None,
        recent_attempts: Optional[List[RecentAttempt]] = None,
        critic_summary: Optional[Dict[str, Any]] = None,
        teaching_policy: Optional[Dict[str, Any]] = None,
        candidate_constraints: Optional[CandidateConstraints] = None,
    ) -> QuestionerContext:
        if not self.repository.learner_exists(learner_id):
            raise QuestionContextError(f"Learner not found: {learner_id}")

        nodes = self.repository.list_knowledge_nodes()
        edges = self.repository.list_knowledge_edges()
        error_types = self.repository.list_error_types()
        personal_by_node = {
            item.knowledge_node_id: item
            for item in self.repository.list_personal_knowledge(learner_id)
        }
        personal_errors = self.repository.list_personal_errors(learner_id)

        constraints = candidate_constraints or CandidateConstraints()
        if not constraints.allowed_knowledge_node_ids:
            constraints.allowed_knowledge_node_ids = [node.id for node in nodes]
        if not constraints.allowed_error_ids:
            constraints.allowed_error_ids = [error_type.id for error_type in error_types]

        return QuestionerContext(
            global_knowledge_graph={
                "nodes": [
                    {
                        "id": node.id,
                        "name": node.name,
                        "description": node.description,
                        "difficulty": node.difficulty,
                        "learning_objective": node.learning_objective,
                    }
                    for node in nodes
                ],
                "edges": [
                    {
                        "source_node_id": edge.source_node_id,
                        "target_node_id": edge.target_node_id,
                        "relation_type": edge.relation_type,
                        "weight": edge.weight,
                    }
                    for edge in edges
                ],
                "error_types": [
                    {
                        "id": error_type.id,
                        "name": error_type.name,
                        "description": error_type.description,
                        "related_knowledge_nodes": error_type.related_knowledge_nodes,
                        "remediation_strategy": error_type.remediation_strategy,
                    }
                    for error_type in error_types
                ],
            },
            personal_knowledge_graph=[
                {
                    "node_id": node.id,
                    "mastery": (
                        personal_by_node[node.id].mastery
                        if node.id in personal_by_node
                        else 0.0
                    ),
                    "status": (
                        personal_by_node[node.id].status
                        if node.id in personal_by_node
                        else "not_started"
                    ),
                }
                for node in nodes
            ],
            error_graph=[
                {
                    "error_id": item.error_type_id,
                    "severity": item.severity,
                    "status": item.status,
                }
                for item in personal_errors
            ],
            recent_questions=recent_questions or [],
            recent_attempts=recent_attempts or [],
            critic_summary=critic_summary or {},
            teaching_policy=teaching_policy or {},
            candidate_constraints=constraints,
        )


class QuestionService:
    def __init__(
        self,
        provider: LLMProvider,
        curriculum_dir: Optional[Path] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.curriculum_dir = curriculum_dir or Path(settings.curriculum_dir)
        prompt = system_prompt or self._load_system_prompt()
        self.questioner = Questioner(provider, prompt)
        self.seed_questions = self._load_seed_questions()

    async def generate_next_question(
        self,
        context: QuestionerContext,
    ) -> QuestionGenerationResult:
        prepared_context = self.prepare_context(context)
        validation_feedback: Optional[str] = None

        for attempt in range(2):
            try:
                packet = await self.questioner.generate(
                    prepared_context,
                    validation_feedback=validation_feedback,
                )
                self.validate_candidate(packet, prepared_context.candidate_constraints)
                packet = packet.model_copy(
                    update={"question_id": uuid4()},
                    deep=True,
                )
                return QuestionGenerationResult(
                    packet=packet,
                    source="model",
                    retry_count=attempt,
                )
            except (
                ValidationError,
                JSONDecodeError,
                QuestionConstraintError,
                LLMProviderError,
            ) as error:
                validation_feedback = str(error)
                logger.warning(
                    "Questioner output rejected on attempt %s: %s",
                    attempt + 1,
                    error,
                )

        fallback = self.select_seed_fallback(prepared_context.candidate_constraints)
        logger.error(
            "Questioner output failed validation twice; using seed fallback %s",
            fallback.question_id,
        )
        return QuestionGenerationResult(
            packet=fallback,
            source="seed_fallback",
            retry_count=1,
        )

    def prepare_context(self, context: QuestionerContext) -> QuestionerContext:
        constraints = context.candidate_constraints.model_copy(deep=True)
        if constraints.preferred_question_type is None:
            constraints.preferred_question_type = choose_preferred_question_type(
                [question.question_type for question in context.recent_questions],
                constraints.allowed_question_types,
            )

        if not constraints.allowed_knowledge_node_ids:
            constraints.allowed_knowledge_node_ids = [
                item.node_id for item in context.personal_knowledge_graph
            ]
        if not constraints.allowed_error_ids:
            constraints.allowed_error_ids = [
                item.error_id for item in context.error_graph
            ]

        constraints.avoid_question_ids = list(
            dict.fromkeys(
                [
                    *constraints.avoid_question_ids,
                    *(question.question_id for question in context.recent_questions),
                ]
            )
        )
        constraints.avoid_markdown = list(
            dict.fromkeys(
                [
                    *constraints.avoid_markdown,
                    *(question.markdown for question in context.recent_questions),
                ]
            )
        )

        teaching_policy = {
            **DEFAULT_TEACHING_POLICY,
            **context.teaching_policy,
        }
        return context.model_copy(
            update={
                "candidate_constraints": constraints,
                "teaching_policy": teaching_policy,
            },
            deep=True,
        )

    def validate_candidate(
        self,
        packet: QuestionPacket,
        constraints: CandidateConstraints,
    ) -> None:
        if packet.question_type not in constraints.allowed_question_types:
            raise QuestionConstraintError("question_type is not allowed")
        if (
            constraints.preferred_question_type
            and packet.question_type != constraints.preferred_question_type
        ):
            raise QuestionConstraintError(
                "question_type must be "
                f"{constraints.preferred_question_type}, got {packet.question_type}"
            )
        if len(packet.knowledge_node_ids) > constraints.max_knowledge_nodes:
            raise QuestionConstraintError("too many knowledge nodes")
        if constraints.allowed_knowledge_node_ids and not set(
            packet.knowledge_node_ids
        ).issubset(constraints.allowed_knowledge_node_ids):
            raise QuestionConstraintError("question references an unknown knowledge node")
        if constraints.allowed_error_ids and not set(packet.target_error_ids).issubset(
            constraints.allowed_error_ids
        ):
            raise QuestionConstraintError("question references an unknown error type")
        if packet.question_id in constraints.avoid_question_ids:
            raise QuestionConstraintError("question_id was recently used")

        normalized_candidate = normalize_markdown(packet.student_content.markdown)
        recent_markdown = {
            normalize_markdown(markdown) for markdown in constraints.avoid_markdown
        }
        if normalized_candidate in recent_markdown:
            raise QuestionConstraintError("question duplicates recent student content")
        candidate_surface = surface_signature(packet.student_content.markdown)
        recent_surfaces = {
            surface_signature(markdown) for markdown in constraints.avoid_markdown
        }
        if candidate_surface in recent_surfaces:
            raise QuestionConstraintError(
                "question only changes numbers or variable names from recent content"
            )

        code_lines = count_code_lines(packet.student_content.markdown)
        if code_lines > constraints.max_code_lines:
            raise QuestionConstraintError(
                f"question contains {code_lines} code lines; "
                f"maximum is {constraints.max_code_lines}"
            )
        option_count = count_choice_options(packet.student_content.markdown)
        if packet.question_type == "multiple_choice" and option_count < 4:
            raise QuestionConstraintError(
                "multiple_choice questions must include A/B/C/D options"
            )
        if asks_for_listed_choice(packet.student_content.markdown) and option_count < 2:
            raise QuestionConstraintError(
                "question asks for a listed choice but does not include options"
            )

    def select_seed_fallback(
        self,
        constraints: CandidateConstraints,
    ) -> QuestionPacket:
        eligible = [
            question
            for question in self.seed_questions
            if question.question_type in constraints.allowed_question_types
            and (
                not constraints.allowed_knowledge_node_ids
                or set(question.knowledge_node_ids).issubset(
                    constraints.allowed_knowledge_node_ids
                )
            )
            and (
                not constraints.allowed_error_ids
                or set(question.target_error_ids).issubset(
                    constraints.allowed_error_ids
                )
            )
        ]
        if not eligible:
            raise RuntimeError("No seed question satisfies the candidate constraints")

        preferred = [
            question
            for question in eligible
            if question.question_type == constraints.preferred_question_type
        ]
        pool = preferred or eligible
        recent_markdown = {
            normalize_markdown(markdown) for markdown in constraints.avoid_markdown
        }
        non_repeated = [
            question
            for question in pool
            if normalize_markdown(question.student_content.markdown) not in recent_markdown
            and surface_signature(question.student_content.markdown)
            not in {
                surface_signature(markdown)
                for markdown in constraints.avoid_markdown
            }
        ]
        selected = (non_repeated or pool)[0]
        return selected.model_copy(update={"question_id": uuid4()}, deep=True)

    def _load_seed_questions(self) -> List[QuestionPacket]:
        path = self.curriculum_dir / "seed_questions.json"
        return TypeAdapter(List[QuestionPacket]).validate_json(
            path.read_text(encoding="utf-8")
        )

    def _load_system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "agents"
            / "prompts"
            / "questioner_system.md"
        )
        return path.read_text(encoding="utf-8")


def choose_preferred_question_type(
    recent_types: Sequence[QuestionType],
    allowed_types: Sequence[QuestionType],
) -> QuestionType:
    counts = Counter(recent_types)
    candidates = [
        question_type
        for question_type in QUESTION_TYPE_RATIOS
        if question_type in allowed_types
    ]
    if not candidates:
        raise ValueError("allowed_question_types has no supported question type")
    return min(
        candidates,
        key=lambda question_type: (
            counts[question_type] / QUESTION_TYPE_RATIOS[question_type],
            -QUESTION_TYPE_RATIOS[question_type],
        ),
    )


def normalize_markdown(markdown: str) -> str:
    return re.sub(r"\s+", " ", markdown).strip().lower()


def surface_signature(markdown: str) -> str:
    code_blocks = re.findall(
        r"```(?:python)?\s*\n(.*?)```",
        markdown,
        flags=re.DOTALL,
    )
    prose = re.sub(
        r"```(?:python)?\s*\n.*?```",
        "<code>",
        markdown,
        flags=re.DOTALL,
    )
    prose = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", prose.lower())
    code_signatures = [_python_surface_signature(block) for block in code_blocks]
    return normalize_markdown(prose) + "|" + "|".join(code_signatures)


def _python_surface_signature(code: str) -> str:
    preserved_names = {"iter", "next", "print", "list", "range"}
    parts = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        for item in tokens:
            if item.type in {
                token.ENCODING,
                token.ENDMARKER,
                token.INDENT,
                token.DEDENT,
                token.NEWLINE,
                tokenize.NL,
            }:
                continue
            if item.type == token.NAME:
                if keyword.iskeyword(item.string) or item.string in preserved_names:
                    parts.append(item.string)
                else:
                    parts.append("<id>")
            elif item.type == token.NUMBER:
                parts.append("<num>")
            elif item.type == token.STRING:
                parts.append("<str>")
            else:
                parts.append(item.string)
    except (IndentationError, tokenize.TokenError):
        return normalize_markdown(code)
    return " ".join(parts)


def count_code_lines(markdown: str) -> int:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", markdown, flags=re.DOTALL)
    return max(
        (
            len([line for line in block.splitlines() if line.strip()])
            for block in blocks
        ),
        default=0,
    )


def count_choice_options(markdown: str) -> int:
    return len(
        re.findall(
            r"(?m)^\s*[A-Da-d]\s*(?:[.．、:：）)]|\))\s+\S",
            markdown,
        )
    )


def asks_for_listed_choice(markdown: str) -> bool:
    normalized = normalize_markdown(markdown)
    return any(
        phrase in normalized
        for phrase in {
            "下列哪",
            "下面哪",
            "哪项",
            "哪个选项",
            "which option",
            "which of the following",
        }
    )
