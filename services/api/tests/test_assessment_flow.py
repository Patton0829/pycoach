"""Exercise finalized assessment accounting through the actual two-agent mock flow."""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm.base import LLMProviderError
from app.llm.mock import DemoMockLLMProvider
from app.models.base import Base
from app.models.entities import (
    AssessmentEvidence,
    GraphUpdateEvent,
    LearnerKnowledgeNode,
    LearningRound,
    Question,
)
from app.schemas.session import CreateSessionRequest, SessionState
from app.seed import seed_database
from app.services.session_orchestrator import LearningSessionOrchestrator

CURRICULUM_DIR = Path(__file__).resolve().parents[3] / "curriculum/python_iterator_v1"


async def settle(orchestrator):
    while orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))
        await asyncio.sleep(0)


class RecordingWebSocket:
    def __init__(self, factory):
        self.factory = factory
        self.events = []
        self.evidence_counts_on_publish = []

    async def broadcast(self, session_id, event):
        self.events.append(event.model_dump(mode="json"))
        if event.type == "question_ready":
            with self.factory() as database:
                self.evidence_counts_on_publish.append(database.scalar(
                    select(func.count()).select_from(AssessmentEvidence)
                ))


class SplitNodeMock(DemoMockLLMProvider):
    def _discussion_summary(self, context):
        result = super()._discussion_summary(context)
        nodes = context["question_packet"]["knowledge_node_ids"]
        result["knowledge_assessments"] = [
            {"node_id": node, "outcome": "correct" if i == 0 else "incorrect",
             "reason": "Explicit independent assessment of this target."}
            for i, node in enumerate(nodes)
        ]
        return result


class FailingSummaryMock(DemoMockLLMProvider):
    async def generate_structured(self, messages, schema):
        if schema.__name__ == "DiscussionSummary":
            raise LLMProviderError("Synthetic summary failure")
        return await super().generate_structured(messages, schema)


class AssessmentFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.factory() as database:
            seed_database(database, CURRICULUM_DIR)
        self.provider = DemoMockLLMProvider()
        self.websocket = RecordingWebSocket(self.factory)
        self.orchestrator = LearningSessionOrchestrator(
            self.provider, self.websocket, session_factory=self.factory,
        )

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def create(self):
        created = await self.orchestrator.create_session(CreateSessionRequest(
            learner_id="demo_user", module="python_iterator",
        ))
        await settle(self.orchestrator)
        with self.factory() as database:
            question = database.get(Question, str(created.current_question_id))
            return str(created.session_id), question

    async def send(self, session_id, message):
        self.orchestrator.accept_message(session_id, message)
        await settle(self.orchestrator)

    def evidence(self, round_id):
        with self.factory() as database:
            return list(database.scalars(select(AssessmentEvidence).where(
                AssessmentEvidence.round_id == round_id,
            )))

    def counts(self, node_id):
        with self.factory() as database:
            state = database.scalar(select(LearnerKnowledgeNode).where(
                LearnerKnowledgeNode.learner_id == "demo_user",
                LearnerKnowledgeNode.knowledge_node_id == node_id,
            ))
            return ((state.evaluated_question_count, state.correct_question_count, state.mastery)
                    if state else (0, 0, 0))

    def test_correct_answer_is_counted_only_after_final_summary_and_not_replayed(self):
        async def scenario():
            session_id, question = await self.create()
            node = question.knowledge_node_ids[0]
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            self.assertEqual(self.counts(node), (0, 0, 0))
            self.assertEqual(self.evidence(question.round_id), [])
            await self.send(session_id, "下一题")
            self.assertEqual(self.counts(node), (1, 1, 0.05))
            self.assertTrue(self.evidence(question.round_id)[0].counted)
            # Publishing the next item precedes summary completion, but cannot score early.
            self.assertEqual(self.websocket.evidence_counts_on_publish, [0])
            with self.factory() as database:
                event_count = database.scalar(select(func.count()).select_from(GraphUpdateEvent))
                current_question = database.get(Question, str(
                    self.orchestrator.get_session_response(session_id).current_question_id
                ))
            summary_calls = sum(name == "DiscussionSummary" for name, _ in self.provider.calls)
            await self.orchestrator.complete_round_summary(
                session_id, question.round_id, question.id, current_question.round_id,
            )
            self.assertEqual(sum(name == "DiscussionSummary" for name, _ in self.provider.calls),
                             summary_calls)
            self.assertEqual(self.counts(node), (1, 1, 0.05))
            self.assertEqual(len(self.evidence(question.round_id)), 1)
            with self.factory() as database:
                self.assertEqual(database.scalar(
                    select(func.count()).select_from(GraphUpdateEvent)
                ), event_count)

        asyncio.run(scenario())

    def test_hint_before_first_answer_is_excluded(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, "给我一个例子")
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "下一题")
            evidence = self.evidence(question.round_id)[0]
            self.assertIsNotNone(evidence.basis_message_id)
            self.assertEqual(evidence.assistance, "hint")
            self.assertEqual(evidence.exclusion_reason, "assisted_answer")
            self.assertFalse(evidence.counted)
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (0, 0, 0))

        asyncio.run(scenario())

    def test_ending_session_finalizes_current_answer(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "结束本次学习")
            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(response.state, SessionState.SESSION_ENDED)
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (1, 1, 0.05))
            self.assertEqual(len(self.evidence(question.round_id)), 1)
            self.assertEqual(self.websocket.evidence_counts_on_publish, [])

        asyncio.run(scenario())

    def test_ending_without_answer_records_exclusion_not_failure(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, "结束")
            evidence = self.evidence(question.round_id)[0]
            self.assertFalse(evidence.counted)
            self.assertEqual(evidence.exclusion_reason, "no_answer")
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (0, 0, 0))

        asyncio.run(scenario())

    def test_later_uncertainty_does_not_erase_a_correct_independent_answer(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "我还是不确定")
            await self.send(session_id, "下一题")
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (1, 1, 0.05))

        asyncio.run(scenario())

    def test_later_answer_after_hint_does_not_replace_an_incorrect_first_answer(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, "This is an incorrect answer")
            await self.send(session_id, "给我一个例子")
            await self.send(session_id, "这里用 next(iterator) 为什么？")
            await self.send(session_id, "下一题")
            evidence = self.evidence(question.round_id)[0]
            self.assertEqual(evidence.outcome, "incorrect")
            self.assertEqual(evidence.assistance, "none")
            self.assertTrue(evidence.counted)
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (1, 0, 0))

        asyncio.run(scenario())

    def test_final_correction_of_a_misjudged_first_answer_counts_the_corrected_result(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, "This is an incorrect answer")
            await self.send(session_id, "请重新检查，这题有问题")
            await self.send(session_id, "下一题")
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (1, 1, 0.05))
            self.assertEqual(self.evidence(question.round_id)[0].outcome, "correct")

        asyncio.run(scenario())

    def test_two_targets_use_explicit_per_node_results(self):
        async def scenario():
            self.orchestrator.provider = SplitNodeMock()
            session_id, question = await self.create()
            targets = ["python.iterator.exhaustion", "python.stop_iteration"]
            with self.factory() as database:
                record = database.get(Question, question.id)
                record.knowledge_node_ids = targets
                database.commit()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "下一题")
            self.assertEqual(self.counts(targets[0]), (1, 1, 0.05))
            self.assertEqual(self.counts(targets[1]), (1, 0, 0))
            self.assertEqual({item.outcome for item in self.evidence(question.round_id)},
                             {"correct", "incorrect"})

        asyncio.run(scenario())

    def test_failed_summary_keeps_unassessable_evidence_without_increment(self):
        async def scenario():
            self.orchestrator.provider = FailingSummaryMock()
            session_id, question = await self.create()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "下一题")
            evidence = self.evidence(question.round_id)[0]
            self.assertEqual(evidence.outcome, "unassessable")
            self.assertFalse(evidence.counted)
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (0, 0, 0))

        asyncio.run(scenario())

    def test_student_dto_and_events_exclude_internal_assessment_material(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            await self.send(session_id, "下一题")
            payload = self.orchestrator.get_session_response(session_id).model_dump(mode="json")
            visible = str([payload, self.websocket.events])
            for internal in ["critic_content", "grading_rubric", "knowledge_assessments",
                             "basis_message_id", "counted_question_key", "score_policy_version"]:
                self.assertNotIn(internal, visible)

        asyncio.run(scenario())

    def test_failure_during_finalization_rolls_back_evidence_counts_and_audit(self):
        async def scenario():
            session_id, question = await self.create()
            with self.factory() as database:
                current = database.get(Question, question.id)
                current.target_error_ids = ["iter_vs_next"]
                database.commit()
            await self.send(session_id, question.critic_content_json["acceptable_answers"][0])
            with self.factory() as database:
                current_round = database.get(LearningRound, question.round_id)
                current_round.state = "ROUND_FINALIZING"
                database.commit()
            with patch("app.services.graph_service.GraphService.commit_error_update",
                       side_effect=RuntimeError("Synthetic persistence failure")):
                with self.assertRaises(RuntimeError):
                    await self.orchestrator.complete_round_summary(
                        session_id, question.round_id, question.id, question.round_id,
                    )
            self.assertEqual(self.evidence(question.round_id), [])
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (0, 0, 0))
            with self.factory() as database:
                self.assertIsNone(database.get(LearningRound, question.round_id)
                                  .discussion_summary_json)
                self.assertEqual(database.scalar(select(func.count())
                                                .select_from(GraphUpdateEvent)), 0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
