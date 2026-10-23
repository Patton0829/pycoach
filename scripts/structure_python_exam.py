"""Build source-preserving, offline RAG records for the supplied NCRE sample PDF.

This is a source-specific extractor, not a generic PDF/OCR importer. Manual visual
transcriptions and editorial observations live in annotations.json and are bound
to the PDF SHA256. No model, database, or exam code is executed.

Requires Python 3.10+, pypdf, Pydantic 2 and the Poppler pdftoppm executable.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

# Support direct execution from any working directory without installing the API.
from app.schemas.base import StrictModel  # noqa: E402
from app.schemas.question import QuestionCriticContent, StudentQuestionContent  # noqa: E402
from app.schemas.question_bank import (  # noqa: E402
    BankQuestionRevisionInput,
    ContentNormalization,
    OriginalOption,
    OriginalQuestionContent,
    QuestionBankImport,
    SourceDocumentInput,
    SourceLocations,
)

DEFAULT_OUTPUT = ROOT / "python考试真题/结构化真题/ncre-python-sample"
SOURCE_RELATIVE_PATH = "python考试真题/二级Python语言程序设计——样题及参考答案.pdf"
EXPECTED_SHA256 = "a0f6a19967464aba6bbb5150d4311311672179c963f631eeed6745e7f4956fd8"
SECTIONS = ("一、单项选择题", "二、基本操作题", "三、简单应用题", "四、综合应用题")


class ReferenceAnswer(StrictModel):
    origin: Literal["provided_pdf_reference_answers"]
    correct_option: Literal["A", "B", "C", "D"]
    source_text: str
    explanation: str | None = None


class QualityIssue(StrictModel):
    code: str
    severity: Literal["blocking", "advisory"]
    description: str
    origin: Literal["project_annotation"] = "project_annotation"


class SourceAsset(StrictModel):
    pdf_page: int = Field(ge=1)
    role: Literal["formula", "figure", "code_layout"]
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    description: str


class ExamQuestion(StrictModel):
    question_id: str
    question_number: int = Field(ge=1, le=36)
    source_section: str
    question_type: Literal["multiple_choice", "code_blank", "programming"]
    original_content: OriginalQuestionContent
    raw_extracted_text: str
    student_content: StudentQuestionContent
    formula_latex: str | None = None
    source_locations: SourceLocations
    answer: ReferenceAnswer | None
    answer_status: Literal["provided", "not_provided"]
    answer_source_note: str
    topic_tags: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    difficulty_reason: str
    annotation_origin: Literal["project_annotation"] = "project_annotation"
    review_status: Literal["draft"] = "draft"
    runtime_curriculum_eligible: Literal[False] = False
    runtime_knowledge_node_ids: list[str] = Field(default_factory=list, max_length=0)
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    retrieval_ready: bool
    normalizations: list[ContentNormalization] = Field(default_factory=list)
    assets: list[SourceAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_record(self) -> "ExamQuestion":
        if (self.answer is not None) != (self.answer_status == "provided"):
            raise ValueError("answer status must match the presence of a source answer")
        if self.question_type == "multiple_choice":
            if [item.label for item in self.original_content.options] != list("ABCD"):
                raise ValueError("each multiple-choice item must retain A/B/C/D")
            if self.answer is None:
                raise ValueError(
                    "this source supplies answers for all multiple-choice items"
                )
        elif self.answer is not None:
            raise ValueError("this source omits the answers for questions 31-36")
        blocking = any(item.severity == "blocking" for item in self.quality_issues)
        if self.retrieval_ready == blocking:
            raise ValueError(
                "blocking source issues must be excluded from default retrieval"
            )
        if "\x00" in self.student_content.markdown:
            raise ValueError("unreadable PDF glyphs must not reach retrieval text")
        return self


class StructuredExam(StrictModel):
    schema_version: Literal["pycoach.exam-rag.v1"] = "pycoach.exam-rag.v1"
    document: SourceDocumentInput
    exam_year_note: str
    processing_notes: list[str]
    questions: list[ExamQuestion] = Field(min_length=36, max_length=36)

    @model_validator(mode="after")
    def validate_paper(self) -> "StructuredExam":
        if [item.question_number for item in self.questions] != list(range(1, 37)):
            raise ValueError("source question sequence must be complete and ordered")
        if len({item.question_id for item in self.questions}) != 36:
            raise ValueError("source IDs must be unique")
        for item in self.questions:
            locations = item.source_locations
            pages = locations.question_pdf_pages + locations.answer_pdf_pages
            if any(page > self.document.page_count for page in pages):
                raise ValueError("source location exceeds the document")
            if item.answer_status == "provided" and locations.answer_pdf_pages != [9]:
                raise ValueError("reference answers must trace to physical PDF page 9")
        return self


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def parse_blocks(reader: PdfReader) -> dict[int, dict]:
    """Merge page-spanning question blocks while retaining line-level page origin."""
    blocks: dict[int, dict] = {}
    current = None
    section = None
    for page_number, page in enumerate(reader.pages[:8], 1):
        for line in page.extract_text().splitlines():
            if re.fullmatch(r"\s*-\s*\d+\s*-\s*", line):
                continue
            if line.strip() in SECTIONS:
                section = line.strip()
                continue
            match = re.match(r"^(\d+)、(.*)$", line)
            if match:
                current = int(match.group(1))
                if current in blocks:
                    raise ValueError(f"duplicate question number {current}")
                blocks[current] = {"section": section, "lines": []}
                line = match.group(2)
            if current is not None:
                blocks[current]["lines"].append((page_number, line))
    if sorted(blocks) != list(range(1, 37)):
        raise ValueError("PDF question boundaries did not match the reviewed sample")
    return blocks


def split_content(
    number: int, block: dict
) -> tuple[OriginalQuestionContent, list, list]:
    stem_lines = []
    code_lines = []
    option_lines: dict[str, list[tuple[int, str]]] = {}
    current_option = None
    in_code = False
    for page, line in block["lines"]:
        option = re.match(r"^([A-D])）(.*)$", line) if number <= 30 else None
        if option:
            current_option = option.group(1)
            if current_option in option_lines:
                raise ValueError(f"duplicate option in question {number}")
            option_lines[current_option] = [(page, option.group(2))]
        elif current_option:
            option_lines[current_option].append((page, line))
        else:
            if line.startswith(">>>") or (number == 31 and re.match(r"^\d\. ", line)):
                in_code = True
            if number == 33 and line.startswith("#随机密码生成"):
                in_code = True
            (code_lines if in_code else stem_lines).append((page, line))
    options = [
        OriginalOption(label=label, text="\n".join(text for _, text in lines).strip())
        for label, lines in option_lines.items()
    ]
    return (
        OriginalQuestionContent(
            stem="\n".join(text for _, text in stem_lines).strip(),
            code="\n".join(text for _, text in code_lines).strip() or None,
            options=options,
        ),
        stem_lines + code_lines,
        [entry for lines in option_lines.values() for entry in lines],
    )


def render_assets(source: Path, output: Path) -> dict[int, Path]:
    tool = shutil.which("pdftoppm")
    if tool is None:
        raise RuntimeError(
            "pdftoppm is required to preserve source formula and figure pages"
        )
    asset_dir = output / "assets"
    asset_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            tool,
            "-f",
            "7",
            "-l",
            "8",
            "-scale-to",
            "1500",
            "-png",
            str(source),
            str(asset_dir / "source-page"),
        ],
        check=True,
        capture_output=True,
    )
    return {page: asset_dir / f"source-page-{page}.png" for page in (7, 8)}


def build_question(
    number: int,
    block: dict,
    answer: str | None,
    annotation: dict,
    assets: dict[int, Path],
    output: Path,
) -> ExamQuestion:
    original, stem_lines, option_lines = split_content(number, block)
    raw = "\n".join(text for _, text in block["lines"]).strip()
    stem = original.stem
    code = original.code
    normalizations = []
    if number in (3, 13) and code:
        normalized = code.translate(
            str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
        )
        normalizations.append(
            ContentNormalization(
                field="student_content.markdown: code",
                before=code,
                after=normalized,
                reason="将视觉确认的成对排版引号规范为代码定界符；原始文本保持不变。",
            )
        )
        code = normalized
    if annotation.get("display_code") is not None:
        normalized = annotation["display_code"]
        normalizations.append(
            ContentNormalization(
                field="student_content.markdown: code",
                before=code or "",
                after=normalized,
                reason=annotation["display_code_reason"],
            )
        )
        code = normalized
    if number == 32:
        stem = stem.split("\nx =", 1)[0].strip()
        normalizations.append(
            ContentNormalization(
                field="formula_latex",
                before=original.stem.split("\n", 1)[-1],
                after=annotation["formula_latex"],
                reason="第7页公式的文本层为不可读字符；按渲染图人工转写并核对指数4与分母8。",
            )
        )
        # Keep the broken text-layer evidence in raw_extracted_text, not in the
        # canonical visual transcription or any retrieval-ready content.
        original = original.model_copy(update={"stem": stem})
    if annotation.get("display_stem"):
        normalizations.append(
            ContentNormalization(
                field="student_content.markdown: stem",
                before=stem,
                after=annotation["display_stem"],
                reason=annotation["display_stem_reason"],
            )
        )
        stem = annotation["display_stem"]
    parts = [stem]
    if code:
        language = "pycon" if code.startswith(">>>") else "python"
        parts.append(f"```{language}\n{code}\n```")
    if annotation.get("formula_latex"):
        parts.extend(
            [
                "$$\n" + annotation["formula_latex"] + "\n$$",
                annotation["formula_plaintext"],
            ]
        )
    for item in original.options:
        if item.text.startswith(">>>"):
            parts.append(f"{item.label}.\n\n```pycon\n{item.text}\n```")
        else:
            parts.append(f"{item.label}. {item.text}")
    source_assets = []
    for asset in annotation.get("assets", []):
        path = assets[asset["pdf_page"]]
        relative = path.relative_to(output).as_posix()
        source_assets.append(
            SourceAsset(
                **asset,
                path=relative,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
        if asset["role"] == "figure":
            parts.append("原卷图形：" + asset["description"])
    issues = [
        QualityIssue.model_validate(item)
        for item in annotation.get("quality_issues", [])
    ]
    stem_pages = sorted({page for page, _ in stem_lines})
    option_pages = sorted({page for page, _ in option_lines})
    return ExamQuestion(
        question_id=f"ncre-python-sample-q{number:03d}",
        question_number=number,
        source_section=block["section"],
        question_type=(
            "multiple_choice"
            if number <= 30
            else "code_blank"
            if number in (31, 33)
            else "programming"
        ),
        original_content=original,
        raw_extracted_text=raw,
        student_content=StudentQuestionContent(
            markdown="\n\n".join(parts),
            input_hint="输入选项字母，也可以说明理由。"
            if number <= 30
            else "按原题要求输入代码或说明。",
        ),
        formula_latex=annotation.get("formula_latex"),
        source_locations=SourceLocations(
            question_pdf_pages=sorted({page for page, _ in block["lines"]}),
            stem_pdf_pages=stem_pages,
            options_pdf_pages=option_pages,
            answer_pdf_pages=[9],
        ),
        answer=(
            ReferenceAnswer(
                origin="provided_pdf_reference_answers",
                correct_option=answer,
                source_text=f"{number}.{answer}",
            )
            if answer
            else None
        ),
        answer_status="provided" if answer else "not_provided",
        answer_source_note=(
            f"第9页原卷参考答案 {number}.{answer}；原卷未提供解析。"
            if answer
            else "第9页对应题型的参考答案为‘（略）’，没有提供本题答案。"
        ),
        topic_tags=annotation["topic_tags"],
        difficulty=annotation["difficulty"],
        difficulty_reason=annotation["difficulty_reason"],
        quality_issues=issues,
        retrieval_ready=not any(item.severity == "blocking" for item in issues),
        normalizations=normalizations,
        assets=source_assets,
    )


def rag_record(
    paper: StructuredExam, question: ExamQuestion, *, answer: bool = False
) -> dict:
    visibility = "internal_answer" if answer else "question"
    text = (
        f"{paper.document.title}\n{question.source_section} 第{question.question_number}题\n"
        f"知识标签：{'、'.join(question.topic_tags)}\n\n{question.student_content.markdown}"
    )
    if answer:
        assert question.answer is not None
        text += (
            f"\n\n原PDF参考答案：{question.answer.correct_option}"
            f"\n来源：物理PDF第9页，{question.answer.source_text}。原卷未提供解析。"
        )
    return {
        "id": question.question_id + (":answer:v1" if answer else ":question:v1"),
        "text": text,
        "metadata": {
            "visibility": visibility,
            "question_id": question.question_id,
            "document_id": paper.document.id,
            "document_type": paper.document.document_type,
            "document_sha256": paper.document.sha256,
            "source_path": paper.document.file_path,
            "exam_year": paper.document.exam_year,
            "question_number": question.question_number,
            "section": question.source_section,
            "question_type": question.question_type,
            "pdf_pages": question.source_locations.question_pdf_pages,
            "topic_tags": question.topic_tags,
            "difficulty": question.difficulty,
            "annotation_origin": question.annotation_origin,
            "answer_available": question.answer_status == "provided",
            "review_status": question.review_status,
            "retrieval_ready": question.retrieval_ready,
            "quality_flags": [item.code for item in question.quality_issues],
            "runtime_curriculum_eligible": question.runtime_curriculum_eligible,
            "asset_paths": [item.path for item in question.assets],
            **({"answer_pdf_pages": [9]} if answer else {}),
        },
    }


def native_draft(paper: StructuredExam) -> QuestionBankImport:
    questions = []
    for item in paper.questions:
        if item.question_type != "multiple_choice":
            continue
        assert item.answer is not None
        issues = "；".join(issue.description for issue in item.quality_issues)
        questions.append(
            BankQuestionRevisionInput(
                bank_question_id=item.question_id,
                question_number=str(item.question_number),
                question_type="multiple_choice",
                difficulty=item.difficulty,
                difficulty_reason=item.difficulty_reason,
                cognitive_goal="recognize_or_trace",
                original_content=item.original_content,
                student_content=item.student_content,
                critic_content=QuestionCriticContent(
                    learning_objective="来源草稿，待建立课程映射并审核："
                    + "、".join(item.topic_tags),
                    reference_answer="原PDF参考答案：" + item.answer.correct_option,
                    acceptable_answers=[],
                    grading_rubric={
                        "pending_review": "原卷仅给答案字母。尚未确认评分规则，草稿不得直接用于评分。"
                    },
                    expected_reasoning="原卷未提供解题过程，解析待审核补充。",
                    ambiguity_notes=issues
                    or "完整原文已保留，课程映射和评分材料尚待审核。",
                ),
                source_locations=item.source_locations,
                answer_provenance={
                    "origin": "provided_pdf_reference_answers",
                    "correct_option": item.answer.correct_option,
                    "source_text": item.answer.source_text,
                    "explanation_origin": "unknown",
                },
                normalizations=item.normalizations,
                topic_tags=item.topic_tags,
                knowledge_targets=[],
                target_error_ids=[],
                review_status="draft",
            )
        )
    return QuestionBankImport(document=paper.document, questions=questions)


def export(paper: StructuredExam, output: Path) -> dict:
    write_json(output / "exam.json", paper.model_dump(mode="json"))
    write_json(output / "schema.json", StructuredExam.model_json_schema())
    all_questions = [rag_record(paper, item) for item in paper.questions]
    ready = [
        record for record in all_questions if record["metadata"]["retrieval_ready"]
    ]
    answers = [
        rag_record(paper, item, answer=True)
        for item in paper.questions
        if item.retrieval_ready and item.answer is not None
    ]
    for name, records in (
        ("rag_questions.jsonl", all_questions),
        ("rag_questions.ready.jsonl", ready),
        ("rag_answers.internal.jsonl", answers),
    ):
        (output / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
            encoding="utf-8",
        )
    native = native_draft(paper)
    write_json(output / "bank_import.draft.json", native.model_dump(mode="json"))
    report = {
        "document_sha256": paper.document.sha256,
        "question_count": len(paper.questions),
        "question_types": dict(Counter(item.question_type for item in paper.questions)),
        "answers_provided": sum(item.answer is not None for item in paper.questions),
        "missing_answer_questions": [
            item.question_number for item in paper.questions if item.answer is None
        ],
        "question_chunks": len(all_questions),
        "default_question_chunks": len(ready),
        "internal_answer_chunks": len(answers),
        "excluded_from_default_retrieval": [
            item.question_number for item in paper.questions if not item.retrieval_ready
        ],
        "review_queue": [
            {
                "question_id": item.question_id,
                "question_number": item.question_number,
                "pdf_pages": item.source_locations.question_pdf_pages,
                "source_answer": item.answer.correct_option if item.answer else None,
                "retrieval_ready": item.retrieval_ready,
                "issues": [issue.model_dump() for issue in item.quality_issues],
            }
            for item in paper.questions
            if item.quality_issues
        ],
        "method": [
            "校验原PDF SHA256后，按物理页提取文本；保留跨页题干、选项和代码。",
            "按题号切分，一道完整题目作为一个RAG chunk，不按固定字符长度截断。",
            "按第9页的题号关联30个原卷答案；后6题答案为null，不补造解析。",
            "标签和难度为项目标注，代码引号、缩进、公式人工转写均记录normalizations。",
            "题面与内部答案分别导出，阻断性源卷问题排除默认检索。",
            "输出通过Pydantic 2校验；仅构建离线资料，不调用LLM、执行题中代码或写入业务数据库。",
        ],
        "native_import_note": "bank_import.draft.json仅包含30道选择题，全部draft且未映射课程。"
        "若相同题号修订已存在，实际导入前需审核内容并增加revision；本次未导入数据库。",
        "rag_usage": "search_exam_rag.py展示离线检索环节；后续可将ready JSONL的text送入embedding服务，"
        "保留metadata和稳定ID。当前未生成向量或接入生成模型。",
        "commands": {
            "rebuild": "python scripts/structure_python_exam.py",
            "retrieve_questions": "python scripts/search_exam_rag.py '字典 添加 删除' --top-k 3",
            "retrieve_internal_answers": "python scripts/search_exam_rag.py '整除' --input "
            "python考试真题/结构化真题/ncre-python-sample/"
            "rag_answers.internal.jsonl --include-answers --top-k 1",
        },
        "rebuild_dependencies": [
            "Python >=3.10",
            "pypdf",
            "pydantic >=2,<3",
            "Poppler pdftoppm",
        ],
        "retrieval_dependencies": ["Python >=3.10；检索脚本仅使用标准库"],
    }
    write_json(output / "processing_report.json", report)
    # Reopen final artifacts; validate serialization, isolation and source joins.
    StructuredExam.model_validate_json((output / "exam.json").read_text())
    QuestionBankImport.model_validate_json(
        (output / "bank_import.draft.json").read_text()
    )
    assert len(all_questions) == 36 and len(native.questions) == 30
    for record in all_questions:
        assert "\x00" not in record["text"]
        assert "原PDF参考答案：" not in record["text"]
        assert record["metadata"]["visibility"] == "question"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    source = ROOT / SOURCE_RELATIVE_PATH
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(
            "PDF changed: visual transcriptions and annotations need a fresh review"
        )
    annotations = json.loads(
        (DEFAULT_OUTPUT / "annotations.json").read_text(encoding="utf-8")
    )
    if annotations["source_sha256"] != digest:
        raise ValueError("annotations belong to another source PDF")
    reader = PdfReader(source)
    if len(reader.pages) != 9:
        raise ValueError("unexpected sample-exam page count")
    answer_pairs = re.findall(r"\b(\d{1,2})\.([A-D])\b", reader.pages[8].extract_text())
    answers = {int(number): letter for number, letter in answer_pairs}
    if len(answer_pairs) != 30 or sorted(answers) != list(range(1, 31)):
        raise ValueError("reference answer grid is incomplete or duplicated")
    output.mkdir(parents=True, exist_ok=True)
    assets = render_assets(source, output)
    blocks = parse_blocks(reader)
    paper = StructuredExam(
        document=SourceDocumentInput(
            id=str(uuid5(NAMESPACE_URL, "pycoach:exam:" + digest)),
            title="全国计算机等级考试（NCRE）二级 Python 语言程序设计 样题及参考答案",
            document_type="sample_exam",
            exam_year=None,
            file_path=SOURCE_RELATIVE_PATH,
            sha256=digest,
            page_count=9,
        ),
        exam_year_note="原卷未标明考试年份；PDF创建时间不作为考试年份。",
        processing_notes=[
            "用户提供的样题，未据文件名推断为某年正式真题。",
            "original_content保留文本原貌，raw_extracted_text保留文本层证据（可含原始不可读字符）。",
            "student_content只含题面；source答案、质量复核与教学难度分别存储。",
            "全卷均为离线draft资料，未批准为当前迭代器课程正式题。",
        ],
        questions=[
            build_question(
                number,
                blocks[number],
                answers.get(number),
                annotations["questions"][str(number)],
                assets,
                output,
            )
            for number in range(1, 37)
        ],
    )
    report = export(paper, output)
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("review_queue", "method")
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
