from datetime import datetime
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.entities import ChapterQuestionSet, ErrorType, LearningSession, Question
from app.repositories.question_repository import QuestionRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.chapter_plan import (
    ActiveErrorPriority,
    ChapterQuestionBlueprintItem,
    ChapterQuestionSetPlan,
    ChapterQuestionSetSummary,
    LearnerLevel,
)
from app.schemas.question import CandidateConstraints

CHAPTER_ID = "python_iterator"
CHAPTER_TITLE = "Python 迭代器"
TARGET_QUESTION_COUNT = 10

LEVEL_TYPE_SEQUENCES = {
    "novice": [
        "multiple_choice",
        "multiple_choice",
        "code_blank",
        "code_blank",
        "output_prediction",
        "multiple_choice",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "short_explanation",
    ],
    "intermediate": [
        "multiple_choice",
        "code_blank",
        "output_prediction",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "multiple_choice",
    ],
    "advanced": [
        "multiple_choice",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "output_prediction",
        "code_blank",
        "short_explanation",
    ],
}

LEVEL_DIFFICULTIES = {
    "novice": [1, 1, 1, 2, 2, 2, 2, 2, 3, 3],
    "intermediate": [1, 2, 2, 2, 3, 3, 3, 3, 4, 4],
    "advanced": [2, 2, 3, 3, 3, 4, 4, 4, 5, 5],
}

COGNITIVE_GOALS = [
    "recognize",
    "construct",
    "retrieve",
    "trace_state",
    "contrast_operations",
    "predict_output",
    "diagnose_exhaustion",
    "explain_protocol",
    "transfer",
    "synthesize",
]

GOAL_NODE_PREFERENCES = {
    "recognize": ["python.iterable", "python.iterator"],
    "construct": ["python.iterator.iter"],
    "retrieve": ["python.iterator.next"],
    "trace_state": ["python.iterator.state"],
    "contrast_operations": ["python.iterator.iter", "python.iterator.next"],
    "predict_output": ["python.iterator.state", "python.iterator.next"],
    "diagnose_exhaustion": ["python.iterator.exhaustion", "python.stop_iteration"],
    "explain_protocol": ["python.for_loop.protocol"],
    "transfer": ["python.for_loop.protocol", "python.generator.intro"],
    "synthesize": [
        "python.iterator",
        "python.iterator.state",
        "python.iterator.exhaustion",
    ],
}

PEDAGOGICAL_STRATEGIES = {
    "recognize": "concept_discrimination",
    "construct": "generation_effect",
    "retrieve": "retrieval_practice",
    "trace_state": "state_tracing",
    "contrast_operations": "contrastive_practice",
    "predict_output": "output_prediction",
    "diagnose_exhaustion": "error_diagnosis",
    "explain_protocol": "protocol_explanation",
    "transfer": "transfer_practice",
    "synthesize": "mixed_synthesis",
}

PROMPT_BRIEFS = {
    "recognize": "区分可迭代对象、迭代器，以及哪个对象能直接传给 next()。",
    "construct": "让学生补全 iter(obj)，明确这是创建迭代器而不是取元素。",
    "retrieve": "让学生补全 next(iterator)，检验从迭代器取下一个元素。",
    "trace_state": "要求追踪连续 next() 后迭代器内部位置的变化。",
    "contrast_operations": "对比 iter(obj) 重新创建迭代器与 next(it) 推进状态的差异。",
    "predict_output": "给出短代码，让学生逐行预测 print 输出。",
    "diagnose_exhaustion": "检验迭代器耗尽后继续 next() 会触发 StopIteration。",
    "explain_protocol": "让学生说明 for 循环背后的 iter()/next()/StopIteration 协议。",
    "transfer": "迁移到生成器或 for 循环场景，但不超出迭代器核心范围。",
    "synthesize": "综合状态推进、耗尽和异常处理，要求学生给出完整推理。",
}

CORE_PRINCIPLES = [
    "可迭代对象能通过 iter(obj) 创建迭代器。",
    "迭代器保存当前位置，next(iterator) 返回下一个元素并推进状态。",
    "同一个迭代器被消耗后不会自动回到开头。",
    "迭代器耗尽后继续 next() 会抛出 StopIteration。",
    "for 循环本质上使用 iter()、next() 和 StopIteration 协议。",
]

QUESTION_QUALITY_CHECKS = [
    "student_content 只包含学生可见题干，不泄露答案。",
    "critic_content 包含参考答案、可接受答案和评分依据。",
    "题目只覆盖 1-2 个目标知识点。",
    "题面形式不能与最近题目只做数字或变量名替换。",
]

SET_QUALITY_CHECKS = [
    "10 题覆盖识别、构造、取值、状态、耗尽、协议和迁移。",
    "难度随 learner_level 渐进，不在前几题过早综合多个薄弱点。",
    "优先覆盖高严重度错误类型，同时避免每题都考同一错误。",
]


class ChapterQuestioningService:
    def __init__(self, database: Session) -> None:
        self.database = database
        self.question_repository = QuestionRepository(database)
        self.session_repository = SessionRepository(database)

    def create_question_set_for_session(
        self,
        session: LearningSession,
        chapter_id: str = CHAPTER_ID,
    ) -> ChapterQuestionSet:
        existing = self.session_repository.get_chapter_question_set(session.id)
        if existing is not None:
            return existing

        plan = self.generate_plan(session.learner_id, chapter_id)
        record = ChapterQuestionSet(
            session_id=session.id,
            learner_id=session.learner_id,
            chapter_id=plan.chapter_id,
            chapter_title=plan.chapter_title,
            target_question_count=plan.question_count,
            learner_level=plan.learner_level,
            average_mastery=plan.average_mastery,
            blueprint_json=plan.model_dump(mode="json"),
            created_at=datetime.utcnow(),
        )
        self.database.add(record)
        self.database.flush()
        return record

    def get_question_set_for_session(
        self,
        session_id: str,
    ) -> ChapterQuestionSet | None:
        return self.session_repository.get_chapter_question_set(session_id)

    def generate_plan(
        self,
        learner_id: str,
        chapter_id: str = CHAPTER_ID,
    ) -> ChapterQuestionSetPlan:
        nodes = list(self.question_repository.list_knowledge_nodes())
        error_types = list(self.question_repository.list_error_types())
        learner_nodes = self.question_repository.list_personal_knowledge(learner_id)
        learner_errors = self.question_repository.list_personal_errors(learner_id)
        mastery_by_node = {item.knowledge_node_id: item.mastery for item in learner_nodes}
        average_mastery = self._average_mastery(nodes, mastery_by_node)
        level = self._infer_level(average_mastery)
        active_errors = [
            ActiveErrorPriority(
                error_id=item.error_type_id,
                severity=item.severity,
                status=item.status,
            )
            for item in learner_errors
            if item.status in {"new", "active", "improving", "relapsed"}
            and item.severity > 0
        ]
        active_errors.sort(key=lambda item: item.severity, reverse=True)

        items: list[ChapterQuestionBlueprintItem] = []
        for index, goal in enumerate(COGNITIVE_GOALS):
            target_nodes = self._choose_nodes_for_goal(
                goal,
                nodes,
                error_types,
                mastery_by_node,
                active_errors,
            )
            target_errors = self._choose_errors_for_nodes(
                target_nodes,
                error_types,
                active_errors,
            )
            items.append(
                ChapterQuestionBlueprintItem(
                    slot=index + 1,
                    question_type=LEVEL_TYPE_SEQUENCES[level][index],
                    difficulty=LEVEL_DIFFICULTIES[level][index],
                    cognitive_goal=goal,
                    target_knowledge_node_ids=target_nodes,
                    target_error_ids=target_errors,
                    pedagogical_strategy=PEDAGOGICAL_STRATEGIES[goal],
                    prompt_brief=PROMPT_BRIEFS[goal],
                    quality_checks=QUESTION_QUALITY_CHECKS,
                )
            )

        return ChapterQuestionSetPlan(
            chapter_id=chapter_id,
            chapter_title=CHAPTER_TITLE,
            question_count=TARGET_QUESTION_COUNT,
            learner_level=level,
            average_mastery=average_mastery,
            active_error_priorities=active_errors[:3],
            core_principles=CORE_PRINCIPLES,
            questions=items,
            set_level_quality_checks=SET_QUALITY_CHECKS,
        )

    def plan_from_record(self, record: ChapterQuestionSet) -> ChapterQuestionSetPlan:
        return ChapterQuestionSetPlan.model_validate(record.blueprint_json)

    def response_summary(
        self,
        session_id: str,
        completed_question_count: int,
    ) -> ChapterQuestionSetSummary | None:
        record = self.get_question_set_for_session(session_id)
        if record is None:
            return None
        slot = min(completed_question_count + 1, record.target_question_count)
        return ChapterQuestionSetSummary(
            chapter_id=record.chapter_id,
            chapter_title=record.chapter_title,
            target_question_count=record.target_question_count,
            current_question_slot=max(1, slot),
            learner_level=record.learner_level,
            average_mastery=record.average_mastery,
        )

    def generation_inputs_for_slot(
        self,
        session: LearningSession,
        slot: int,
        recent_questions: Sequence[Question] = (),
    ) -> tuple[dict, CandidateConstraints]:
        record = self.create_question_set_for_session(session)
        plan = self.plan_from_record(record)
        if slot > plan.question_count:
            return self._default_inputs_after_planned_set(plan, recent_questions)
        item = self._blueprint_item_for_slot(plan, slot)
        recent_ids = [question.id for question in recent_questions]
        recent_markdown = [
            question.student_content_json["markdown"]
            for question in recent_questions
            if question.student_content_json.get("markdown")
        ]
        constraints = CandidateConstraints(
            allowed_question_types=[item.question_type],
            preferred_question_type=item.question_type,
            allowed_knowledge_node_ids=item.target_knowledge_node_ids,
            allowed_error_ids=item.target_error_ids,
            max_code_lines=self._max_code_lines(item.difficulty),
            max_knowledge_nodes=len(item.target_knowledge_node_ids),
            avoid_question_ids=recent_ids,
            avoid_markdown=recent_markdown,
        )
        critic_summary = {
            "chapter_question_set": {
                "chapter_id": plan.chapter_id,
                "chapter_title": plan.chapter_title,
                "question_count": plan.question_count,
                "learner_level": plan.learner_level,
                "average_mastery": plan.average_mastery,
            },
            "chapter_question_blueprint": item.model_dump(mode="json"),
            "chapter_core_principles": plan.core_principles,
            "set_level_quality_checks": plan.set_level_quality_checks,
        }
        return critic_summary, constraints

    @staticmethod
    def current_slot(completed_question_count: int) -> int:
        return min(completed_question_count + 1, TARGET_QUESTION_COUNT)

    @staticmethod
    def next_slot(completed_question_count: int) -> int:
        return completed_question_count + 2

    @staticmethod
    def _infer_level(average_mastery: float) -> LearnerLevel:
        if average_mastery < 0.35:
            return "novice"
        if average_mastery < 0.70:
            return "intermediate"
        return "advanced"

    @staticmethod
    def _average_mastery(nodes: Sequence[object], mastery_by_node: dict[str, float]) -> float:
        if not nodes:
            return 0.0
        total = sum(mastery_by_node.get(node.id, 0.0) for node in nodes)
        return round(total / len(nodes), 3)

    @staticmethod
    def _blueprint_item_for_slot(
        plan: ChapterQuestionSetPlan,
        slot: int,
    ) -> ChapterQuestionBlueprintItem:
        return plan.questions[slot - 1]

    @staticmethod
    def _default_inputs_after_planned_set(
        plan: ChapterQuestionSetPlan,
        recent_questions: Sequence[Question],
    ) -> tuple[dict, CandidateConstraints]:
        recent_ids = [question.id for question in recent_questions]
        recent_markdown = [
            question.student_content_json["markdown"]
            for question in recent_questions
            if question.student_content_json.get("markdown")
        ]
        return (
            {
                "chapter_question_set": {
                    "chapter_id": plan.chapter_id,
                    "chapter_title": plan.chapter_title,
                    "question_count": plan.question_count,
                    "learner_level": plan.learner_level,
                    "average_mastery": plan.average_mastery,
                    "completed": True,
                }
            },
            CandidateConstraints(
                avoid_question_ids=recent_ids,
                avoid_markdown=recent_markdown,
            ),
        )

    @staticmethod
    def _max_code_lines(difficulty: int) -> int:
        if difficulty <= 1:
            return 8
        if difficulty <= 3:
            return 14
        return 20

    def _choose_nodes_for_goal(
        self,
        goal: str,
        nodes: Sequence[object],
        error_types: Sequence[ErrorType],
        mastery_by_node: dict[str, float],
        active_errors: Sequence[ActiveErrorPriority],
    ) -> list[str]:
        existing_node_ids = {node.id for node in nodes}
        preferred = [
            node_id
            for node_id in GOAL_NODE_PREFERENCES[goal]
            if node_id in existing_node_ids
        ]
        error_related = self._active_error_related_nodes(error_types, active_errors)
        ranked = sorted(
            preferred,
            key=lambda node_id: (
                0 if node_id in error_related else 1,
                mastery_by_node.get(node_id, 0.0),
                node_id,
            ),
        )
        if ranked:
            return ranked[:2]

        fallback = sorted(
            existing_node_ids,
            key=lambda node_id: (mastery_by_node.get(node_id, 0.0), node_id),
        )
        return fallback[:1]

    @staticmethod
    def _active_error_related_nodes(
        error_types: Sequence[ErrorType],
        active_errors: Sequence[ActiveErrorPriority],
    ) -> set[str]:
        error_type_by_id = {item.id: item for item in error_types}
        related: set[str] = set()
        for active_error in active_errors:
            error_type = error_type_by_id.get(active_error.error_id)
            if error_type is not None:
                related.update(error_type.related_knowledge_nodes)
        return related

    @staticmethod
    def _choose_errors_for_nodes(
        node_ids: Sequence[str],
        error_types: Sequence[ErrorType],
        active_errors: Sequence[ActiveErrorPriority],
    ) -> list[str]:
        node_id_set = set(node_ids)
        error_type_by_id = {item.id: item for item in error_types}
        active = [
            item.error_id
            for item in active_errors
            if error_type_by_id.get(item.error_id) is not None
            and node_id_set.intersection(error_type_by_id[item.error_id].related_knowledge_nodes)
        ]
        if active:
            return active[:2]
        related = [
            error_type.id
            for error_type in error_types
            if node_id_set.intersection(error_type.related_knowledge_nodes)
        ]
        return related[:2]
