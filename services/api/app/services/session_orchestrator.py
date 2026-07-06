from datetime import datetime
import logging
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.llm.base import LLMProvider
from app.models.entities import LearningRound, LearningSession, Question
from app.repositories.session_repository import SessionRepository
from app.schemas.critic import (
    CriticTurnContext,
    CriticTurnResult,
    DiscussionSummary,
    DiscussionSummaryContext,
    QuestionReview,
    QuestionReviewContext,
)
from app.schemas.message import (
    CandidateQuestionStatusEvent,
    CriticReplyReadyEvent,
    CriticReplyReadyPayload,
    MessageStreamDeltaEvent,
    MessageStreamDeltaPayload,
    MessageStreamResetEvent,
    MessageStreamResetPayload,
    MessageStreamStartedEvent,
    MessageStreamStartedPayload,
    MessageAcceptedResponse,
    QuestionInvalidEvent,
    QuestionInvalidPayload,
    QuestionReadyEvent,
    QuestionReadyPayload,
    SessionSummaryReadyEvent,
    SessionSummaryReadyPayload,
)
from app.schemas.question import RecentQuestion
from app.schemas.session import CreateSessionRequest, SessionResponse, SessionState
from app.services.candidate_question_service import CandidateQuestionService
from app.services.chapter_questioning_service import ChapterQuestioningService
from app.services.conversation_service import (
    create_message,
    create_turn_result_record,
    to_critic_context_message,
    to_student_visible_message,
)
from app.services.critic_service import (
    CriticConversationService,
    CriticQuestionReviewService,
)
from app.services.graph_service import GraphService
from app.services.question_service import QuestionContextBuilder, QuestionService
from app.services.websocket_manager import SessionWebSocketManager

logger = logging.getLogger(__name__)

NEXT_QUESTION_COMMANDS = {
    "下一题",
    "下一个",
    "继续",
    "next",
    "next question",
}
STALE_NEXT_QUESTION_SECONDS = 6
NEXT_QUESTION_WAIT_TIMEOUT_SECONDS = 30
NEXT_QUESTION_WAIT_INTERVAL_SECONDS = 0.5

ALLOWED_TRANSITIONS = {
    SessionState.SESSION_CREATED: {SessionState.QUESTION_GENERATING},
    SessionState.QUESTION_GENERATING: {
        SessionState.QUESTION_ACTIVE,
        SessionState.QUESTION_GENERATION_FAILED,
    },
    SessionState.QUESTION_ACTIVE: {
        SessionState.USER_MESSAGE_RECEIVED,
        SessionState.QUESTION_INVALID,
        SessionState.SESSION_ENDED,
    },
    SessionState.USER_MESSAGE_RECEIVED: {SessionState.CRITIC_PROCESSING},
    SessionState.CRITIC_PROCESSING: {
        SessionState.QUESTION_ACTIVE,
        SessionState.FEEDBACK_DISCUSSION,
        SessionState.ROUND_FINALIZING,
        SessionState.QUESTION_INVALID,
        SessionState.CRITIC_OUTPUT_INVALID,
        SessionState.SESSION_ENDED,
    },
    SessionState.FEEDBACK_DISCUSSION: {
        SessionState.USER_MESSAGE_RECEIVED,
        SessionState.ROUND_FINALIZING,
        SessionState.QUESTION_INVALID,
        SessionState.SESSION_ENDED,
    },
    SessionState.ROUND_FINALIZING: {
        SessionState.NEXT_QUESTION_READY,
        SessionState.QUESTION_GENERATION_FAILED,
        SessionState.FEEDBACK_DISCUSSION,
    },
    SessionState.NEXT_QUESTION_READY: {SessionState.QUESTION_ACTIVE},
    SessionState.QUESTION_INVALID: {
        SessionState.QUESTION_GENERATING,
        SessionState.QUESTION_ACTIVE,
    },
    SessionState.CRITIC_OUTPUT_INVALID: {
        SessionState.QUESTION_ACTIVE,
        SessionState.FEEDBACK_DISCUSSION,
    },
    SessionState.CANDIDATE_STALE: {
        SessionState.FEEDBACK_DISCUSSION,
        SessionState.ROUND_FINALIZING,
    },
    SessionState.QUESTION_GENERATION_FAILED: {
        SessionState.QUESTION_GENERATING,
        SessionState.FEEDBACK_DISCUSSION,
        SessionState.SESSION_ENDED,
    },
    SessionState.SESSION_ENDED: set(),
}


class InvalidSessionTransitionError(ValueError):
    pass


class SessionNotFoundError(LookupError):
    pass


class SessionBusyError(RuntimeError):
    pass


def transition_session(
    session: LearningSession,
    target: SessionState,
) -> None:
    current = SessionState(session.status)
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidSessionTransitionError(f"{current} -> {target} is not allowed")
    session.status = target.value


def create_question_record(
    packet,
    session_id: str,
    round_id: str,
    status: str,
) -> Question:
    return Question(
        id=str(packet.question_id),
        session_id=session_id,
        round_id=round_id,
        question_type=packet.question_type,
        difficulty=packet.difficulty,
        student_content_json=packet.student_content.model_dump(mode="json"),
        critic_content_json=packet.critic_content.model_dump(mode="json"),
        knowledge_node_ids=packet.knowledge_node_ids,
        target_error_ids=packet.target_error_ids,
        pedagogical_strategy=packet.pedagogical_strategy,
        status=status,
    )


class LearningSessionOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        websocket_manager: SessionWebSocketManager,
        session_factory=SessionLocal,
    ) -> None:
        self.provider = provider
        self.websocket_manager = websocket_manager
        self.session_factory = session_factory
        self._tasks = set()
        self._candidate_generation_keys = set()

    async def create_session(
        self,
        request: CreateSessionRequest,
    ) -> SessionResponse:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            if not repository.learner_exists(request.learner_id):
                raise SessionNotFoundError(f"Learner not found: {request.learner_id}")

            session = LearningSession(
                learner_id=request.learner_id,
                status=SessionState.SESSION_CREATED.value,
            )
            database.add(session)
            database.flush()
            transition_session(session, SessionState.QUESTION_GENERATING)
            learning_round = LearningRound(
                session_id=session.id,
                state=SessionState.QUESTION_GENERATING.value,
            )
            database.add(learning_round)
            database.flush()

            chapter_service = ChapterQuestioningService(database)
            critic_summary, candidate_constraints = (
                chapter_service.generation_inputs_for_slot(
                    session,
                    slot=ChapterQuestioningService.current_slot(0),
                )
            )
            context = QuestionContextBuilder(database).build(
                request.learner_id,
                critic_summary=critic_summary,
                candidate_constraints=candidate_constraints,
            )
            generation = await QuestionService(self.provider).generate_next_question(
                context
            )
            question = create_question_record(
                generation.packet,
                session.id,
                learning_round.id,
                "active",
            )
            database.add(question)
            database.flush()
            learning_round.question_id = question.id
            learning_round.state = SessionState.QUESTION_ACTIVE.value
            session.current_question_id = question.id
            transition_session(session, SessionState.QUESTION_ACTIVE)
            database.add(
                create_message(
                    session.id,
                    learning_round.id,
                    "questioner",
                    generation.packet.student_content.markdown,
                )
            )
            database.commit()
            session_id = session.id
            question_id = question.id
            round_id = learning_round.id

        self._schedule(self.review_current_question(session_id, question_id))
        self._schedule(
            self.prepare_candidate(
                session_id,
                critic_summary={},
                round_id=round_id,
            )
        )
        return self.get_session_response(session_id)

    def get_session_response(self, session_id: str) -> SessionResponse:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            self._recover_stale_next_question_transition(
                database,
                repository,
                session,
            )
            question = repository.get_current_question(session)
            messages = [
                to_student_visible_message(message).model_dump(mode="json")
                for message in repository.list_messages(session.id)
            ]
            graph_service = GraphService(database)
            knowledge = graph_service.get_knowledge_graph(session.learner_id)
            errors = graph_service.get_error_graph(session.learner_id)
            completed_count = repository.count_completed_rounds(session.id)
            chapter_summary = ChapterQuestioningService(database).response_summary(
                session.id,
                completed_count,
            )
            return SessionResponse(
                session_id=session.id,
                state=SessionState(session.status),
                messages=messages,
                current_question_id=question.id if question else None,
                current_question=(
                    {
                        "question_id": question.id,
                        "markdown": question.student_content_json["markdown"],
                        "input_hint": question.student_content_json.get("input_hint"),
                    }
                    if question
                    else None
                ),
                knowledge_graph=knowledge.nodes,
                error_graph=errors.nodes,
                completed_question_count=completed_count,
                chapter_question_set=chapter_summary,
            )

    def accept_message(
        self,
        session_id: str,
        content: str,
        client_message_id: Optional[UUID] = None,
    ) -> MessageAcceptedResponse:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            current_state = SessionState(session.status)
            if current_state not in {
                SessionState.QUESTION_ACTIVE,
                SessionState.FEEDBACK_DISCUSSION,
            }:
                raise SessionBusyError(f"Session is currently {current_state.value}")
            learning_round = repository.get_current_round(session.id)
            if learning_round is None:
                raise SessionBusyError("Session has no active round")

            message_id = str(client_message_id or uuid4())
            existing = repository.get_message(message_id)
            if existing:
                return MessageAcceptedResponse(
                    message_id=existing.id,
                    status="processing",
                    session_state=SessionState.CRITIC_PROCESSING,
                )

            database.add(
                create_message(
                    session.id,
                    learning_round.id,
                    "student",
                    content,
                    message_id=message_id,
                )
            )
            transition_session(session, SessionState.USER_MESSAGE_RECEIVED)
            transition_session(session, SessionState.CRITIC_PROCESSING)
            database.commit()
            round_id = learning_round.id
            should_preheat_candidate = current_state == SessionState.QUESTION_ACTIVE
            should_fast_advance = (
                current_state == SessionState.FEEDBACK_DISCUSSION
                and self._is_next_question_command(content)
            )

        if should_preheat_candidate:
            self._schedule(
                self.prepare_candidate(
                    session_id,
                    critic_summary={},
                    round_id=round_id,
                )
            )

        if should_fast_advance:
            self._schedule(
                self.process_next_question_request(
                    session_id,
                    message_id,
                    previous_state=current_state,
                )
            )
        else:
            self._schedule(
                self.process_message(
                    session_id,
                    message_id,
                    previous_state=current_state,
                )
            )
        return MessageAcceptedResponse(
            message_id=message_id,
            status="processing",
            session_state=SessionState.CRITIC_PROCESSING,
        )

    async def process_next_question_request(
        self,
        session_id: str,
        message_id: str,
        previous_state: SessionState,
    ) -> None:
        try:
            with self.session_factory() as database:
                repository = SessionRepository(database)
                session = repository.get_session(session_id)
                student_message = repository.get_message(message_id)
                learning_round = repository.get_current_round(session_id)
                if not session or not student_message or not learning_round:
                    await self.recover_processing_failure(session_id)
                    return

                result = CriticTurnResult(
                    intent="next_question",
                    intent_confidence=1.0,
                    student_visible_reply_markdown="好的，我们进入下一题。",
                    verdict="not_applicable",
                    round_action="finalize_round",
                    provisional_knowledge_updates=[],
                    provisional_error_updates=[],
                    should_prepare_next_question=False,
                    should_invalidate_candidate_question=False,
                )
                critic_message = create_message(
                    session.id,
                    learning_round.id,
                    "critic",
                    result.student_visible_reply_markdown,
                    critic_intent=result.intent,
                )
                database.add(critic_message)
                database.flush()
                database.add(create_turn_result_record(student_message.id, result))
                transition_session(session, SessionState.ROUND_FINALIZING)
                learning_round.state = SessionState.ROUND_FINALIZING.value
                database.commit()

                critic_event = CriticReplyReadyEvent(
                    session_id=session.id,
                    payload=CriticReplyReadyPayload(
                        message=to_student_visible_message(critic_message),
                        session_state=SessionState(session.status),
                    ),
                )

            await self.websocket_manager.broadcast(session_id, critic_event)
            await self.finalize_round(session_id)
        except Exception:
            logger.exception("Fast next-question transition failed")
            await self.recover_processing_failure(session_id)

    async def process_message(
        self,
        session_id: str,
        message_id: str,
        previous_state: SessionState,
    ) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            student_message = repository.get_message(message_id)
            learning_round = repository.get_current_round(session_id)
            if not session or not student_message or not learning_round:
                return
            question = repository.get_current_question(session)
            if question is None:
                return

            review_record = repository.get_latest_question_review(question.id)
            if review_record is None:
                await self._review_question_in_database(database, question)
                review_record = repository.get_latest_question_review(question.id)
            review = (
                repository.review_from_record(review_record)
                if review_record
                else QuestionReview(
                    status="needs_revision",
                    quality_score=0.5,
                    issues=["审题尚未完成。"],
                    grading_notes=None,
                )
            )
            packet = repository.packet_from_question(question)
            history = [
                to_critic_context_message(message)
                for message in repository.list_messages(session.id, learning_round.id)
                if message.id != student_message.id
            ]
            previous_record = repository.get_latest_turn_result(learning_round.id)
            previous_result = (
                repository.turn_result_from_record(previous_record)
                if previous_record
                else None
            )
            candidate = repository.get_candidate_question(
                session.id,
                learning_round.id,
            )
            candidate_generation_key = (session.id, learning_round.id)
            candidate_status = (
                self._candidate_status(candidate)
                if candidate
                else (
                    "generating"
                    if candidate_generation_key in self._candidate_generation_keys
                    else None
                )
            )
            stream_id = uuid4()
            on_delta, on_reset = await self._start_critic_stream(
                session_id,
                stream_id,
            )
            execution = await CriticConversationService(self.provider).process_turn(
                CriticTurnContext(
                    session_state=previous_state.value,
                    question_packet=packet,
                    question_review=review,
                    conversation_history=history,
                    student_message=student_message.content_markdown,
                    previous_critic_result=previous_result,
                    candidate_question_status=candidate_status,
                ),
                on_delta=on_delta,
                on_reset=on_reset,
            )
            result = execution.result
            critic_message = create_message(
                session.id,
                learning_round.id,
                "critic",
                result.student_visible_reply_markdown,
                critic_intent=result.intent,
            )
            database.add(critic_message)
            database.flush()
            database.add(create_turn_result_record(student_message.id, result))

            if learning_round.initial_verdict is None and result.verdict not in {
                "not_applicable",
                "critic_uncertain",
            }:
                learning_round.initial_verdict = result.verdict

            if execution.status == "failed":
                transition_session(session, previous_state)
                learning_round.state = previous_state.value
            elif result.round_action == "wait_for_answer":
                transition_session(session, SessionState.QUESTION_ACTIVE)
                learning_round.state = SessionState.QUESTION_ACTIVE.value
            elif result.round_action in {"show_feedback", "continue_discussion"}:
                target = (
                    SessionState.FEEDBACK_DISCUSSION
                    if previous_state == SessionState.FEEDBACK_DISCUSSION
                    or result.round_action == "show_feedback"
                    else SessionState.QUESTION_ACTIVE
                )
                transition_session(session, target)
                learning_round.state = target.value
            elif result.round_action == "end_session":
                transition_session(session, SessionState.SESSION_ENDED)
                session.ended_at = datetime.utcnow()
                learning_round.state = SessionState.SESSION_ENDED.value
            elif result.round_action == "replace_question":
                transition_session(session, SessionState.QUESTION_INVALID)
                learning_round.state = SessionState.QUESTION_INVALID.value
            elif result.round_action == "finalize_round":
                transition_session(session, SessionState.ROUND_FINALIZING)
                learning_round.state = SessionState.ROUND_FINALIZING.value
            database.commit()

            critic_event = CriticReplyReadyEvent(
                session_id=session.id,
                payload=CriticReplyReadyPayload(
                    message=to_student_visible_message(critic_message),
                    session_state=SessionState(session.status),
                    stream_id=stream_id,
                ),
            )

        await self.websocket_manager.broadcast(session_id, critic_event)

        if result.round_action == "finalize_round":
            await self.finalize_round(session_id)
            return
        if result.round_action == "replace_question":
            await self.replace_invalid_question(session_id, student_has_answered=True)
            return
        if result.should_prepare_next_question or result.should_invalidate_candidate_question:
            self._schedule(
                self.prepare_candidate(
                    session_id,
                    critic_summary={},
                    round_id=learning_round.id,
                )
            )

    async def review_current_question(
        self,
        session_id: str,
        question_id: str,
    ) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            question = repository.get_question(question_id)
            session = repository.get_session(session_id)
            if question is None or session is None:
                return
            execution = await self._review_question_in_database(database, question)
            if execution.status == "failed":
                return
            student_has_answered = any(
                message.role == "student"
                for message in repository.list_messages(session.id, question.round_id)
            )
            decision = CriticQuestionReviewService(self.provider).decide_handling(
                execution,
                UUID(question.id),
                student_has_answered,
            )
        if decision.review_status == "invalid":
            await self.replace_invalid_question(session_id, student_has_answered)

    async def prepare_candidate(
        self,
        session_id: str,
        critic_summary: dict,
        round_id: Optional[str] = None,
        replace_existing: bool = False,
    ) -> Optional[str]:
        key = None
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = (
                repository.get_round(round_id)
                if round_id
                else repository.get_current_round(session_id)
            )
            if not session or not learning_round:
                return None
            if learning_round.finalized_at is not None:
                return None
            existing = repository.get_candidate_question(
                session.id,
                learning_round.id,
            )
            if existing and existing.status in {
                "candidate_provisional",
                "candidate_ready",
            }:
                if not replace_existing:
                    return existing.id
            key = (session.id, learning_round.id)
            if key in self._candidate_generation_keys:
                return None
            self._candidate_generation_keys.add(key)
            try:
                chapter_service = ChapterQuestioningService(database)
                target_slot = ChapterQuestioningService.next_slot(
                    repository.count_completed_rounds(session.id)
                )
                plan_summary, candidate_constraints = (
                    chapter_service.generation_inputs_for_slot(
                        session,
                        slot=target_slot,
                        recent_questions=repository.list_recent_formal_questions(
                            session.id
                        ),
                    )
                )
                generation_summary = {
                    **critic_summary,
                    **plan_summary,
                }
                candidate = await CandidateQuestionService(self.provider).generate(
                    database,
                    session,
                    learning_round,
                    generation_summary,
                    candidate_constraints=candidate_constraints,
                )
            finally:
                self._candidate_generation_keys.discard(key)
            if candidate is None:
                return None
            if replace_existing and existing is not None:
                CandidateQuestionService.mark_stale(existing)
                database.commit()
            candidate_id = candidate.id
        await self.websocket_manager.broadcast(
            session_id,
            CandidateQuestionStatusEvent(
                type="candidate_question_ready",
                session_id=UUID(session_id),
            ),
        )
        return candidate_id

    async def invalidate_candidate(self, session_id: str) -> None:
        invalidated = False
        with self.session_factory() as database:
            repository = SessionRepository(database)
            learning_round = repository.get_current_round(session_id)
            if not learning_round:
                return
            candidate = repository.get_candidate_question(
                session_id,
                learning_round.id,
            )
            if candidate:
                CandidateQuestionService.mark_stale(candidate)
                invalidated = True
                database.commit()
        if invalidated:
            await self.websocket_manager.broadcast(
                session_id,
                CandidateQuestionStatusEvent(
                    type="candidate_question_stale",
                    session_id=UUID(session_id),
                ),
            )

    async def finalize_round(self, session_id: str) -> None:
        import asyncio

        deadline = (
            asyncio.get_running_loop().time()
            + NEXT_QUESTION_WAIT_TIMEOUT_SECONDS
        )
        published = None
        while published is None:
            published = await self._publish_prepared_question(session_id)
            if published is not None:
                break
            if asyncio.get_running_loop().time() >= deadline:
                await self._mark_question_generation_failed(session_id)
                await self.recover_processing_failure(session_id)
                return
            await asyncio.sleep(NEXT_QUESTION_WAIT_INTERVAL_SECONDS)

        question_event = QuestionReadyEvent(
            session_id=published["session_id"],
            payload=QuestionReadyPayload(
                question_id=published["next_question_id"],
                markdown=published["next_markdown"],
                input_hint=published["next_input_hint"],
            ),
        )
        await self.websocket_manager.broadcast(session_id, question_event)
        self._schedule(
            self.review_current_question(
                session_id,
                str(published["next_question_id"]),
            )
        )
        self._schedule(
            self.complete_round_summary(
                session_id=session_id,
                completed_round_id=published["completed_round_id"],
                completed_question_id=published["completed_question_id"],
                next_round_id=published["next_round_id"],
            )
        )

    async def _publish_prepared_question(self, session_id: str) -> Optional[dict]:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_current_round(session_id)
            if not session or not learning_round:
                return None
            question = repository.get_current_question(session)
            if not question:
                return None
            candidate = repository.get_candidate_question(
                session.id,
                learning_round.id,
            )

            if candidate is None:
                if (session.id, learning_round.id) in self._candidate_generation_keys:
                    return None
                chapter_service = ChapterQuestioningService(database)
                target_slot = ChapterQuestioningService.next_slot(
                    repository.count_completed_rounds(session.id)
                )
                critic_summary, candidate_constraints = (
                    chapter_service.generation_inputs_for_slot(
                        session,
                        slot=target_slot,
                        recent_questions=repository.list_recent_formal_questions(
                            session.id
                        ),
                    )
                )
                candidate = await CandidateQuestionService(self.provider).generate(
                    database,
                    session,
                    learning_round,
                    critic_summary=critic_summary,
                    candidate_constraints=candidate_constraints,
                )
            if candidate is None:
                return None

            learning_round.finalized_at = datetime.utcnow()
            transition_session(session, SessionState.NEXT_QUESTION_READY)
            learning_round.state = SessionState.NEXT_QUESTION_READY.value
            question.status = "completed"
            CandidateQuestionService.mark_ready(candidate)

            new_round = LearningRound(
                session_id=session.id,
                state=SessionState.QUESTION_ACTIVE.value,
            )
            database.add(new_round)
            database.flush()
            candidate.round_id = new_round.id
            candidate.status = "active"
            new_round.question_id = candidate.id
            session.current_question_id = candidate.id
            transition_session(session, SessionState.QUESTION_ACTIVE)
            question_message = create_message(
                session.id,
                new_round.id,
                "questioner",
                candidate.student_content_json["markdown"],
            )
            database.add(question_message)
            database.commit()
            next_session_id = session.id
            next_question_id = candidate.id
            next_markdown = candidate.student_content_json["markdown"]
            next_input_hint = candidate.student_content_json.get("input_hint")
            completed_round_id = learning_round.id
            completed_question_id = question.id
            next_round_id = new_round.id

        return {
            "session_id": next_session_id,
            "next_question_id": next_question_id,
            "next_markdown": next_markdown,
            "next_input_hint": next_input_hint,
            "completed_round_id": completed_round_id,
            "completed_question_id": completed_question_id,
            "next_round_id": next_round_id,
        }

    async def _mark_question_generation_failed(self, session_id: str) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_current_round(session_id)
            if not session or not learning_round:
                return
            transition_session(session, SessionState.QUESTION_GENERATION_FAILED)
            learning_round.state = SessionState.QUESTION_GENERATION_FAILED.value
            database.commit()

    async def recover_processing_failure(self, session_id: str) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_current_round(session_id)
            if not session or not learning_round:
                return
            message = self._recover_processing_failure_in_database(
                database,
                session,
                learning_round,
            )
            if message is None:
                return
            event = CriticReplyReadyEvent(
                session_id=session.id,
                payload=CriticReplyReadyPayload(
                    message=to_student_visible_message(message),
                    session_state=SessionState.FEEDBACK_DISCUSSION,
                ),
            )

        await self.websocket_manager.broadcast(session_id, event)

    async def recover_round_finalizing_failure(self, session_id: str) -> None:
        await self.recover_processing_failure(session_id)

    def _recover_stale_next_question_transition(
        self,
        database: Session,
        repository: SessionRepository,
        session: LearningSession,
    ) -> None:
        current_state = SessionState(session.status)
        if current_state not in {
            SessionState.CRITIC_PROCESSING,
            SessionState.ROUND_FINALIZING,
            SessionState.QUESTION_GENERATION_FAILED,
        }:
            return

        learning_round = repository.get_current_round(session.id)
        if learning_round is None:
            return
        messages = list(repository.list_messages(session.id, learning_round.id))
        if not messages:
            return
        latest_student = next(
            (message for message in reversed(messages) if message.role == "student"),
            None,
        )
        if latest_student is None or not self._is_next_question_command(
            latest_student.content_markdown
        ):
            return
        latest_message = messages[-1]
        created_at = latest_message.created_at
        if created_at is not None:
            age_seconds = (
                datetime.utcnow() - created_at.replace(tzinfo=None)
            ).total_seconds()
            if age_seconds < STALE_NEXT_QUESTION_SECONDS:
                return
        self._recover_processing_failure_in_database(
            database,
            session,
            learning_round,
        )

    def _recover_processing_failure_in_database(
        self,
        database: Session,
        session: LearningSession,
        learning_round: LearningRound,
    ):
        current_state = SessionState(session.status)
        if current_state not in {
            SessionState.CRITIC_PROCESSING,
            SessionState.ROUND_FINALIZING,
            SessionState.QUESTION_GENERATION_FAILED,
        }:
            return None
        messages = list(
            SessionRepository(database).list_messages(
                session.id,
                learning_round.id,
            )
        )
        existing_recovery = [
            message
            for message in reversed(messages)
            if message.role == "critic"
            and "下一题暂时没有准备好" in message.content_markdown
        ]
        if existing_recovery:
            transition_session(session, SessionState.FEEDBACK_DISCUSSION)
            learning_round.state = SessionState.FEEDBACK_DISCUSSION.value
            database.commit()
            return existing_recovery[0]
        transition_session(session, SessionState.FEEDBACK_DISCUSSION)
        learning_round.state = SessionState.FEEDBACK_DISCUSSION.value
        message = create_message(
            session.id,
            learning_round.id,
            "critic",
            "下一题暂时没有准备好。你可以稍后再输入“下一题”，或者继续追问当前题。",
            critic_intent="ambiguous",
        )
        database.add(message)
        database.commit()
        return message

    async def complete_round_summary(
        self,
        session_id: str,
        completed_round_id: str,
        completed_question_id: str,
        next_round_id: str,
    ) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_round(completed_round_id)
            question = repository.get_question(completed_question_id)
            if not session or not learning_round or not question:
                return
            packet = repository.packet_from_question(question)
            review_record = repository.get_latest_question_review(question.id)
            review = (
                repository.review_from_record(review_record)
                if review_record
                else QuestionReview(
                    status="needs_revision",
                    quality_score=0.5,
                    issues=["审题记录缺失。"],
                )
            )
            history = [
                to_critic_context_message(message)
                for message in repository.list_messages(session.id, learning_round.id)
            ]
            turn_results = [
                repository.turn_result_from_record(record)
                for record in repository.list_turn_results(learning_round.id)
            ]
            candidate = repository.get_candidate_question(
                session.id,
                next_round_id,
            )
            summary_execution = await CriticConversationService(
                self.provider
            ).summarize_discussion(
                DiscussionSummaryContext(
                    question_packet=packet,
                    question_review=review,
                    conversation_history=history,
                    turn_results=turn_results,
                    provisional_candidate_question=(
                        repository.packet_from_question(candidate)
                        if candidate
                        else None
                    ),
                )
            )
            summary = (
                summary_execution.summary
                if summary_execution.status == "completed"
                else self._safe_summary(packet, learning_round)
            )

            graphs_changed = False
            if review.status != "invalid":
                try:
                    with database.begin_nested():
                        graph_service = GraphService(database)
                        for update in summary.final_knowledge_updates:
                            graphs_changed = (
                                graph_service.commit_knowledge_update(
                                    session.learner_id,
                                    learning_round.id,
                                    update,
                                )
                                is not None
                            ) or graphs_changed
                        for update in summary.final_error_updates:
                            graphs_changed = (
                                graph_service.commit_error_update(
                                    session.learner_id,
                                    learning_round.id,
                                    update,
                                )
                                is not None
                            ) or graphs_changed
                except Exception:
                    logger.exception("Graph update transaction rolled back")
                    graphs_changed = False

            learning_round.final_verdict = summary.final_verdict
            learning_round.discussion_summary_json = summary.model_dump(mode="json")
            if learning_round.finalized_at is None:
                learning_round.finalized_at = datetime.utcnow()
            question.status = "completed"
            database.commit()
            completed_count = repository.count_completed_rounds(session.id)

        await self.websocket_manager.broadcast(
            session_id,
            SessionSummaryReadyEvent(
                session_id=UUID(session_id),
                payload=SessionSummaryReadyPayload(
                    completed_question_count=completed_count,
                    graphs_changed=graphs_changed,
                ),
            ),
        )
        await self.prepare_candidate(
            session_id,
            critic_summary=summary.model_dump(mode="json"),
            round_id=next_round_id,
            replace_existing=True,
        )

    async def replace_invalid_question(
        self,
        session_id: str,
        student_has_answered: bool,
    ) -> None:
        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_current_round(session_id)
            if not session or not learning_round:
                return
            current = repository.get_current_question(session)
            if current:
                current.status = "invalid"
            transition_session(session, SessionState.QUESTION_INVALID)
            learning_round.state = SessionState.QUESTION_INVALID.value
            if student_has_answered:
                database.add(
                    create_message(
                        session.id,
                        learning_round.id,
                        "critic",
                        "这道题存在问题，不会影响你的学习记录。我会为你换一道题。",
                        critic_intent="ambiguous",
                    )
                )
            database.commit()

        await self.websocket_manager.broadcast(
            session_id,
            QuestionInvalidEvent(
                session_id=UUID(session_id),
                payload=QuestionInvalidPayload(
                    student_visible_reason_markdown=(
                        "这道题存在问题，不会影响你的学习记录。"
                    )
                ),
            ),
        )

        with self.session_factory() as database:
            repository = SessionRepository(database)
            session = repository.get_session(session_id)
            learning_round = repository.get_current_round(session_id)
            transition_session(session, SessionState.QUESTION_GENERATING)
            learning_round.state = SessionState.QUESTION_GENERATING.value
            recent_records = repository.list_recent_formal_questions(session.id)
            invalid_record = repository.get_current_question(session)
            records_to_avoid = [
                *([invalid_record] if invalid_record else []),
                *(
                    record
                    for record in recent_records
                    if not invalid_record or record.id != invalid_record.id
                ),
            ]
            recent_questions = [
                RecentQuestion(
                    question_id=record.id,
                    question_type=record.question_type,
                    markdown=record.student_content_json["markdown"],
                    knowledge_node_ids=record.knowledge_node_ids,
                )
                for record in records_to_avoid
            ]
            chapter_service = ChapterQuestioningService(database)
            critic_summary, candidate_constraints = (
                chapter_service.generation_inputs_for_slot(
                    session,
                    slot=ChapterQuestioningService.current_slot(
                        repository.count_completed_rounds(session.id)
                    ),
                    recent_questions=records_to_avoid,
                )
            )
            context = QuestionContextBuilder(database).build(
                session.learner_id,
                recent_questions=recent_questions,
                critic_summary=critic_summary,
                candidate_constraints=candidate_constraints,
            )
            generation = await QuestionService(self.provider).generate_next_question(
                context,
            )
            replacement = create_question_record(
                generation.packet,
                session.id,
                learning_round.id,
                "active",
            )
            database.add(replacement)
            database.flush()
            learning_round.question_id = replacement.id
            learning_round.state = SessionState.QUESTION_ACTIVE.value
            session.current_question_id = replacement.id
            transition_session(session, SessionState.QUESTION_ACTIVE)
            database.add(
                create_message(
                    session.id,
                    learning_round.id,
                    "questioner",
                    replacement.student_content_json["markdown"],
                )
            )
            database.commit()
            event = QuestionReadyEvent(
                session_id=session.id,
                payload=QuestionReadyPayload(
                    question_id=replacement.id,
                    markdown=replacement.student_content_json["markdown"],
                    input_hint=replacement.student_content_json.get("input_hint"),
                ),
            )
            replacement_id = replacement.id
        await self.websocket_manager.broadcast(session_id, event)
        self._schedule(self.review_current_question(session_id, replacement_id))

    async def _review_question_in_database(
        self,
        database: Session,
        question: Question,
    ):
        repository = SessionRepository(database)
        packet = repository.packet_from_question(question)
        recent = [
            RecentQuestion(
                question_id=record.id,
                question_type=record.question_type,
                markdown=record.student_content_json["markdown"],
                knowledge_node_ids=record.knowledge_node_ids,
            )
            for record in repository.list_recent_formal_questions(question.session_id)
            if record.id != question.id
        ]
        return await CriticQuestionReviewService(self.provider).review_and_persist(
            QuestionReviewContext(
                question_packet=packet,
                expected_knowledge_node_ids=packet.knowledge_node_ids,
                expected_difficulty_min=max(1, packet.difficulty - 1),
                expected_difficulty_max=min(5, packet.difficulty + 1),
                recent_questions=recent,
            ),
            database,
        )

    @staticmethod
    def _candidate_status(question: Question) -> str:
        return question.status.removeprefix("candidate_")

    @staticmethod
    def _is_next_question_command(content: str) -> bool:
        normalized = (
            content.strip()
            .lower()
            .removesuffix("。")
            .removesuffix("！")
            .removesuffix("!")
            .removesuffix(".")
        )
        return normalized in NEXT_QUESTION_COMMANDS

    @staticmethod
    def _safe_summary(packet, learning_round) -> DiscussionSummary:
        original = learning_round.initial_verdict or "critic_uncertain"
        return DiscussionSummary(
            question_id=packet.question_id,
            original_verdict=original,
            final_verdict="critic_uncertain",
            diagnosis_changed=original != "critic_uncertain",
            discussion_resolved=False,
            confirmed_knowledge=[],
            remaining_knowledge_gaps=[],
            active_errors=[],
            resolved_errors=[],
            final_knowledge_updates=[],
            final_error_updates=[],
            next_question_guidance={"strategy": "safe_retry"},
        )

    async def _start_critic_stream(
        self,
        session_id: str,
        stream_id: UUID,
    ):
        await self.websocket_manager.broadcast(
            session_id,
            MessageStreamStartedEvent(
                session_id=UUID(session_id),
                payload=MessageStreamStartedPayload(
                    stream_id=stream_id,
                    role="critic",
                ),
            ),
        )

        async def on_delta(delta: str) -> None:
            if not delta:
                return
            await self.websocket_manager.broadcast(
                session_id,
                MessageStreamDeltaEvent(
                    session_id=UUID(session_id),
                    payload=MessageStreamDeltaPayload(
                        stream_id=stream_id,
                        role="critic",
                        delta=delta,
                    ),
                ),
            )

        async def on_reset() -> None:
            await self.websocket_manager.broadcast(
                session_id,
                MessageStreamResetEvent(
                    session_id=UUID(session_id),
                    payload=MessageStreamResetPayload(
                        stream_id=stream_id,
                        role="critic",
                    ),
                ),
            )

        return on_delta, on_reset

    def _schedule(self, coroutine) -> None:
        import asyncio

        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def finish(completed_task) -> None:
            self._tasks.discard(completed_task)
            if completed_task.cancelled():
                return
            error = completed_task.exception()
            if error:
                logger.exception(
                    "Background session task failed",
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(finish)
