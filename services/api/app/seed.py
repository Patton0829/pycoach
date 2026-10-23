import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Type, TypeVar

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.entities import (
    CurriculumChapter,
    ErrorType,
    KnowledgeEdge,
    KnowledgeNode,
    Learner,
    LearnerErrorNode,
    LearnerKnowledgeNode,
)
from app.schemas.base import StrictModel
from app.schemas.seed import (
    ErrorTypeSeed,
    KnowledgeEdgeSeed,
    KnowledgeNodeSeed,
    SeedResult,
)

SeedModel = TypeVar("SeedModel", bound=BaseModel)


class TutorialChapterSeed(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    course_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    sort_order: int
    reference_url: str | None = Field(default=None, max_length=500)


class TutorialNodeMetadata(StrictModel):
    chapter_id: str = Field(min_length=1, max_length=120)
    reference_url: str = Field(min_length=1, max_length=500)
    reference_section: str = Field(min_length=1, max_length=40)
    is_supplementary: bool = False


class TutorialCatalog(StrictModel):
    source_index_url: str
    chapters: list[TutorialChapterSeed]
    node_metadata: dict[str, TutorialNodeMetadata]


DEMO_KNOWLEDGE_STATE: Dict[str, tuple[float, str]] = {
    "python.list": (0.0, "not_started"),
    "python.iterable": (0.0, "not_started"),
    "python.iterator": (0.0, "not_started"),
    "python.iterator.iter": (0.0, "not_started"),
    "python.iterator.next": (0.0, "not_started"),
}

DEMO_ERROR_STATE: Dict[str, tuple[float, str]] = {
    "iter_vs_next": (0.45, "active"),
}


def load_seed_list(
    curriculum_dir: Path,
    filename: str,
    schema: Type[SeedModel],
) -> list[SeedModel]:
    path = curriculum_dir / filename
    with path.open(encoding="utf-8") as seed_file:
        raw_data = json.load(seed_file)
    return TypeAdapter(list[schema]).validate_python(raw_data)


def load_tutorial_catalog(curriculum_dir: Path) -> TutorialCatalog | None:
    """Load official section references for project-defined knowledge granularity."""
    catalog_path = curriculum_dir.parent / "python_tutorial_catalog.json"
    if not catalog_path.is_file():
        return None
    return TutorialCatalog.model_validate_json(catalog_path.read_text(encoding="utf-8"))


def seed_tutorial_catalog(
    database: Session, curriculum_dir: Path,
) -> dict[str, TutorialNodeMetadata]:
    catalog = load_tutorial_catalog(curriculum_dir)
    if catalog is None:
        return {}
    for definition in catalog.chapters:
        chapter = database.get(CurriculumChapter, definition.id)
        values = definition.model_dump(exclude={"id"})
        if chapter is None:
            database.add(CurriculumChapter(id=definition.id, **values))
        else:
            for field, value in values.items():
                setattr(chapter, field, value)
    database.flush()
    return catalog.node_metadata


def seed_database(database: Session, curriculum_dir: Path) -> SeedResult:
    knowledge_nodes = load_seed_list(
        curriculum_dir,
        "knowledge_nodes.json",
        KnowledgeNodeSeed,
    )
    knowledge_edges = load_seed_list(
        curriculum_dir,
        "knowledge_edges.json",
        KnowledgeEdgeSeed,
    )
    error_types = load_seed_list(
        curriculum_dir,
        "error_types.json",
        ErrorTypeSeed,
    )

    node_metadata = seed_tutorial_catalog(database, curriculum_dir)
    for item in knowledge_nodes:
        node = database.get(KnowledgeNode, item.id)
        values = item.model_dump(exclude={"id"})
        if item.id in node_metadata:
            values.update(node_metadata[item.id].model_dump())
        if node is None:
            database.add(KnowledgeNode(id=item.id, **values))
        else:
            for field, value in values.items():
                setattr(node, field, value)
    database.flush()

    for item in knowledge_edges:
        statement = select(KnowledgeEdge).where(
            KnowledgeEdge.source_node_id == item.source_node_id,
            KnowledgeEdge.target_node_id == item.target_node_id,
            KnowledgeEdge.relation_type == item.relation_type,
        )
        edge = database.scalar(statement)
        if edge is None:
            database.add(KnowledgeEdge(**item.model_dump()))
        else:
            edge.weight = item.weight

    for item in error_types:
        error_type = database.get(ErrorType, item.id)
        values = item.model_dump(exclude={"id"})
        if error_type is None:
            database.add(ErrorType(id=item.id, **values))
        else:
            for field, value in values.items():
                setattr(error_type, field, value)

    learner = database.get(Learner, "demo_user")
    if learner is None:
        learner = Learner(id="demo_user", display_name="Demo User")
        database.add(learner)
    database.flush()

    seeded_node_ids = {item.id for item in knowledge_nodes}
    seeded_error_ids = {item.id for item in error_types}

    for node_id, (mastery, status) in DEMO_KNOWLEDGE_STATE.items():
        if node_id not in seeded_node_ids:
            continue
        statement = select(LearnerKnowledgeNode).where(
            LearnerKnowledgeNode.learner_id == learner.id,
            LearnerKnowledgeNode.knowledge_node_id == node_id,
        )
        if database.scalar(statement) is None:
            database.add(
                LearnerKnowledgeNode(
                    learner_id=learner.id,
                    knowledge_node_id=node_id,
                    mastery=mastery,
                    status=status,
                )
            )

    for error_id, (severity, status) in DEMO_ERROR_STATE.items():
        if error_id not in seeded_error_ids:
            continue
        statement = select(LearnerErrorNode).where(
            LearnerErrorNode.learner_id == learner.id,
            LearnerErrorNode.error_type_id == error_id,
        )
        if database.scalar(statement) is None:
            now = datetime.utcnow()
            database.add(
                LearnerErrorNode(
                    learner_id=learner.id,
                    error_type_id=error_id,
                    severity=severity,
                    status=status,
                    occurrence_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )

    database.commit()
    return SeedResult(
        knowledge_nodes=_count(database, KnowledgeNode),
        knowledge_edges=_count(database, KnowledgeEdge),
        error_types=_count(database, ErrorType),
        learners=_count(database, Learner),
        learner_knowledge_nodes=_count(database, LearnerKnowledgeNode),
        learner_error_nodes=_count(database, LearnerErrorNode),
    )


def curriculum_directories(curriculum_dir: Path) -> list[Path]:
    if (curriculum_dir / "knowledge_nodes.json").is_file():
        directories = [curriculum_dir]
        foundation_dir = curriculum_dir.parent / "python_foundation_v1"
        if foundation_dir.is_dir() and foundation_dir not in directories:
            directories.append(foundation_dir)
        return directories
    return sorted(
        path
        for path in curriculum_dir.iterdir()
        if path.is_dir() and (path / "knowledge_nodes.json").is_file()
    )


def _count(database: Session, model: Any) -> int:
    return database.scalar(select(func.count()).select_from(model)) or 0


def main() -> None:
    curriculum_dir = Path(settings.curriculum_dir)
    with SessionLocal() as database:
        result = None
        for directory in curriculum_directories(curriculum_dir):
            result = seed_database(database, directory)
        if result is None:
            raise RuntimeError(f"No curriculum seed directories found under {curriculum_dir}")
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
