"""Local administration of validated question-bank JSON.

This command does not expose internal answers through the student API.
"""

import argparse
import json
from pathlib import Path

from app.schemas.question_bank import (
    QuestionBankImport,
    QuestionBankQuery,
    import_from_exam_example,
)
from app.services.question_bank_service import QuestionBankService


def main() -> None:
    parser = argparse.ArgumentParser(description="PyCoach internal question bank")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="print the JSON Schema for native imports")
    importer = commands.add_parser("import-json", help="import a validated JSON document")
    importer.add_argument("path", type=Path)
    query = commands.add_parser("query", help="list approved iterator question candidates")
    query.add_argument("--node", action="append", default=[])
    query.add_argument("--min-difficulty", type=int, default=1)
    query.add_argument("--max-difficulty", type=int, default=5)
    query.add_argument("--exclude", action="append", default=[])
    query.add_argument("--limit", type=int, default=10)
    review = commands.add_parser("review", help="set review status after local content review")
    review.add_argument("revision_id")
    review.add_argument("status", choices=["draft", "approved", "invalid"])
    args = parser.parse_args()

    if args.command == "schema":
        print(json.dumps(QuestionBankImport.model_json_schema(), ensure_ascii=False, indent=2))
        return

    # Importing database settings only here keeps schema and CLI parser tests
    # independent of the configured running database.
    from app.core.database import SessionLocal

    with SessionLocal() as database:
        with database.begin():
            service = QuestionBankService(database)
            if args.command == "import-json":
                payload = import_from_exam_example(
                    json.loads(args.path.read_text(encoding="utf-8"))
                )
                service.register_catalog(payload.catalog_chapters, payload.catalog_knowledge_nodes)
                document = service.register_document(payload.document)
                revisions = [
                    service.create_revision(document.id, item) for item in payload.questions
                ]
                result = {
                    "document_id": document.id,
                    "questions": [
                        {
                            "bank_question_id": item.bank_question_id,
                            "revision_id": item.id,
                            "revision": item.revision,
                            "review_status": item.review_status,
                        }
                        for item in revisions
                    ],
                }
            elif args.command == "review":
                revision = service.review_revision(args.revision_id, args.status)
                result = {"revision_id": revision.id, "review_status": revision.review_status}
            else:
                result = [
                    item.model_dump(mode="json")
                    for item in service.find_candidates(
                        QuestionBankQuery(
                            knowledge_node_ids=args.node,
                            difficulty_min=args.min_difficulty,
                            difficulty_max=args.max_difficulty,
                            exclude_bank_question_ids=args.exclude,
                            limit=args.limit,
                        )
                    )
                ]
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
