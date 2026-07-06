from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
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
from app.schemas.question import CandidateConstraints, QuestionType

DEFAULT_ASSESSMENT_ID = "python_iterator"
ITERATOR_TITLE = "Python 迭代器"
ITERATOR_TARGET_QUESTION_COUNT = 10
FOUNDATION_TARGET_QUESTION_COUNT = 35
CHAPTER_TARGET_QUESTION_COUNT = 10


@dataclass(frozen=True)
class AssessmentSpec:
    module_id: str
    title: str
    target_question_count: int
    node_ids: tuple[str, ...]
    core_principles: tuple[str, ...]
    set_level_quality_checks: tuple[str, ...]
    source_skill: str
    mode: str


PYTHON_TUTORIAL_CHAPTER_NODES: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "python_tutorial_ch3": (
        "Python 入门章节测试",
        (
            "python.ch3.numbers",
            "python.ch3.text",
            "python.ch3.sequence_indexing",
            "python.ch3.lists",
            "python.ch3.assignment_mutability",
        ),
        (
            "数字、文本和列表是 Python 入门的基础数据操作对象。",
            "索引从 0 开始，切片使用左闭右开边界。",
            "赋值绑定名字，可变对象的别名会共享变更。",
        ),
    ),
    "python_tutorial_ch4": (
        "控制流章节测试",
        (
            "python.ch4.if",
            "python.ch4.for_range",
            "python.ch4.loop_control",
            "python.ch4.functions",
            "python.ch4.arguments",
        ),
        (
            "控制流决定代码执行路径。",
            "range() 的 stop 不包含在结果中。",
            "函数调用的参数绑定规则会影响实际执行。",
        ),
    ),
    "python_tutorial_ch5": (
        "数据结构章节测试",
        (
            "python.ch5.list_methods",
            "python.ch5.comprehensions",
            "python.ch5.tuples_sequences",
            "python.ch5.sets_dicts",
            "python.ch5.looping_conditions",
        ),
        (
            "不同容器有不同的访问、更新和迭代语义。",
            "原地修改方法和创建新对象的表达式必须区分。",
            "循环技巧可以把多个集合结构组合起来处理。",
        ),
    ),
    "python_tutorial_ch6": (
        "模块章节测试",
        (
            "python.ch6.imports",
            "python.ch6.module_execution",
            "python.ch6.search_path",
            "python.ch6.dir",
            "python.ch6.packages",
        ),
        (
            "模块是可复用代码和命名空间的组织单位。",
            "不同 import 形式会绑定不同名字。",
            "包和搜索路径决定模块如何被定位和加载。",
        ),
    ),
    "python_tutorial_ch7": (
        "输入输出章节测试",
        (
            "python.ch7.fstrings_format",
            "python.ch7.str_repr",
            "python.ch7.open_modes",
            "python.ch7.with_files",
            "python.ch7.json",
        ),
        (
            "格式化输出关注展示形式，repr 更偏向可调试表示。",
            "文件模式、编码和上下文管理决定 I/O 行为。",
            "JSON 是结构化数据持久化的一种常见方式。",
        ),
    ),
    "python_tutorial_ch8": (
        "错误与异常章节测试",
        (
            "python.ch8.syntax_vs_exception",
            "python.ch8.try_except",
            "python.ch8.raise",
            "python.ch8.finally_cleanup",
            "python.ch8.custom_exceptions",
        ),
        (
            "语法错误和运行时异常发生在不同阶段。",
            "try/except/else/finally 共同决定异常路径。",
            "自定义异常应该表达清晰的业务错误类型。",
        ),
    ),
    "python_tutorial_ch9": (
        "类章节测试",
        (
            "python.ch9.namespaces_scopes",
            "python.ch9.class_definition",
            "python.ch9.instance_methods",
            "python.ch9.class_instance_variables",
            "python.ch9.inheritance",
        ),
        (
            "类、实例和方法依赖命名空间与属性查找规则。",
            "self 指向当前实例，实例属性和类变量语义不同。",
            "继承通过方法查找顺序复用或覆盖行为。",
        ),
    ),
}

FOUNDATION_NODE_IDS = tuple(
    node_id
    for _, node_ids, _ in PYTHON_TUTORIAL_CHAPTER_NODES.values()
    for node_id in node_ids
)

ITERATOR_NODE_IDS = (
    "python.iterable",
    "python.iterator",
    "python.iterator.iter",
    "python.iterator.next",
    "python.iterator.state",
    "python.iterator.exhaustion",
    "python.stop_iteration",
    "python.for_loop.protocol",
    "python.generator.intro",
)

ITERATOR_CORE_PRINCIPLES = (
    "可迭代对象能通过 iter(obj) 创建迭代器。",
    "迭代器保存当前位置，next(iterator) 返回下一个元素并推进状态。",
    "同一个迭代器被消耗后不会自动回到开头。",
    "迭代器耗尽后继续 next() 会抛出 StopIteration。",
    "for 循环本质上使用 iter()、next() 和 StopIteration 协议。",
)

QUESTION_QUALITY_CHECKS = [
    "student_content 只包含学生可见题干，不泄露答案。",
    "critic_content 包含参考答案、可接受答案和评分依据。",
    "题目只覆盖 1-2 个目标知识点。",
    "题面形式不能与最近题目只做数字或变量名替换。",
]

ITERATOR_SET_QUALITY_CHECKS = (
    "10 题覆盖识别、构造、取值、状态、耗尽、协议和迁移。",
    "难度随 learner_level 渐进，不在前几题过早综合多个薄弱点。",
    "优先覆盖高严重度错误类型，同时避免每题都考同一错误。",
)

CHAPTER_SET_QUALITY_CHECKS = (
    "10 题覆盖章节核心概念、代码补全、输出预测、误区诊断和迁移解释。",
    "题目必须限定在所选章节的知识节点范围内。",
    "根据 learner_level 调整代码长度、推理步数和边界情况复杂度。",
)

FOUNDATION_SET_QUALITY_CHECKS = (
    "35 题覆盖 Python Tutorial 第 3-9 章，每章 5 个核心知识节点。",
    "每章至少包含识别、补全、追踪、误区和解释/迁移信号。",
    "最终诊断应能形成整体等级、章节短板和知识节点掌握画像。",
)

ASSESSMENT_SPECS: dict[str, AssessmentSpec] = {
    DEFAULT_ASSESSMENT_ID: AssessmentSpec(
        module_id=DEFAULT_ASSESSMENT_ID,
        title=ITERATOR_TITLE,
        target_question_count=ITERATOR_TARGET_QUESTION_COUNT,
        node_ids=ITERATOR_NODE_IDS,
        core_principles=ITERATOR_CORE_PRINCIPLES,
        set_level_quality_checks=ITERATOR_SET_QUALITY_CHECKS,
        source_skill="chapter-adaptive-questioning",
        mode="iterator",
    ),
    "python_foundation_diagnostic": AssessmentSpec(
        module_id="python_foundation_diagnostic",
        title="Python 综合能力诊断（3-9 章）",
        target_question_count=FOUNDATION_TARGET_QUESTION_COUNT,
        node_ids=FOUNDATION_NODE_IDS,
        core_principles=(
            "综合诊断按 Python Tutorial 第 3-9 章建立基础画像。",
            "每章覆盖 5 个核心节点，用于定位章节短板和后续学习路径。",
            "题目从识别到追踪、误区诊断和解释迁移逐步收集证据。",
        ),
        set_level_quality_checks=FOUNDATION_SET_QUALITY_CHECKS,
        source_skill="python-foundation-diagnostic",
        mode="foundation",
    ),
}

for module_id, (title, node_ids, principles) in PYTHON_TUTORIAL_CHAPTER_NODES.items():
    ASSESSMENT_SPECS[module_id] = AssessmentSpec(
        module_id=module_id,
        title=title,
        target_question_count=CHAPTER_TARGET_QUESTION_COUNT,
        node_ids=node_ids,
        core_principles=principles,
        set_level_quality_checks=CHAPTER_SET_QUALITY_CHECKS,
        source_skill="chapter-adaptive-questioning",
        mode="chapter",
    )

ASSESSMENT_DISPLAY_ORDER = (
    "python_foundation_diagnostic",
    "python_tutorial_ch3",
    "python_tutorial_ch4",
    "python_tutorial_ch5",
    "python_tutorial_ch6",
    "python_tutorial_ch7",
    "python_tutorial_ch8",
    "python_tutorial_ch9",
)

ITERATOR_TYPE_SEQUENCES: dict[LearnerLevel, list[QuestionType]] = {
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

ITERATOR_DIFFICULTIES: dict[LearnerLevel, list[int]] = {
    "novice": [1, 1, 1, 2, 2, 2, 2, 2, 3, 3],
    "intermediate": [1, 2, 2, 2, 3, 3, 3, 3, 4, 4],
    "advanced": [2, 2, 3, 3, 3, 4, 4, 4, 5, 5],
}

GENERIC_TYPE_SEQUENCES: dict[LearnerLevel, tuple[QuestionType, ...]] = {
    "novice": (
        "multiple_choice",
        "code_blank",
        "output_prediction",
        "multiple_choice",
        "short_explanation",
    ),
    "intermediate": (
        "multiple_choice",
        "code_blank",
        "output_prediction",
        "short_explanation",
        "code_blank",
    ),
    "advanced": (
        "output_prediction",
        "short_explanation",
        "code_blank",
        "multiple_choice",
        "short_explanation",
    ),
}

ITERATOR_COGNITIVE_GOALS = [
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

GENERIC_COGNITIVE_GOALS = (
    "recognize",
    "construct",
    "predict_output",
    "misconception_check",
    "explain",
    "transfer",
    "synthesize",
)

ITERATOR_GOAL_NODE_PREFERENCES = {
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

ITERATOR_PEDAGOGICAL_STRATEGIES = {
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

GENERIC_PEDAGOGICAL_STRATEGIES = {
    "recognize": "concept_discrimination",
    "construct": "generation_effect",
    "predict_output": "output_prediction",
    "misconception_check": "error_diagnosis",
    "explain": "protocol_explanation",
    "transfer": "transfer_practice",
    "synthesize": "mixed_synthesis",
}

ITERATOR_PROMPT_BRIEFS = {
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


def is_supported_assessment_module(module_id: str) -> bool:
    return module_id in ASSESSMENT_SPECS


def list_assessment_options() -> list[dict]:
    return [
        {
            "module_id": spec.module_id,
            "title": spec.title,
            "target_question_count": spec.target_question_count,
            "mode": spec.mode,
        }
        for spec in (ASSESSMENT_SPECS[module_id] for module_id in ASSESSMENT_DISPLAY_ORDER)
    ]


def assessment_spec(module_id: str) -> AssessmentSpec:
    try:
        return ASSESSMENT_SPECS[module_id]
    except KeyError as error:
        raise ValueError(f"Unsupported assessment module: {module_id}") from error


class ChapterQuestioningService:
    def __init__(self, database: Session) -> None:
        self.database = database
        self.question_repository = QuestionRepository(database)
        self.session_repository = SessionRepository(database)

    def create_question_set_for_session(
        self,
        session: LearningSession,
        assessment_id: str = DEFAULT_ASSESSMENT_ID,
    ) -> ChapterQuestionSet:
        existing = self.session_repository.get_chapter_question_set(session.id)
        if existing is not None:
            return existing

        plan = self.generate_plan(session.learner_id, assessment_id)
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
        assessment_id: str = DEFAULT_ASSESSMENT_ID,
    ) -> ChapterQuestionSetPlan:
        spec = assessment_spec(assessment_id)
        nodes = list(self.question_repository.list_knowledge_nodes())
        node_by_id = {node.id: node for node in nodes}
        target_nodes = [node_by_id[node_id] for node_id in spec.node_ids if node_id in node_by_id]
        if not target_nodes:
            raise ValueError(f"Assessment has no seeded knowledge nodes: {assessment_id}")
        if spec.mode == "foundation":
            rotation = self._foundation_rotation_offset(
                learner_id,
                spec.module_id,
                len(target_nodes),
            )
            target_nodes = [*target_nodes[rotation:], *target_nodes[:rotation]]

        error_types = list(self.question_repository.list_error_types())
        learner_nodes = self.question_repository.list_personal_knowledge(learner_id)
        learner_errors = self.question_repository.list_personal_errors(learner_id)
        mastery_by_node = {item.knowledge_node_id: item.mastery for item in learner_nodes}
        average_mastery = self._average_mastery(target_nodes, mastery_by_node)
        level = self._infer_level(average_mastery)
        active_errors = self._active_errors_for_spec(
            spec,
            error_types,
            learner_errors,
        )

        if spec.mode == "iterator":
            items = self._iterator_items(
                spec,
                target_nodes,
                error_types,
                mastery_by_node,
                active_errors,
                level,
            )
        else:
            items = self._generic_items(
                spec,
                target_nodes,
                error_types,
                active_errors,
                level,
            )

        return ChapterQuestionSetPlan(
            chapter_id=spec.module_id,
            chapter_title=spec.title,
            question_count=spec.target_question_count,
            learner_level=level,
            average_mastery=average_mastery,
            active_error_priorities=active_errors[:5],
            core_principles=list(spec.core_principles),
            questions=items,
            set_level_quality_checks=list(spec.set_level_quality_checks),
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
        )

    def generation_inputs_for_slot(
        self,
        session: LearningSession,
        slot: int,
        recent_questions: Sequence[Question] = (),
        assessment_id: str | None = None,
    ) -> tuple[dict, CandidateConstraints]:
        record = self.create_question_set_for_session(
            session,
            assessment_id or DEFAULT_ASSESSMENT_ID,
        )
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
        return completed_question_count + 1

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

    def _foundation_rotation_offset(
        self,
        learner_id: str,
        module_id: str,
        node_count: int,
    ) -> int:
        if node_count <= 1:
            return 0
        existing_count = self.database.scalar(
            select(func.count())
            .select_from(ChapterQuestionSet)
            .where(
                ChapterQuestionSet.learner_id == learner_id,
                ChapterQuestionSet.chapter_id == module_id,
            )
        )
        return int(existing_count or 0) % node_count

    def _iterator_items(
        self,
        spec: AssessmentSpec,
        nodes: Sequence[object],
        error_types: Sequence[ErrorType],
        mastery_by_node: dict[str, float],
        active_errors: Sequence[ActiveErrorPriority],
        level: LearnerLevel,
    ) -> list[ChapterQuestionBlueprintItem]:
        items: list[ChapterQuestionBlueprintItem] = []
        for index, goal in enumerate(ITERATOR_COGNITIVE_GOALS):
            target_nodes = self._choose_iterator_nodes_for_goal(
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
                    question_type=ITERATOR_TYPE_SEQUENCES[level][index],
                    difficulty=ITERATOR_DIFFICULTIES[level][index],
                    cognitive_goal=goal,
                    target_knowledge_node_ids=target_nodes,
                    target_error_ids=target_errors,
                    pedagogical_strategy=ITERATOR_PEDAGOGICAL_STRATEGIES[goal],
                    prompt_brief=ITERATOR_PROMPT_BRIEFS[goal],
                    quality_checks=[
                        *QUESTION_QUALITY_CHECKS,
                        f"题目必须限定在 {spec.title} 的知识点范围。",
                    ],
                )
            )
        return items

    def _generic_items(
        self,
        spec: AssessmentSpec,
        nodes: Sequence[object],
        error_types: Sequence[ErrorType],
        active_errors: Sequence[ActiveErrorPriority],
        level: LearnerLevel,
    ) -> list[ChapterQuestionBlueprintItem]:
        node_by_id = {node.id: node for node in nodes}
        ordered_node_ids = [node.id for node in nodes]
        question_types = GENERIC_TYPE_SEQUENCES[level]
        items: list[ChapterQuestionBlueprintItem] = []

        for index in range(spec.target_question_count):
            node_id = ordered_node_ids[index % len(ordered_node_ids)]
            node = node_by_id[node_id]
            goal = GENERIC_COGNITIVE_GOALS[index % len(GENERIC_COGNITIVE_GOALS)]
            question_type = question_types[index % len(question_types)]
            target_errors = self._choose_errors_for_nodes(
                [node_id],
                error_types,
                active_errors,
            )
            items.append(
                ChapterQuestionBlueprintItem(
                    slot=index + 1,
                    question_type=question_type,
                    difficulty=self._generic_difficulty(node.difficulty, level, index),
                    cognitive_goal=goal,
                    target_knowledge_node_ids=[node_id],
                    target_error_ids=target_errors,
                    pedagogical_strategy=GENERIC_PEDAGOGICAL_STRATEGIES[goal],
                    prompt_brief=(
                        f"围绕《{spec.title}》中的“{node.name}”出题："
                        f"{node.learning_objective}"
                    ),
                    quality_checks=[
                        *QUESTION_QUALITY_CHECKS,
                        f"题目必须限定在 {spec.title} 的知识点范围。",
                    ],
                )
            )
        return items

    @staticmethod
    def _generic_difficulty(
        node_difficulty: int,
        level: LearnerLevel,
        index: int,
    ) -> int:
        if level == "novice":
            return min(3, max(1, node_difficulty))
        if level == "intermediate":
            return min(4, max(1, node_difficulty + (1 if index % 5 >= 3 else 0)))
        return min(5, max(2, node_difficulty + (1 if index % 5 >= 2 else 0)))

    def _choose_iterator_nodes_for_goal(
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
            for node_id in ITERATOR_GOAL_NODE_PREFERENCES[goal]
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
    def _active_errors_for_spec(
        spec: AssessmentSpec,
        error_types: Sequence[ErrorType],
        learner_errors: Sequence[object],
    ) -> list[ActiveErrorPriority]:
        node_ids = set(spec.node_ids)
        error_type_by_id = {item.id: item for item in error_types}
        active_errors = [
            ActiveErrorPriority(
                error_id=item.error_type_id,
                severity=item.severity,
                status=item.status,
            )
            for item in learner_errors
            if item.status in {"new", "active", "improving", "relapsed"}
            and item.severity > 0
            and error_type_by_id.get(item.error_type_id) is not None
            and node_ids.intersection(
                error_type_by_id[item.error_type_id].related_knowledge_nodes
            )
        ]
        active_errors.sort(key=lambda item: item.severity, reverse=True)
        return active_errors

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
