"""Export reviewed, source-preserving NCRE questions and a local review page.

The source extraction remains immutable. Editorial decisions are read from
review_annotations.json and validated with Pydantic before any output is written.
This command does not connect to a database, call a model, or execute exam code.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html import escape
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Literal
from urllib.parse import quote, urlparse

from pydantic import Field, TypeAdapter, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/api"))

from app.schemas.base import StrictModel  # noqa: E402
from app.schemas.question_bank import (  # noqa: E402
    BankQuestionRevisionInput,
    CatalogChapterInput,
    CatalogKnowledgeNodeInput,
    QuestionBankImport,
    QuestionKnowledgeTarget,
)
from scripts.structure_python_exam import StructuredExam  # noqa: E402

DEFAULT_INPUT = ROOT / "python考试真题/结构化真题/ncre-python-sample"
DEFAULT_CATALOG = ROOT / "curriculum/python_tutorial_catalog.json"
REVISION = 2


class ReviewedQuestion(StrictModel):
    question_number: int = Field(ge=1, le=36)
    revision: int = Field(default=REVISION, ge=2)
    difficulty: int = Field(ge=1, le=5)
    status: Literal["approved", "invalid"]
    knowledge_targets: list[QuestionKnowledgeTarget] = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    reference_code: str | None = None
    explanation: str = Field(min_length=1)
    correct_option: str | None = None
    source_correct_option: str | None = None
    answer_origin: Literal["provided_pdf_reference_answers", "project_annotation"]
    notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    student_clarification: str | None = None
    references: list[str] = Field(default_factory=list)


class ReviewAnnotations(StrictModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    taxonomy_source: str
    review_policy: str = ""
    questions: list[ReviewedQuestion] = Field(min_length=36, max_length=36)

    @model_validator(mode="after")
    def complete_paper(self) -> "ReviewAnnotations":
        if sorted(item.question_number for item in self.questions) != list(
            range(1, 37)
        ):
            raise ValueError(
                "review annotations must cover questions 1-36 exactly once"
            )
        return self


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def node_catalog(catalog: dict, supplemental: list[CatalogKnowledgeNodeInput]) -> dict:
    """Resolve real node names and official chapter references without a database."""
    nodes = {}
    metadata = catalog["node_metadata"]
    for path in sorted((ROOT / "curriculum").glob("*/knowledge_nodes.json")):
        for item in read_json(path):
            nodes[item["id"]] = {**item, **metadata.get(item["id"], {})}
    for item in supplemental:
        if item.id in nodes:
            raise ValueError(
                f"supplemental node duplicates an existing node: {item.id}"
            )
        nodes[item.id] = item.model_dump(mode="json")
    return nodes


def build_reviewed_exports(
    exam_path: Path,
    annotations_path: Path,
    supplemental_nodes_path: Path,
    catalog_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    exam = StructuredExam.model_validate(read_json(exam_path))
    annotations = ReviewAnnotations.model_validate(read_json(annotations_path))
    supplemental = TypeAdapter(list[CatalogKnowledgeNodeInput]).validate_python(
        read_json(supplemental_nodes_path)
    )
    catalog = read_json(catalog_path)
    chapters = TypeAdapter(list[CatalogChapterInput]).validate_python(
        catalog["chapters"]
    )
    chapter_by_id = {chapter.id: chapter for chapter in chapters}
    nodes = node_catalog(catalog, supplemental)
    source_pdf = ROOT / exam.document.file_path
    source_hash = fingerprint(source_pdf)
    if source_hash != exam.document.sha256 or source_hash != annotations.source_sha256:
        raise ValueError("source PDF fingerprint differs from the extraction or review")
    by_number = {item.question_number: item for item in annotations.questions}
    bank_items = []
    public_chunks = []
    answer_chunks = []
    question_reports = []

    for original in exam.questions:
        review = by_number[original.question_number]
        source_option = original.answer.correct_option if original.answer else None
        if review.source_correct_option != source_option:
            raise ValueError(
                f"question {original.question_number}: source answer changed"
            )
        if (
            review.answer_origin == "provided_pdf_reference_answers"
            and review.correct_option != source_option
        ):
            raise ValueError("a changed answer must be labeled project_annotation")
        if original.answer is None and review.answer_origin != "project_annotation":
            raise ValueError(
                "source-omitted answers must be labeled project_annotation"
            )

        knowledge_points = []
        for target in review.knowledge_targets:
            if target.knowledge_node_id not in nodes:
                raise ValueError(f"unknown mapped node: {target.knowledge_node_id}")
            node = nodes[target.knowledge_node_id]
            chapter_id = node.get("chapter_id")
            if chapter_id not in chapter_by_id:
                raise ValueError(f"mapped node lacks an official chapter: {node['id']}")
            chapter = chapter_by_id[chapter_id]
            knowledge_points.append(
                {
                    "id": node["id"],
                    "name": node["name"],
                    "role": target.role,
                    "is_primary": target.is_primary,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter.title,
                    "reference_section": node.get("reference_section"),
                    "reference_url": node.get("reference_url"),
                    "is_supplementary": node.get("is_supplementary", False),
                }
            )

        markdown = original.student_content.markdown
        normalizations = [
            item.model_dump(mode="json") for item in original.normalizations
        ]
        if original.question_number == 26:
            normalized = markdown.translate(str.maketrans({"“": '"', "”": '"'}))
            if normalized != markdown:
                normalizations.append(
                    {
                        "field": "student_content.markdown",
                        "before": markdown,
                        "after": normalized,
                        "reason": "将代码中的排版引号规范成Python字符串定界符，原题保留。",
                    }
                )
                markdown = normalized
        if review.student_clarification:
            clarified = markdown + "\n\n> 项目补充说明：" + review.student_clarification
            normalizations.append(
                {
                    "field": "student_content.markdown",
                    "before": markdown,
                    "after": clarified,
                    "reason": "显式标明审核时补充的题意约定，原卷内容未被覆盖。",
                }
            )
            markdown = clarified

        assessed = [
            item for item in review.knowledge_targets if item.role == "assessed"
        ]
        objective = "；".join(item.assessment_criterion for item in assessed)
        reference = review.reference_answer
        if review.reference_code:
            reference += "\n\n```python\n" + review.reference_code.rstrip() + "\n```"
        criteria = {
            item.knowledge_node_id: item.assessment_criterion for item in assessed
        }
        if review.status == "invalid":
            criteria["assessment_policy"] = "原题审核未通过，不得据此更新学生掌握记录。"
        else:
            criteria["correct"] = (
                "满足各评估目标，答案或等价代码正确；不要求逐字匹配参考解。"
            )
            criteria["partial"] = (
                "部分目标成立，但仍存在遗漏或逻辑错误，按知识点分别判断。"
            )
            criteria["incorrect"] = "未满足评估目标，或关键结论、代码逻辑错误。"

        locations = original.source_locations.model_dump(mode="json")
        if original.answer is None:
            locations["answer_pdf_pages"] = []
        source_text = original.answer.source_text if original.answer else None
        item = BankQuestionRevisionInput.model_validate(
            {
                "bank_question_id": original.question_id,
                "question_number": str(original.question_number),
                "revision": review.revision,
                "question_type": original.question_type,
                "difficulty": review.difficulty,
                "difficulty_origin": "project_annotation",
                "difficulty_reason": original.difficulty_reason,
                "cognitive_goal": "apply_and_explain"
                if original.question_number >= 31
                else "recognize_or_trace",
                "original_content": original.original_content.model_dump(mode="json"),
                "student_content": {
                    **original.student_content.model_dump(),
                    "markdown": markdown,
                },
                "critic_content": {
                    "learning_objective": objective,
                    "reference_answer": reference,
                    "acceptable_answers": [
                        review.correct_option,
                        review.reference_answer,
                    ]
                    if review.correct_option
                    else [review.reference_answer],
                    "grading_rubric": criteria,
                    "expected_reasoning": review.explanation,
                    "ambiguity_notes": "；".join(review.notes + review.assumptions)
                    or None,
                },
                "source_locations": locations,
                "answer_provenance": {
                    "origin": review.answer_origin,
                    "correct_option": review.correct_option,
                    "source_correct_option": source_option,
                    "source_text": source_text,
                    "explanation_origin": "project_annotation",
                    "review_note": "；".join(review.notes) or None,
                    "assumptions": review.assumptions,
                    "verification_sources": review.references,
                },
                "normalizations": normalizations,
                "topic_tags": original.topic_tags,
                "target_error_ids": [],
                "knowledge_targets": [
                    item.model_dump(mode="json") for item in review.knowledge_targets
                ],
                "review_status": review.status,
            }
        )
        bank_items.append(item)
        assessed_points = [
            point for point in knowledge_points if point["role"] == "assessed"
        ]
        metadata = {
            "visibility": "question",
            "question_id": original.question_id,
            "document_id": exam.document.id,
            "document_type": exam.document.document_type,
            "document_sha256": source_hash,
            "source_path": exam.document.file_path,
            "source_title": exam.document.title,
            "exam_year": exam.document.exam_year,
            "question_number": original.question_number,
            "section": original.source_section,
            "question_type": original.question_type,
            "pdf_pages": locations["question_pdf_pages"],
            "topic_tags": original.topic_tags,
            "difficulty": review.difficulty,
            "knowledge_node_ids": [point["id"] for point in assessed_points],
            "knowledge_points": assessed_points,
            "annotation_origin": "project_annotation",
            "review_status": review.status,
            "retrieval_ready": review.status == "approved",
            "revision": review.revision,
            "runtime_curriculum_eligible": False,
            "asset_paths": [asset.path for asset in original.assets],
        }
        chunk_text = (
            f"{exam.document.title}\n{original.source_section} 第{original.question_number}题\n"
            + "知识点："
            + "、".join(point["name"] for point in assessed_points)
            + "\n\n"
            + markdown
        )
        public_chunks.append(
            {
                "id": f"{original.question_id}:question:v{review.revision}",
                "text": chunk_text,
                "metadata": metadata,
            }
        )
        if review.status == "approved":
            answer_chunks.append(
                {
                    "id": f"{original.question_id}:answer:v{review.revision}",
                    "text": f"第{original.question_number}题内部参考答案：\n{reference}\n\n解析：{review.explanation}",
                    "metadata": {
                        **metadata,
                        "visibility": "internal_answer",
                        "answer_origin": review.answer_origin,
                        "source_correct_option": source_option,
                        "correct_option": review.correct_option,
                        "source_text": source_text,
                        "answer_pdf_pages": locations["answer_pdf_pages"],
                        "assumptions": review.assumptions,
                        "references": review.references,
                    },
                }
            )
        question_reports.append(
            {
                "question_id": original.question_id,
                "question_number": original.question_number,
                "revision": review.revision,
                "review_status": review.status,
                "difficulty": review.difficulty,
                "source_original_preserved": True,
                "source_locations": locations,
                "knowledge_points": knowledge_points,
                "knowledge_targets": [
                    target.model_dump(mode="json")
                    for target in review.knowledge_targets
                ],
                "mapping_source": annotations.taxonomy_source,
                "answer_provenance": item.answer_provenance.model_dump(mode="json"),
                "reference_answer": review.reference_answer,
                "reference_code": review.reference_code,
                "explanation": review.explanation,
                "notes": review.notes,
                "assumptions": review.assumptions,
                "student_clarification": review.student_clarification,
                "references": review.references,
                "original_quality_issues": [
                    issue.model_dump(mode="json") for issue in original.quality_issues
                ],
            }
        )

    payload = QuestionBankImport(
        document=exam.document,
        questions=bank_items,
        catalog_chapters=chapters,
        catalog_knowledge_nodes=supplemental,
    )
    counts = Counter(item.review_status for item in bank_items)
    report = {
        "schema_version": "pycoach.exam-review.v1",
        "source_document": exam.document.model_dump(mode="json"),
        "taxonomy_source": annotations.taxonomy_source,
        "review_policy": annotations.review_policy,
        "revision": REVISION,
        "revision_note": "此处revision表示审核导出代次，各题内容版本以question_revisions为准。",
        "question_revisions": {
            item.bank_question_id: item.revision for item in bank_items
        },
        "question_count": len(bank_items),
        "review_status_counts": dict(sorted(counts.items())),
        "mapped_question_count": len(question_reports),
        "assessed_mapping_count": sum(
            len(
                [
                    point
                    for point in item["knowledge_points"]
                    if point["role"] == "assessed"
                ]
            )
            for item in question_reports
        ),
        "difficulty_counts": dict(
            sorted(Counter(item.difficulty for item in bank_items).items())
        ),
        "supplemental_node_count": len(supplemental),
        "missing_answers_filled": [
            item.question_number for item in exam.questions if item.answer is None
        ],
        "corrected_reference_answers": [
            item.question_number
            for item in annotations.questions
            if item.source_correct_option is not None
            and item.correct_option is not None
            and item.source_correct_option != item.correct_option
        ],
        "blocked_questions": [
            int(item.question_number)
            for item in bank_items
            if item.review_status != "approved"
        ],
        "public_question_chunks": len(public_chunks),
        "ready_question_chunks": sum(
            item["metadata"]["retrieval_ready"] for item in public_chunks
        ),
        "internal_answer_chunks": len(answer_chunks),
        "runtime_curriculum_eligible_count": 0,
        "notes": [
            "审核通过表示题库内容可用，不会自动扩展当前迭代器学习模块。",
            "官方教程之外的补充知识点明确标记is_supplementary。",
            "题面语料不含答案、评分材料或内部审核说明；内部答案语料单独保存。",
            "所有参考代码仅经人工静态推理，导出命令不会执行题目代码。",
        ],
        "input_fingerprints": {
            "exam_json": fingerprint(exam_path),
            "review_annotations": fingerprint(annotations_path),
            "supplemental_nodes": fingerprint(supplemental_nodes_path),
            "tutorial_catalog": fingerprint(catalog_path),
        },
        "questions": question_reports,
    }
    ready = [chunk for chunk in public_chunks if chunk["metadata"]["retrieval_ready"]]
    return {
        "bank_import.reviewed.json": payload.model_dump(mode="json"),
        "bank_import.reviewed.schema.json": QuestionBankImport.model_json_schema(),
        "reviewed_review_report.json": report,
        "rag_questions.reviewed.jsonl": public_chunks,
        "rag_questions.reviewed.ready.jsonl": ready,
        "rag_answers.reviewed.internal.jsonl": answer_chunks,
        "review.html": review_html(payload, report, output_dir, source_pdf),
    }


def safe_link(url: str, label: str) -> str:
    if urlparse(url).scheme not in {"http", "https"}:
        return escape(label)
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noreferrer">{escape(label)}</a>'


def review_html(
    payload: QuestionBankImport, report: dict, output_dir: Path, source_pdf: Path
) -> str:
    cards = []
    source_url = quote(os.path.relpath(source_pdf, output_dir))
    for item, review in zip(payload.questions, report["questions"]):
        stars = "".join(
            f'<span class="star {"gold" if index < item.difficulty else "gray"}" aria-hidden="true">★</span>'
            for index in range(5)
        )
        points = "".join(
            "<li>"
            + escape(point["name"])
            + f' <span class="muted">{escape(point["chapter_title"])}'
            + (
                f" · {escape(point['reference_section'])}"
                if point["reference_section"]
                else ""
            )
            + (" · 补充知识点" if point["is_supplementary"] else "")
            + (" · 前置背景" if point["role"] == "prerequisite" else "")
            + "</span></li>"
            for point in review["knowledge_points"]
        )
        notes = "".join("<li>" + escape(note) + "</li>" for note in review["notes"])
        assumptions = "".join(
            "<li>" + escape(note) + "</li>" for note in review["assumptions"]
        )
        refs = "".join(
            "<li>" + safe_link(url, url) + "</li>" for url in review["references"]
        )
        pages = "、".join(
            str(page) for page in item.source_locations.question_pdf_pages
        )
        first_page = item.source_locations.question_pdf_pages[0]
        status = "审核通过" if item.review_status == "approved" else "原题隔离"
        provenance = item.answer_provenance
        origin_label = (
            "原卷答案，项目补充解析"
            if provenance.origin == "provided_pdf_reference_answers"
            else "项目补充或纠正的参考解"
        )
        source_answer = provenance.source_correct_option or "原卷略去，未提供"
        reference_code = (
            ("<pre><code>" + escape(review["reference_code"]) + "</code></pre>")
            if review["reference_code"]
            else ""
        )
        cards.append(
            f'<article class="card" id="q{escape(item.question_number)}">'
            f'<div class="card-head"><h2>第 {escape(item.question_number)} 题</h2>'
            f'<span class="status {item.review_status}">{status}</span>'
            f'<span class="stars" role="img" aria-label="难度 {item.difficulty} 星，共 5 星">{stars}</span></div>'
            f'<p class="muted">{escape(item.question_type)} · 原卷第 {pages} 页 · 版本 {item.revision} · '
            f'<a href="{source_url}#page={first_page}">查看原卷</a></p>'
            '<ul class="points">' + points + "</ul>"
            '<div class="question-text">'
            + escape(item.student_content.markdown)
            + "</div>"
            + (
                '<div class="review-note"><strong>审核说明</strong><ul>'
                + notes
                + "</ul></div>"
                if notes
                else ""
            )
            + "<details><summary>查看内部参考解与审核依据</summary>"
            + '<p class="muted">'
            + escape(origin_label)
            + "；原卷答案："
            + escape(source_answer)
            + "</p>"
            + "<p>"
            + escape(review["reference_answer"])
            + "</p>"
            + reference_code
            + "<p>"
            + escape(review["explanation"])
            + "</p>"
            + (
                "<strong>补充约定</strong><ul>" + assumptions + "</ul>"
                if assumptions
                else ""
            )
            + '<strong>核验资料</strong><ul class="refs">'
            + refs
            + "</ul>"
            + "</details></article>"
        )
    approved = report["review_status_counts"].get("approved", 0)
    invalid = report["review_status_counts"].get("invalid", 0)
    links = " ".join(f'<a href="#q{index}">{index}</a>' for index in range(1, 37))
    return (
        """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Python 样题 · 知识点映射与审核</title><style>
:root{color-scheme:light;font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#172033;background:#f3f5f8}
*{box-sizing:border-box}body{margin:0}main{max-width:1060px;margin:auto;padding:40px 24px 72px}h1{font-size:30px;line-height:1.35;margin:8px 0 14px}h2{font-size:21px;margin:0}.eyebrow{color:#596779;font-size:13px;letter-spacing:.08em}.intro{line-height:1.8}.muted{color:#677489;font-size:13px}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.stats span{padding:12px 18px;border:1px solid #dde3ec;border-radius:12px;background:white}.stats b{font-size:23px;margin-right:7px}nav{display:flex;gap:7px;flex-wrap:wrap;margin:20px 0 28px}nav a{min-width:32px;padding:6px 9px;background:#fff;text-align:center;border:1px solid #dfe5ed;border-radius:7px;text-decoration:none}.card{background:#fff;border:1px solid #dfe5ed;border-radius:16px;padding:26px;margin:20px 0;scroll-margin-top:20px}.card-head{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.status{font-size:12px;padding:4px 9px;border-radius:99px}.approved{background:#e7f4ec;color:#296144}.invalid{background:#fff0e9;color:#a04d28}.stars{display:inline-flex;gap:3px;margin-left:auto;white-space:nowrap}.star{font-size:23px;line-height:1}.gold{color:#d99a0b}.gray{color:#aeb7c3}.points{padding:12px 18px 12px 32px;background:#f6f8fb;border-radius:9px;font-size:14px;line-height:1.8}.question-text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;font-size:15px;padding:10px 0 18px}.review-note{border-left:3px solid #cc9d52;padding:9px 14px;background:#fffaf2;font-size:14px;line-height:1.7}details{border-top:1px solid #e8ecf1;margin-top:16px;padding-top:14px;line-height:1.8;font-size:14px}summary{cursor:pointer;color:#445d88}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f9;border:1px solid #e4e9f0;border-radius:8px;padding:16px;line-height:1.65;font-size:13px}a{color:#365f9a}.refs{font-size:12px;overflow-wrap:anywhere}footer{color:#677489;font-size:13px;line-height:1.8;margin-top:26px}@media(max-width:600px){main{padding:24px 14px}.card{padding:19px}h1{font-size:25px}.stars{margin-left:0}}
</style></head><body><main><div class="eyebrow">PYCOACH · INTERNAL REVIEW</div>
<h1>Python 样题：知识点映射与审核</h1>
<p class="intro">"""
        + escape(payload.document.title)
        + """<br>按 Python 官方教程章节组织知识点。难度始终显示五颗星：金黄色为当前等级，其余为灰色。</p>
<p class="muted">这是内部审核页，折叠区包含参考答案。原题与原卷答案均保留；项目补充、纠正及题意约定另行标注。审核通过不会自动启用当前迭代器课程之外的题目。</p>
<div class="stats"><span><b>36</b>题已映射</span><span><b>"""
        + str(approved)
        + """</b>题通过</span><span><b>"""
        + str(invalid)
        + """</b>题隔离</span><span><b>6</b>题补充参考解</span></div>
<nav aria-label="题号导航">"""
        + links
        + "</nav>"
        + "".join(cards)
        + """
<footer>难度为项目教学标注，范围为 1 至 5。原卷未标明考试年份。所有代码均为文本参考材料，本页及导出脚本不会执行代码。</footer>
</main></body></html>"""
    )


def write_exports(output_dir: Path, outputs: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        if name.endswith(".jsonl"):
            rendered = "".join(
                json.dumps(item, ensure_ascii=False) + "\n" for item in content
            )
        elif name.endswith(".json"):
            rendered = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        else:
            rendered = content
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output_dir,
                prefix=".review-",
                delete=False,
            ) as temporary:
                temporary.write(rendered)
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, output_dir / name)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="验证审核标注并导出36题题库、RAG题面和内部审核页。"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--check", action="store_true", help="只验证，不写入输出文件")
    args = parser.parse_args()
    output_dir = (args.output_dir or args.input_dir).resolve()
    outputs = build_reviewed_exports(
        args.input_dir / "exam.json",
        args.input_dir / "review_annotations.json",
        args.input_dir / "supplemental_nodes.json",
        args.catalog,
        output_dir,
    )
    if not args.check:
        write_exports(output_dir, outputs)
    report = outputs["reviewed_review_report.json"]
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "question_count",
                    "review_status_counts",
                    "missing_answers_filled",
                    "corrected_reference_answers",
                    "blocked_questions",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
