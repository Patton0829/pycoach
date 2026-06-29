import asyncio
import logging
from json import JSONDecodeError
from pathlib import Path
from typing import Awaitable, Callable, Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.critic import Critic
from app.llm.base import LLMProvider, LLMProviderError
from app.repositories.question_review_repository import QuestionReviewRepository
from app.schemas.critic import (
    CriticTurnContext,
    CriticTurnExecution,
    CriticTurnResult,
    DiscussionSummary,
    DiscussionSummaryContext,
    DiscussionSummaryExecution,
    QuestionReview,
    QuestionReviewContext,
    QuestionReviewDecision,
    QuestionReviewExecution,
)

logger = logging.getLogger(__name__)

SAFE_CRITIC_FAILURE_REPLY = (
    "我暂时无法可靠判断这次回答，我们不更新你的学习记录。请重新发送一次。"
)


class QuestionNotFoundError(LookupError):
    pass


class CriticQuestionReviewService:
    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.critic = Critic(provider)
        self.system_prompt = system_prompt or self._load_system_prompt()

    def start_review(
        self,
        context: QuestionReviewContext,
    ) -> asyncio.Task[QuestionReviewExecution]:
        """Start review without blocking question delivery to the student."""
        return asyncio.create_task(self.review_question(context))

    async def review_question(
        self,
        context: QuestionReviewContext,
    ) -> QuestionReviewExecution:
        validation_feedback: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(2):
            try:
                review = await self.critic.run(
                    self.system_prompt,
                    context.model_dump_json(indent=2),
                    QuestionReview,
                    validation_feedback=validation_feedback,
                )
                return QuestionReviewExecution(
                    status="completed",
                    review=review,
                    retry_count=attempt,
                )
            except (ValidationError, JSONDecodeError, LLMProviderError) as error:
                last_error = str(error)
                validation_feedback = last_error
                logger.warning(
                    "Critic question review rejected on attempt %s: %s",
                    attempt + 1,
                    error,
                )

        logger.error("Critic question review failed validation twice")
        return QuestionReviewExecution(
            status="failed",
            retry_count=1,
            error=last_error or "Unknown review validation error",
        )

    async def review_and_persist(
        self,
        context: QuestionReviewContext,
        database: Session,
        update_question_status: bool = True,
    ) -> QuestionReviewExecution:
        execution = await self.review_question(context)
        if execution.status == "failed":
            return execution

        repository = QuestionReviewRepository(database)
        question = repository.get_question(str(context.question_packet.question_id))
        if question is None:
            raise QuestionNotFoundError(str(context.question_packet.question_id))
        repository.save(
            question,
            execution.review,
            update_question_status=update_question_status,
        )
        database.commit()
        return execution

    def decide_handling(
        self,
        execution: QuestionReviewExecution,
        question_id,
        student_has_answered: bool,
    ) -> QuestionReviewDecision:
        if execution.status == "failed":
            return QuestionReviewDecision(
                question_id=question_id,
                review_status="review_failed",
                question_status="review_failed",
                action="pause_for_review_retry",
                allow_graph_updates=False,
                should_generate_replacement=False,
                student_visible_reply_markdown=(
                    "这道题正在重新检查，请稍等一下。"
                ),
            )

        review = execution.review
        if review.status == "approved":
            return QuestionReviewDecision(
                question_id=question_id,
                review_status="approved",
                question_status="active",
                action="continue_question",
                allow_graph_updates=True,
                should_generate_replacement=False,
            )
        if review.status == "needs_revision":
            return QuestionReviewDecision(
                question_id=question_id,
                review_status="needs_revision",
                question_status="active_with_review_notes",
                action="continue_with_review_notes",
                allow_graph_updates=True,
                should_generate_replacement=False,
            )

        return QuestionReviewDecision(
            question_id=question_id,
            review_status="invalid",
            question_status="invalid",
            action=(
                "explain_invalid_and_replace"
                if student_has_answered
                else "replace_question"
            ),
            allow_graph_updates=False,
            should_generate_replacement=True,
            student_visible_reply_markdown=(
                "这道题存在问题，不会影响你的学习记录。我会为你换一道题。"
                if student_has_answered
                else None
            ),
        )

    def _load_system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "agents"
            / "prompts"
            / "critic_question_review.md"
        )
        return path.read_text(encoding="utf-8")


class CriticConversationService:
    def __init__(
        self,
        provider: LLMProvider,
        turn_prompt: Optional[str] = None,
        summary_prompt: Optional[str] = None,
    ) -> None:
        self.critic = Critic(provider)
        self.turn_prompt = turn_prompt or self._load_prompt("critic_turn.md")
        self.summary_prompt = summary_prompt or self._load_prompt(
            "critic_discussion_summary.md"
        )

    async def process_turn(
        self,
        context: CriticTurnContext,
        on_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        on_reset: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> CriticTurnExecution:
        validation_feedback: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(2):
            try:
                result = await self.critic.run(
                    self.turn_prompt,
                    context.model_dump_json(indent=2),
                    CriticTurnResult,
                    validation_feedback=validation_feedback,
                    on_delta=on_delta,
                )
                self._validate_turn_for_state(context, result)
                return CriticTurnExecution(
                    status="completed",
                    result=result,
                    retry_count=attempt,
                )
            except (
                ValidationError,
                JSONDecodeError,
                ValueError,
                LLMProviderError,
            ) as error:
                if on_delta is not None and on_reset is not None:
                    await on_reset()
                last_error = str(error)
                validation_feedback = last_error
                logger.warning(
                    "Critic turn rejected on attempt %s: %s",
                    attempt + 1,
                    error,
                )

        logger.error("Critic turn failed validation twice")
        return CriticTurnExecution(
            status="failed",
            result=self._safe_failure_result(),
            retry_count=1,
            error=last_error or "Unknown Critic turn validation error",
        )

    async def summarize_discussion(
        self,
        context: DiscussionSummaryContext,
    ) -> DiscussionSummaryExecution:
        validation_feedback: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(2):
            try:
                summary = await self.critic.run(
                    self.summary_prompt,
                    context.model_dump_json(indent=2),
                    DiscussionSummary,
                    validation_feedback=validation_feedback,
                )
                if summary.question_id != context.question_packet.question_id:
                    raise ValueError("summary question_id does not match current question")
                return DiscussionSummaryExecution(
                    status="completed",
                    summary=summary,
                    retry_count=attempt,
                )
            except (
                ValidationError,
                JSONDecodeError,
                ValueError,
                LLMProviderError,
            ) as error:
                last_error = str(error)
                validation_feedback = last_error
                logger.warning(
                    "Critic discussion summary rejected on attempt %s: %s",
                    attempt + 1,
                    error,
                )

        logger.error("Critic discussion summary failed validation twice")
        return DiscussionSummaryExecution(
            status="failed",
            retry_count=1,
            error=last_error or "Unknown discussion summary validation error",
        )

    def _validate_turn_for_state(
        self,
        context: CriticTurnContext,
        result: CriticTurnResult,
    ) -> None:
        if context.question_review.status == "invalid":
            if result.verdict != "invalid_question":
                raise ValueError("invalid reviewed question requires invalid_question verdict")
            if result.round_action != "replace_question":
                raise ValueError("invalid reviewed question must be replaced")

        if result.intent in {"answer_attempt", "answer_and_question"}:
            if context.session_state == "QUESTION_ACTIVE":
                if result.round_action != "show_feedback":
                    raise ValueError(
                        "answer evaluation in QUESTION_ACTIVE must show feedback"
                    )
        if (
            result.intent == "clarification_question"
            and context.session_state == "QUESTION_ACTIVE"
            and result.round_action != "wait_for_answer"
        ):
            raise ValueError(
                "pre-answer clarification must keep the question active"
            )
        if result.intent == "request_example" and result.round_action not in {
            "wait_for_answer",
            "continue_discussion",
        }:
            raise ValueError("request_example must remain in the current round")
        if result.intent == "challenge_evaluation" and result.round_action not in {
            "continue_discussion",
            "show_feedback",
            "replace_question",
        }:
            raise ValueError("challenge_evaluation must recheck the current round")

    def _safe_failure_result(self) -> CriticTurnResult:
        return CriticTurnResult(
            intent="ambiguous",
            intent_confidence=0.0,
            student_visible_reply_markdown=SAFE_CRITIC_FAILURE_REPLY,
            verdict="critic_uncertain",
            round_action="continue_discussion",
            provisional_knowledge_updates=[],
            provisional_error_updates=[],
            should_prepare_next_question=False,
            should_invalidate_candidate_question=False,
        )

    def _load_prompt(self, filename: str) -> str:
        path = (
            Path(__file__).resolve().parents[1]
            / "agents"
            / "prompts"
            / filename
        )
        return path.read_text(encoding="utf-8")
