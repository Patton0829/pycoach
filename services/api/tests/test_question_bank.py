import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.entities import (
    BankQuestion,
    KnowledgeNode,
    Learner,
    LearningRound,
    LearningSession,
    Question,
    QuestionKnowledgeMapping,
    SourceDocument,
)
from app.schemas.question_bank import (
    BankQuestionRevisionInput,
    QuestionBankImport,
    QuestionBankQuery,
    SourceDocumentInput,
    import_from_exam_example,
)
from app.services.question_bank_service import (
    ImmutableQuestionRevisionError,
    QuestionBankError,
    QuestionBankService,
)


def source_document(**overrides) -> SourceDocumentInput:
    return SourceDocumentInput.model_validate(
        {
            "title": "Iterator source document fixture",
            "document_type": "sample_exam",
            "exam_year": None,
            "file_path": "fixtures/exam.pdf",
            "sha256": "a" * 64,
            "page_count": 3,
            **overrides,
        }
    )


def question_definition(**overrides) -> BankQuestionRevisionInput:
    return BankQuestionRevisionInput.model_validate(
        {
            "bank_question_id": "fixture-iterator-q1",
            "question_number": "1",
            "revision": 1,
            "question_type": "output_prediction",
            "difficulty": 2,
            "difficulty_reason": "Trace an iterator's position.",
            "cognitive_goal": "trace",
            "original_content": {
                "stem": "Predict the final expression.",
                "code": "it = iter([1, 2])\nnext(it)\nnext(it)",
            },
            "student_content": {
                "markdown": "Predict the final expression.\n\n"
                "```python\nit = iter([1, 2])\nnext(it)\nnext(it)\n```"
            },
            "critic_content": {
                "learning_objective": "Trace iterator state.",
                "reference_answer": "2",
                "acceptable_answers": ["2"],
                "grading_rubric": {"correct": "The final expression yields 2."},
                "expected_reasoning": "The first call consumes 1; the second yields 2.",
            },
            "source_locations": {
                "question_pdf_pages": [1, 2],
                "answer_pdf_pages": [3],
            },
            "answer_provenance": {
                "origin": "provided_pdf_reference_answers",
                "source_text": "1. 2",
                "explanation_origin": "project_annotation",
            },
            "topic_tags": ["iterator state"],
            "knowledge_targets": [
                {
                    "knowledge_node_id": "python.iterator.state",
                    "role": "assessed",
                    "is_primary": True,
                    "assessment_criterion": "Tracks the consumed first value.",
                },
                {
                    "knowledge_node_id": "python.iterator.iter",
                    "role": "prerequisite",
                },
            ],
            "review_status": "approved",
            **overrides,
        }
    )


class QuestionBankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.database = sessionmaker(bind=self.engine, expire_on_commit=False)()
        for node_id in (
            "python.iterator.state",
            "python.iterator.iter",
            "python.iterator.next",
            "python.iterator.exhaustion",
            "python.stop_iteration",
            "python.other",
        ):
            self.database.add(
                KnowledgeNode(
                    id=node_id,
                    name=node_id,
                    description="fixture",
                    difficulty=2,
                    learning_objective="fixture",
                )
            )
        self.database.flush()
        self.service = QuestionBankService(self.database)
        self.document = self.service.register_document(source_document())

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def test_import_is_idempotent_and_preserves_source_and_student_boundary(self) -> None:
        duplicate = self.service.register_document(source_document())
        self.assertEqual(duplicate.id, self.document.id)
        first = self.service.create_revision(self.document.id, question_definition())
        second = self.service.create_revision(self.document.id, question_definition())
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.source_locations_json["question_pdf_pages"], [1, 2])
        self.assertEqual(
            first.original_content_json["code"], question_definition().original_content.code
        )
        candidates = self.service.find_candidates(QuestionBankQuery())
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0].model_dump()
        self.assertNotIn("critic_content", candidate)
        self.assertNotIn("reference_answer", candidate)
        self.assertEqual(candidates[0].knowledge_node_ids, ["python.iterator.state"])
        self.assertEqual(self.database.scalar(select(func.count()).select_from(SourceDocument)), 1)
        self.assertEqual(self.database.scalar(select(func.count()).select_from(BankQuestion)), 1)

    def test_revisions_are_immutable_and_queries_use_latest_approved(self) -> None:
        first = self.service.create_revision(self.document.id, question_definition())
        changed = question_definition(difficulty=3)
        with self.assertRaises(ImmutableQuestionRevisionError):
            self.service.create_revision(self.document.id, changed)
        second = self.service.create_revision(
            self.document.id, question_definition(revision=2, difficulty=3, review_status="draft")
        )
        self.assertEqual(self.service.find_candidates(QuestionBankQuery())[0].revision_id, first.id)
        self.service.review_revision(second.id, "approved")
        self.assertEqual(
            self.service.find_candidates(QuestionBankQuery())[0].revision_id, second.id
        )
        self.assertEqual(first.difficulty, 2)
        self.assertEqual(second.difficulty, 3)

    def test_stable_identity_cannot_be_reassigned_or_duplicated(self) -> None:
        self.service.create_revision(self.document.id, question_definition())
        with self.assertRaises(QuestionBankError):
            self.service.create_revision(
                self.document.id,
                question_definition(bank_question_id="different-id-for-same-source-question"),
            )
        with self.assertRaises(QuestionBankError):
            self.service.create_revision(self.document.id, question_definition(question_number="2"))

    def test_candidate_filters_do_not_match_prerequisites_or_repeat_sources(self) -> None:
        revision = self.service.create_revision(self.document.id, question_definition())
        self.assertEqual(
            self.service.find_candidates(
                QuestionBankQuery(knowledge_node_ids=["python.iterator.iter"])
            ),
            [],
        )
        self.assertEqual(
            self.service.find_candidates(
                QuestionBankQuery(exclude_bank_question_ids=[revision.bank_question_id])
            ),
            [],
        )
        self.assertEqual(self.service.find_candidates(QuestionBankQuery(difficulty_min=3)), [])
        self.assertEqual(
            self.service.find_candidates(QuestionBankQuery(question_types=["code_blank"])), []
        )
        self.assertEqual(
            self.service.find_candidates(
                QuestionBankQuery(allowed_knowledge_node_ids=["python.iterator.next"])
            ),
            [],
        )
        self.assertEqual(
            len(
                self.service.find_candidates(
                    QuestionBankQuery(knowledge_node_ids=["python.iterator.state"])
                )
            ),
            1,
        )

    def test_validates_foreign_keys_and_page_bounds_before_writing(self) -> None:
        for field, value in (
            (
                "knowledge_targets",
                [
                    {
                        "knowledge_node_id": "unknown",
                        "is_primary": True,
                        "assessment_criterion": "fixture",
                    }
                ],
            ),
            ("target_error_ids", ["unknown"]),
            ("source_locations", {"question_pdf_pages": [4]}),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(QuestionBankError):
                self.service.create_revision(
                    self.document.id, question_definition(**{field: value})
                )
        self.assertEqual(self.database.scalar(select(func.count()).select_from(BankQuestion)), 0)

    def test_content_review_does_not_activate_an_out_of_scope_question(self) -> None:
        revision = self.service.create_revision(self.document.id, question_definition(
            knowledge_targets=[{
                "knowledge_node_id": "python.other", "is_primary": True,
                "assessment_criterion": "Reviewed source knowledge outside the active lesson.",
            }],
        ))
        self.assertEqual(revision.review_status, "approved")
        self.assertEqual(self.service.find_candidates(QuestionBankQuery()), [])
        with self.assertRaisesRegex(QuestionBankError, "outside the active"):
            self.service.materialize(revision.id)

    def test_draft_unmapped_item_can_be_archived_but_cannot_be_materialized(self) -> None:
        revision = self.service.create_revision(
            self.document.id,
            question_definition(knowledge_targets=[], review_status="draft"),
        )
        self.assertEqual(self.service.find_candidates(QuestionBankQuery()), [])
        with self.assertRaises(QuestionBankError):
            self.service.materialize(revision.id)
        with self.assertRaises(ValidationError):
            self.service.review_revision(revision.id, "approved")

    def test_materialization_uses_runtime_uuid_and_retains_historical_snapshot(self) -> None:
        revision = self.service.create_revision(self.document.id, question_definition())
        self.database.add(Learner(id="learner", display_name="fixture"))
        self.database.flush()
        session = LearningSession(learner_id="learner", status="QUESTION_ACTIVE")
        self.database.add(session)
        self.database.flush()
        learning_round = LearningRound(session_id=session.id, state="QUESTION_ACTIVE")
        self.database.add(learning_round)
        self.database.flush()
        question = self.service.attach_to_round(revision.id, session.id, learning_round.id)
        self.database.commit()
        self.assertNotEqual(question.id, revision.bank_question_id)
        self.assertNotEqual(question.id, revision.id)
        self.assertEqual(question.bank_question_revision_id, revision.id)
        self.assertEqual(learning_round.question_id, question.id)
        self.assertEqual(question.knowledge_node_ids, ["python.iterator.state"])
        self.assertEqual(
            self.service.attach_to_round(revision.id, session.id, learning_round.id).id,
            question.id,
        )
        self.service.create_revision(
            self.document.id,
            question_definition(
                revision=2, difficulty=3, student_content={"markdown": "Revised statement."}
            ),
        )
        stored = self.database.get(Question, question.id)
        self.assertEqual(stored.student_content_json, revision.student_content_json)
        self.assertEqual(stored.difficulty, 2)
        self.assertEqual(self.database.scalar(select(func.count()).select_from(Question)), 1)

    def test_rejects_attaching_to_another_sessions_round(self) -> None:
        revision = self.service.create_revision(self.document.id, question_definition())
        self.database.add(Learner(id="learner", display_name="fixture"))
        self.database.flush()
        session = LearningSession(learner_id="learner", status="QUESTION_ACTIVE")
        other = LearningSession(learner_id="learner", status="QUESTION_ACTIVE")
        self.database.add_all([session, other])
        self.database.flush()
        learning_round = LearningRound(session_id=other.id, state="QUESTION_ACTIVE")
        self.database.add(learning_round)
        self.database.flush()
        with self.assertRaises(QuestionBankError):
            self.service.attach_to_round(revision.id, session.id, learning_round.id)

    def test_schema_rejects_duplicate_targets_unknown_fields_and_invalid_ranges(self) -> None:
        target = question_definition().knowledge_targets[0].model_dump()
        with self.assertRaises(ValidationError):
            question_definition(knowledge_targets=[target, target])
        with self.assertRaises(ValidationError):
            question_definition(internal_leak=True)
        with self.assertRaises(ValidationError):
            QuestionBankQuery(difficulty_min=4, difficulty_max=2)
        with self.assertRaises(ValidationError):
            source_document(sha256="not-a-sha256")

    def test_previously_generated_pdf_example_stays_draft_and_retains_original_output(self) -> None:
        # Use the legacy export shape, without depending on an untracked user PDF.
        raw = {
            "schema_version": "exam-bank-example.v1",
            "source_document": {
                "title": "Sample exam fixture",
                "document_type": "sample_exam",
                "exam_year": None,
                "relative_path": "fixtures/sample.pdf",
                "sha256": "b" * 64,
                "page_count": 3,
            },
            "questions": [],
        }
        for number in range(1, 4):
            definition = question_definition().model_dump(mode="json")
            if number == 2:
                definition["original_content"]["options"] = [
                    {"label": "A", "text": ">>>3/2\n1.50"},
                    {"label": "B", "text": ">>>3/2\n1"},
                    {"label": "C", "text": ">>>3//2\n1"},
                    {"label": "D", "text": ">>>3//2\n1.5"},
                ]
            raw["questions"].append(
                {
                    "question_id": f"legacy-q{number}",
                    "question_type": definition["question_type"],
                    "source": {
                        "question_number": number,
                        "question_pdf_pages": [1, 2] if number == 3 else [1],
                        "stem_pdf_pages": [1],
                        "options_pdf_pages": [2] if number == 3 else [1],
                        "answer_pdf_pages": [3],
                    },
                    "original_content": definition["original_content"],
                    "student_content": definition["student_content"],
                    "critic_content": definition["critic_content"],
                    "answer_provenance": {
                        **definition["answer_provenance"],
                        "correct_option": "C" if number == 2 else None,
                    },
                    "annotations": {
                        "difficulty": 2,
                        "difficulty_reason": "Fixture annotations.",
                        "topic_tags": ["unmapped source topic"],
                    },
                }
            )
        payload = import_from_exam_example(raw)
        self.assertEqual(payload.document.document_type, "sample_exam")
        self.assertIsNone(payload.document.exam_year)
        self.assertEqual(payload.questions[1].original_content.options[0].text, ">>>3/2\n1.50")
        self.assertEqual(payload.questions[2].source_locations.question_pdf_pages, [1, 2])
        self.assertEqual(payload.questions[2].source_locations.stem_pdf_pages, [1])
        self.assertEqual(payload.questions[2].source_locations.options_pdf_pages, [2])
        self.assertEqual(payload.questions[1].answer_provenance.correct_option, "C")
        document = self.service.register_document(payload.document)
        revisions = [self.service.create_revision(document.id, item) for item in payload.questions]
        self.assertTrue(all(revision.review_status == "draft" for revision in revisions))
        self.assertEqual(self.service.find_candidates(QuestionBankQuery()), [])
        self.assertEqual(
            self.database.scalar(select(func.count()).select_from(QuestionKnowledgeMapping)), 0
        )

    def test_cli_import_is_repeatable_and_does_not_publish_draft_questions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pycoach-bank-cli-") as directory:
            directory = Path(directory)
            database_url = f"sqlite+pysqlite:///{directory / 'bank.db'}"
            engine = create_engine(database_url)
            Base.metadata.create_all(engine)
            engine.dispose()
            payload = QuestionBankImport(
                document=source_document(),
                questions=[question_definition(knowledge_targets=[], review_status="draft")],
            )
            input_path = directory / "bank.json"
            input_path.write_text(payload.model_dump_json(), encoding="utf-8")
            environment = {
                **os.environ,
                "DATABASE_URL": database_url,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "LLM_PROVIDER": "mock",
            }

            def command(*arguments):
                result = subprocess.run(
                    [sys.executable, "-m", "app.question_bank_cli", *arguments],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return json.loads(result.stdout)

            first = command("import-json", str(input_path))
            second = command("import-json", str(input_path))
            self.assertEqual(first, second)
            self.assertEqual(first["questions"][0]["review_status"], "draft")
            self.assertEqual(command("query"), [])

    def test_cli_schema_does_not_require_a_database_connection(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.question_bank_cli", "schema"],
            env={
                **os.environ,
                "DATABASE_URL": "intentionally-not-a-database-url",
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "LLM_PROVIDER": "mock",
            },
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["title"], "QuestionBankImport")


if __name__ == "__main__":
    unittest.main()
