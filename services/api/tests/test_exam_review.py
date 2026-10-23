import json
from pathlib import Path
import unittest

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.entities import (
    BankQuestion,
    BankQuestionRevision,
    CurriculumChapter,
    KnowledgeNode,
    QuestionKnowledgeMapping,
    SourceDocument,
)
from app.schemas.question_bank import (
    BankQuestionRevisionInput,
    QuestionBankImport,
    QuestionBankQuery,
    import_from_exam_example,
)
from app.seed import seed_database
from app.services.graph_service import GraphService
from app.services.question_bank_service import QuestionBankError, QuestionBankService
from app.services.question_service import QuestionContextBuilder


ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "python考试真题" / "结构化真题" / "ncre-python-sample"
CURRICULUM = ROOT / "curriculum" / "python_iterator_v1"
FOUNDATION = ROOT / "curriculum" / "python_foundation_v1"
PREVIOUS_EXAMPLE = ROOT / "python考试真题" / "结构化示例" / "前三题.json"


def reviewed_import() -> QuestionBankImport:
    return QuestionBankImport.model_validate_json(
        (CORPUS / "bank_import.reviewed.json").read_text(encoding="utf-8")
    )


class ReviewedExamArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = reviewed_import()
        cls.by_number = {int(item.question_number): item for item in cls.payload.questions}
        original = json.loads((CORPUS / "exam.json").read_text(encoding="utf-8"))
        cls.original_by_number = {
            item["question_number"]: item for item in original["questions"]
        }

    def test_every_original_question_has_specific_reviewed_knowledge_targets(self) -> None:
        self.assertEqual(set(self.by_number), set(range(1, 37)))
        catalog_ids = {node.id for node in self.payload.catalog_knowledge_nodes}
        catalog_ids.update(
            item["id"] for item in json.loads(
                (FOUNDATION / "knowledge_nodes.json").read_text(encoding="utf-8")
            )
        )
        self.assertTrue(catalog_ids)
        for number, question in self.by_number.items():
            with self.subTest(question=number):
                assessed = [target for target in question.knowledge_targets if target.role == "assessed"]
                self.assertIn(len(assessed), (1, 2))
                self.assertEqual(sum(target.is_primary for target in assessed), 1)
                self.assertTrue(all(target.assessment_criterion.strip() for target in assessed))
                self.assertTrue(all(
                    target.knowledge_node_id in catalog_ids
                    for target in question.knowledge_targets
                ))
                self.assertEqual(question.revision, 3 if number in (13, 17) else 2)
                self.assertIn(question.review_status, {"approved", "invalid"})

        # These source defects cannot be resolved merely by choosing an answer.
        for number in (4, 6, 12, 14, 16):
            with self.subTest(invalid_source_question=number):
                self.assertEqual(self.by_number[number].review_status, "invalid")
        self.assertEqual(self.by_number[15].review_status, "approved")

    def test_missing_source_answers_are_filled_with_explicit_project_provenance(self) -> None:
        for number in range(31, 37):
            with self.subTest(question=number):
                original = self.original_by_number[number]
                self.assertIsNone(original["answer"])
                self.assertEqual(original["answer_status"], "not_provided")
                question = self.by_number[number]
                self.assertEqual(question.answer_provenance.origin, "project_annotation")
                self.assertIsNone(question.answer_provenance.source_correct_option)
                self.assertTrue(question.critic_content.reference_answer.strip())
                self.assertTrue(question.critic_content.expected_reasoning.strip())
                self.assertEqual(question.answer_provenance.explanation_origin, "project_annotation")
                self.assertNotIn(
                    question.critic_content.reference_answer,
                    question.student_content.markdown,
                )

    def test_reviewed_break_answer_preserves_conflicting_source_answer(self) -> None:
        question = self.by_number[15]
        self.assertEqual(self.original_by_number[15]["answer"]["correct_option"], "B")
        self.assertEqual(question.answer_provenance.source_correct_option, "B")
        self.assertEqual(question.answer_provenance.correct_option, "C")
        self.assertEqual(question.answer_provenance.origin, "project_annotation")
        self.assertTrue(question.answer_provenance.review_note)
        self.assertEqual(question.critic_content.reference_answer, "C")
        self.assertEqual(
            next(option.text for option in question.original_content.options if option.label == "C"),
            "break",
        )
        self.assertIn("break", question.critic_content.expected_reasoning)
        self.assertIn("continue", question.critic_content.expected_reasoning)
        self.assertTrue(any(
            "docs.python.org" in source
            for source in question.answer_provenance.verification_sources
        ))

    def test_password_and_weight_clarifications_are_visible_without_solutions(self) -> None:
        for number in (33, 36):
            with self.subTest(question=number):
                question = self.by_number[number]
                original = self.original_by_number[number]
                self.assertEqual(question.original_content.stem, original["original_content"]["stem"])
                self.assertTrue(question.answer_provenance.assumptions)
                self.assertNotEqual(question.student_content.markdown, original["student_content"]["markdown"])
                self.assertTrue(question.normalizations)
                self.assertNotIn("参考答案", question.student_content.markdown)
                self.assertNotIn("评分规则", question.student_content.markdown)
        self.assertTrue(any(
            phrase in self.by_number[33].student_content.markdown
            for phrase in ("10 个", "10个", "0～9", "0-9", "0 到 9", "0到9")
        ))
        self.assertTrue(any(
            phrase in self.by_number[36].student_content.markdown
            for phrase in ("当前体重", "初始体重", "初始地球体重", "当前地球体重")
        ))

    def test_catalog_distinguishes_official_tutorial_sections_and_project_supplements(self) -> None:
        chapters = {chapter.id: chapter for chapter in self.payload.catalog_chapters}
        self.assertTrue(chapters)
        supplemental = []
        for node in self.payload.catalog_knowledge_nodes:
            with self.subTest(node=node.id):
                self.assertFalse(node.runtime_enabled)
                self.assertIn(node.chapter_id, chapters)
                if node.is_supplementary:
                    supplemental.append(node)
                else:
                    self.assertTrue(node.reference_section)
                    self.assertTrue(node.reference_url.startswith("https://docs.python.org/3/tutorial/"))
                    self.assertTrue(chapters[node.chapter_id].reference_url.startswith(
                        "https://docs.python.org/3/tutorial/"
                    ))
        self.assertTrue(supplemental)
        ipo_nodes = [node for node in supplemental if "IPO" in node.name]
        self.assertTrue(ipo_nodes, "IPO is a project supplement rather than an invented tutorial section")

    def test_retrieval_exports_separate_invalid_questions_and_internal_answers(self) -> None:
        def read_records(filename: str) -> list[dict]:
            return [
                json.loads(line)
                for line in (CORPUS / filename).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        all_questions = read_records("rag_questions.reviewed.jsonl")
        ready_questions = read_records("rag_questions.reviewed.ready.jsonl")
        internal_answers = read_records("rag_answers.reviewed.internal.jsonl")
        approved_ids = {
            item.bank_question_id for item in self.payload.questions
            if item.review_status == "approved"
        }
        self.assertEqual(len(all_questions), 36)
        self.assertEqual(
            {item["metadata"]["question_id"] for item in all_questions},
            {item.bank_question_id for item in self.payload.questions},
        )
        self.assertEqual(
            {item["metadata"]["question_id"] for item in ready_questions}, approved_ids,
        )
        self.assertEqual(
            {item["metadata"]["question_id"] for item in internal_answers}, approved_ids,
        )
        for record in all_questions:
            metadata = record["metadata"]
            self.assertEqual(metadata["visibility"], "question")
            self.assertFalse(metadata["runtime_curriculum_eligible"])
            self.assertEqual(metadata["retrieval_ready"], metadata["question_id"] in approved_ids)
            for forbidden in (
                "reference_answer", "critic_content", "grading_rubric",
                "correct_option", "source_correct_option", "source_text",
            ):
                self.assertNotIn(forbidden, metadata)
                self.assertNotIn(forbidden, record)
        self.assertTrue(all(
            record["metadata"]["visibility"] == "internal_answer"
            for record in internal_answers
        ))


class ReviewedExamImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.database = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)()
        seed_database(self.database, CURRICULUM)
        seed_database(self.database, FOUNDATION)
        self.service = QuestionBankService(self.database)
        self.payload = reviewed_import()

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _import_reviewed(self) -> list[BankQuestionRevision]:
        self.service.register_catalog(
            self.payload.catalog_chapters, self.payload.catalog_knowledge_nodes,
        )
        document = self.service.register_document(self.payload.document)
        revisions = [
            self.service.create_revision(document.id, question)
            for question in self.payload.questions
        ]
        self.database.commit()
        return revisions

    def _counts(self) -> dict[str, int]:
        return {
            model.__tablename__: self.database.scalar(select(func.count()).select_from(model))
            for model in (
                CurriculumChapter, KnowledgeNode, SourceDocument,
                BankQuestion, BankQuestionRevision, QuestionKnowledgeMapping,
            )
        }

    def test_reviewed_import_is_idempotent_and_preserves_original_first_revision(self) -> None:
        previous = import_from_exam_example(json.loads(PREVIOUS_EXAMPLE.read_text(encoding="utf-8")))
        document = self.service.register_document(previous.document)
        original = self.service.create_revision(document.id, previous.questions[0])
        self.database.commit()
        old_revision_id = original.id
        old_critic_content = json.loads(json.dumps(original.critic_content_json))
        old_student_content = json.loads(json.dumps(original.student_content_json))

        revisions = self._import_reviewed()
        first_counts = self._counts()
        repeated = self._import_reviewed()

        self.assertEqual([revision.id for revision in revisions], [revision.id for revision in repeated])
        self.assertEqual(self._counts(), first_counts)
        self.assertEqual(first_counts["bank_questions"], 36)
        self.assertEqual(first_counts["bank_question_revisions"], 37)
        self.assertEqual(first_counts["source_documents"], 1)
        retained = self.database.get(BankQuestionRevision, old_revision_id)
        self.assertEqual(retained.revision, 1)
        self.assertEqual(retained.review_status, "draft")
        self.assertEqual(retained.critic_content_json, old_critic_content)
        self.assertEqual(retained.student_content_json, old_student_content)
        new_first = next(
            revision for revision in revisions
            if revision.bank_question_id == previous.questions[0].bank_question_id
        )
        self.assertEqual(new_first.revision, 2)
        self.assertNotEqual(new_first.id, retained.id)

    def test_imported_exam_catalog_does_not_expand_current_student_curriculum(self) -> None:
        before_context = QuestionContextBuilder(self.database).build("demo_user")
        before_graph = GraphService(self.database).get_knowledge_graph("demo_user")
        before_ids = {node["id"] for node in before_context.global_knowledge_graph["nodes"]}
        before_graph_ids = {node.node_id for node in before_graph.nodes}

        self._import_reviewed()
        catalog_ids = {node.id for node in self.payload.catalog_knowledge_nodes}
        context = QuestionContextBuilder(self.database).build("demo_user")
        graph = GraphService(self.database).get_knowledge_graph("demo_user")

        self.assertEqual(
            {node["id"] for node in context.global_knowledge_graph["nodes"]}, before_ids,
        )
        self.assertEqual({node.node_id for node in graph.nodes}, before_graph_ids)
        self.assertTrue(catalog_ids.isdisjoint(before_ids))
        self.assertTrue(catalog_ids.isdisjoint(
            item.node_id for item in context.personal_knowledge_graph
        ))
        self.assertTrue(all(
            not self.database.get(KnowledgeNode, node_id).runtime_enabled
            for node_id in catalog_ids
        ))

    def test_content_approval_does_not_enable_out_of_scope_runtime_questions(self) -> None:
        revisions = self._import_reviewed()
        self.assertTrue(any(revision.review_status == "approved" for revision in revisions))
        self.assertEqual(self.service.find_candidates(QuestionBankQuery()), [])
        for revision in revisions:
            with self.subTest(question=revision.bank_question_id):
                with self.assertRaises(QuestionBankError):
                    self.service.materialize(revision.id)

    def test_catalog_reimport_cannot_overwrite_an_existing_knowledge_definition(self) -> None:
        self._import_reviewed()
        original = self.payload.catalog_knowledge_nodes[0]
        changed = original.model_copy(update={"name": "Conflicting replacement name"})
        with self.assertRaises(QuestionBankError):
            self.service.register_catalog([], [changed])
        self.database.rollback()
        retained = self.database.get(KnowledgeNode, original.id)
        self.assertEqual(retained.name, original.name)
        self.assertFalse(retained.runtime_enabled)

    def test_disabling_an_iterator_node_blocks_retrieval_and_materialization(self) -> None:
        document = self.service.register_document(self.payload.document)
        definition = BankQuestionRevisionInput.model_validate({
            "bank_question_id": "fixture-reviewed-disabled-iterator",
            "question_number": "iterator-fixture",
            "question_type": "output_prediction",
            "difficulty": 1,
            "difficulty_reason": "Track a single next() call.",
            "cognitive_goal": "trace",
            "original_content": {
                "stem": "What value does next(it) return?",
                "code": "it = iter([1, 2])\nnext(it)",
            },
            "student_content": {
                "markdown": "What value does next(it) return?\n\n"
                "```python\nit = iter([1, 2])\nnext(it)\n```",
            },
            "critic_content": {
                "learning_objective": "Identify the next iterator value.",
                "reference_answer": "1",
                "acceptable_answers": ["1"],
                "grading_rubric": {"correct": "The first item is 1."},
                "expected_reasoning": "The first next() call returns the first item.",
            },
            "source_locations": {"question_pdf_pages": [1]},
            "answer_provenance": {"origin": "project_annotation"},
            "knowledge_targets": [{
                "knowledge_node_id": "python.iterator.next",
                "role": "assessed",
                "is_primary": True,
                "assessment_criterion": "Identifies that next() obtains the next value.",
            }],
            "review_status": "approved",
        })
        revision = self.service.create_revision(document.id, definition)
        self.database.commit()
        self.assertEqual(len(self.service.find_candidates(QuestionBankQuery())), 1)
        self.assertEqual(self.service.materialize(revision.id).difficulty, 1)

        node = self.database.get(KnowledgeNode, "python.iterator.next")
        node.runtime_enabled = False
        self.database.commit()

        self.assertEqual(self.service.find_candidates(QuestionBankQuery()), [])
        with self.assertRaises(QuestionBankError):
            self.service.materialize(revision.id)


if __name__ == "__main__":
    unittest.main()
