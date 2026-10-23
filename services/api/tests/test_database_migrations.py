"""Migration checks run without a model API or access to the application's database."""

import os
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.models.base import Base
from app.models import entities  # noqa: F401

API_ROOT = Path(__file__).resolve().parents[1]


def migration_config(connection) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.attributes["connection"] = connection
    return config


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.directory.name}/migration.db")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.directory.cleanup()

    def test_complete_upgrade_matches_models_and_round_trips(self) -> None:
        with self.engine.connect() as connection:
            config = migration_config(connection)
            command.upgrade(config, "head")
            self.assertEqual(connection.scalar(text("SELECT version_num FROM alembic_version")), "0004")
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            self.assertEqual(differences, [])
            self.assertIn("assessment_evidence", inspect(connection).get_table_names())
            command.downgrade(config, "0002")
            self.assertNotIn("assessment_evidence", inspect(connection).get_table_names())
            command.upgrade(config, "head")
            self.assertIn("bank_question_revisions", inspect(connection).get_table_names())
            command.downgrade(config, "base")
            self.assertEqual(inspect(connection).get_table_names(), ["alembic_version"])

    def test_knowledge_provenance_upgrade_preserves_progress_and_existing_scope(self) -> None:
        with self.engine.connect() as connection:
            config = migration_config(connection)
            command.upgrade(config, "0003")
            connection.execute(text(
                "INSERT INTO curriculum_chapters (id, course_id, title, sort_order) "
                "VALUES ('chapter', 'python', 'Existing chapter', 1)"
            ))
            connection.execute(text(
                "INSERT INTO learners (id, display_name, created_at) "
                "VALUES ('learner', 'Learner', CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO knowledge_nodes "
                "(id, chapter_id, name, description, difficulty, learning_objective, created_at) "
                "VALUES ('node', 'chapter', 'Existing node', 'Description', 1, 'Objective', "
                "CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO learner_knowledge_nodes "
                "(id, learner_id, knowledge_node_id, mastery, status, attempt_count, "
                "positive_evidence_count, negative_evidence_count, evaluated_question_count, "
                "correct_question_count, score_policy_version, updated_at) "
                "VALUES ('state', 'learner', 'node', 0.85, 'mastered', 4, 3, 1, 20, 17, "
                "'correct_over_max_20_v1', CURRENT_TIMESTAMP)"
            ))
            connection.commit()

            command.upgrade(config, "head")
            node = connection.execute(text(
                "SELECT reference_url, reference_section, is_supplementary, runtime_enabled "
                "FROM knowledge_nodes WHERE id='node'"
            )).mappings().one()
            self.assertIsNone(node["reference_url"])
            self.assertIsNone(node["reference_section"])
            self.assertFalse(node["is_supplementary"])
            self.assertTrue(node["runtime_enabled"])
            self.assertIsNone(connection.scalar(text(
                "SELECT reference_url FROM curriculum_chapters WHERE id='chapter'"
            )))
            connection.execute(text(
                "UPDATE knowledge_nodes SET reference_url=:url, reference_section='4.1', "
                "is_supplementary=true, runtime_enabled=false WHERE id='node'"
            ), {"url": "https://docs.python.org/3/tutorial/controlflow.html"})
            connection.execute(text(
                "UPDATE curriculum_chapters SET reference_url=:url WHERE id='chapter'"
            ), {"url": "https://docs.python.org/3/tutorial/"})
            connection.commit()
            command.upgrade(config, "head")
            self.assertFalse(connection.scalar(text(
                "SELECT runtime_enabled FROM knowledge_nodes WHERE id='node'"
            )))

            command.downgrade(config, "0003")
            self.assertNotIn("runtime_enabled", {
                column["name"] for column in inspect(connection).get_columns("knowledge_nodes")
            })
            self.assertNotIn("reference_url", {
                column["name"] for column in inspect(connection).get_columns("curriculum_chapters")
            })
            self.assertEqual(connection.scalar(text(
                "SELECT name FROM knowledge_nodes WHERE id='node'"
            )), "Existing node")
            command.upgrade(config, "head")
            progress = connection.execute(text(
                "SELECT mastery, status, evaluated_question_count, correct_question_count, "
                "attempt_count FROM learner_knowledge_nodes WHERE id='state'"
            )).mappings().one()
            self.assertAlmostEqual(progress["mastery"], 0.85)
            self.assertEqual(progress["status"], "mastered")
            self.assertEqual(progress["evaluated_question_count"], 20)
            self.assertEqual(progress["correct_question_count"], 17)
            self.assertEqual(progress["attempt_count"], 4)

    def test_knowledge_provenance_migration_compiles_for_mysql_and_postgresql(self) -> None:
        script = ScriptDirectory.from_config(migration_config(None))
        migration = script.get_revision("0004").module
        for dialect_name in ("mysql", "postgresql"):
            with self.subTest(dialect=dialect_name):
                output = StringIO()
                context = MigrationContext.configure(
                    dialect_name=dialect_name,
                    opts={"as_sql": True, "output_buffer": output},
                )
                with Operations.context(context):
                    migration.upgrade()
                    migration.downgrade()
                statements = output.getvalue()
                self.assertIn("runtime_enabled", statements)
                self.assertIn("is_supplementary", statements)
                self.assertIn("reference_section", statements)
                self.assertIn("DROP COLUMN", statements)
                if dialect_name == "postgresql":
                    self.assertIn("BOOLEAN DEFAULT true NOT NULL", statements)
                else:
                    self.assertIn("BOOL NOT NULL DEFAULT true", statements)

    def test_legacy_profile_is_preserved_without_inventing_answer_counts(self) -> None:
        with self.engine.connect() as connection:
            config = migration_config(connection)
            command.upgrade(config, "0002")
            connection.execute(
                text(
                    "INSERT INTO learners (id, display_name, created_at) "
                    "VALUES ('legacy-user', 'Legacy', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_nodes "
                    "(id, name, description, difficulty, learning_objective, created_at) "
                    "VALUES ('legacy-node', 'Node', 'Description', 1, 'Objective', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO learner_knowledge_nodes "
                    "(id, learner_id, knowledge_node_id, mastery, status, attempt_count, "
                    "positive_evidence_count, negative_evidence_count, updated_at) "
                    "VALUES ('legacy-state', 'legacy-user', 'legacy-node', 0.42, 'weak', 7, "
                    "4, 2, CURRENT_TIMESTAMP)"
                )
            )
            connection.commit()
            command.upgrade(config, "head")
            row = (
                connection.execute(
                    text("SELECT * FROM learner_knowledge_nodes WHERE id='legacy-state'")
                )
                .mappings()
                .one()
            )
            self.assertAlmostEqual(row["legacy_mastery"], 0.42)
            self.assertEqual(row["legacy_status"], "weak")
            self.assertEqual(row["mastery"], 0)
            self.assertEqual(row["status"], "not_started")
            self.assertEqual(row["evaluated_question_count"], 0)
            self.assertEqual(row["correct_question_count"], 0)
            self.assertEqual(row["attempt_count"], 7)
            self.assertEqual(row["positive_evidence_count"], 4)
            connection.execute(
                text(
                    "UPDATE learner_knowledge_nodes SET evaluated_question_count=1, "
                    "correct_question_count=1, mastery=0.05 WHERE id='legacy-state'"
                )
            )
            connection.commit()
            command.upgrade(config, "head")
            self.assertEqual(
                connection.scalar(
                    text(
                        "SELECT evaluated_question_count FROM learner_knowledge_nodes "
                        "WHERE id='legacy-state'"
                    )
                ),
                1,
            )
            command.downgrade(config, "0002")
            restored = connection.execute(
                text("SELECT mastery, status FROM learner_knowledge_nodes WHERE id='legacy-state'")
            ).one()
            self.assertAlmostEqual(restored.mastery, 0.42)
            self.assertEqual(restored.status, "weak")

    def test_migrated_schema_enforces_foreign_keys(self) -> None:
        with self.engine.connect() as connection:
            command.upgrade(migration_config(connection), "head")
            connection.commit()
            connection.execute(text("PRAGMA foreign_keys=ON"))
            with self.assertRaises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO bank_questions "
                        "(id, source_document_id, question_number, created_at) "
                        "VALUES ('orphan', 'missing-document', '1', CURRENT_TIMESTAMP)"
                    )
                )

    def test_mysql_ddl_retains_microseconds_and_large_text(self) -> None:
        dialect = mysql.dialect()
        for table in Base.metadata.sorted_tables:
            statement = str(CreateTable(table).compile(dialect=dialect))
            self.assertTrue(statement)
            for constraint in table.constraints:
                if constraint.name is not None:
                    self.assertLessEqual(len(str(constraint.name)), 64)
        messages = str(
            CreateTable(Base.metadata.tables["conversation_messages"]).compile(dialect=dialect)
        )
        self.assertIn("DATETIME(6)", messages)
        self.assertIn("LONGTEXT", messages)
        mastery_type = Base.metadata.tables["learner_knowledge_nodes"].c.mastery.type
        self.assertFalse(mastery_type.dialect_impl(dialect).asdecimal)

    def test_url_encoded_password_is_not_config_interpolation(self) -> None:
        with self.engine.connect() as connection:
            config = migration_config(connection)
            encoded_url = "mysql+pymysql://example:encoded%40value@localhost/example"
            config.attributes["database_url"] = encoded_url
            command.upgrade(config, "head")
            self.assertEqual(config.get_main_option("sqlalchemy.url"), encoded_url)


@unittest.skipUnless(os.getenv("TEST_MYSQL_URL"), "TEST_MYSQL_URL is not configured")
class MySQLMigrationTests(unittest.TestCase):
    """Always create a disposable schema; never migrate the URL's existing schema."""

    def test_real_mysql_upgrade_constraints_and_downgrade(self) -> None:
        supplied_url = make_url(os.environ["TEST_MYSQL_URL"])
        if supplied_url.drivername != "mysql+pymysql":
            self.fail("TEST_MYSQL_URL must use mysql+pymysql")
        database_name = "pycoach_test_" + uuid4().hex
        admin = create_engine(supplied_url.set(database=None))
        database = None
        try:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 "
                        "COLLATE utf8mb4_unicode_ci"
                    )
                )
            database = create_engine(supplied_url.set(database=database_name))
            with database.connect() as connection:
                config = migration_config(connection)
                command.upgrade(config, "head")
                self.assertIn("assessment_evidence", inspect(connection).get_table_names())
                columns = {
                    c["name"]: c for c in inspect(connection).get_columns("conversation_messages")
                }
                self.assertEqual(columns["created_at"]["type"].fsp, 6)
                self.assertIsInstance(columns["content_markdown"]["type"], mysql.LONGTEXT)
                knowledge_columns = {
                    c["name"]: c
                    for c in inspect(connection).get_columns("learner_knowledge_nodes")
                }
                self.assertIsInstance(knowledge_columns["mastery"]["type"], mysql.DOUBLE)
                self.assertEqual(
                    compare_metadata(MigrationContext.configure(connection), Base.metadata), []
                )
                command.downgrade(config, "0002")
                command.upgrade(config, "head")
                command.downgrade(config, "base")
                self.assertEqual(inspect(connection).get_table_names(), ["alembic_version"])
        finally:
            if database is not None:
                database.dispose()
            with admin.begin() as connection:
                connection.execute(text(f"DROP DATABASE IF EXISTS `{database_name}`"))
            admin.dispose()
