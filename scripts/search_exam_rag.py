"""Retrieve complete exam-question chunks from an offline JSONL corpus.

This is the retrieval stage of a RAG example. It uses no model, database, or
third-party package, and never executes code found in a source question.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
from typing import Any


DEFAULT_INPUT = (
    Path(__file__).resolve().parents[1]
    / "python考试真题"
    / "结构化真题"
    / "ncre-python-sample"
    / "rag_questions.reviewed.ready.jsonl"
)
CHINESE_SPAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
IDENTIFIER = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?"
    r"|\d+(?:\.\d+)*"
)
INTERNAL_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "answer_text",
        "answer_provenance",
        "correct_answer",
        "correct_option",
        "reference_answer",
        "critic_content",
        "critic_content_json",
        "grading_rubric",
        "expected_reasoning",
        "provisional_knowledge_updates",
        "provisional_error_updates",
    }
)
ANSWER_MARKER = re.compile(
    r'"(?:reference_answer|correct_option|grading_rubric)"\s*:'
    r"|(?:参考答案|正确答案|答案解析|评分规则|评分标准)\s*[:：]"
)


def tokenize(text: str) -> list[str]:
    """Use Chinese characters/bigrams and case-insensitive code identifiers."""
    tokens = []
    for match in CHINESE_SPAN.finditer(text):
        span = match.group()
        tokens.extend(span)
        tokens.extend(span[index : index + 2] for index in range(len(span) - 1))
    for match in IDENTIFIER.finditer(text):
        token = match.group().removesuffix("()").casefold()
        tokens.append(token)
        if "." in token and not token[0].isdigit():
            tokens.extend(token.split("."))
    return tokens


def contains_answer_payload(value: Any) -> bool:
    """Reject obvious answer fields even when a record is mislabeled question.

    Visibility labels and this lexical check complement an audited source
    corpus; the check cannot infer every answer expressed in natural language.
    """
    if isinstance(value, dict):
        return bool(set(value) & INTERNAL_FIELDS) or any(
            contains_answer_payload(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(contains_answer_payload(child) for child in value)
    return isinstance(value, str) and ANSWER_MARKER.search(value) is not None


def load_documents(path: Path, include_answers: bool) -> list[dict[str, Any]]:
    documents = []
    seen_ids = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number}: invalid JSON") from error
        if not isinstance(item, dict):
            raise ValueError(f"line {number}: expected an object")
        if not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError(f"line {number}: id must be a nonempty string")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError(f"line {number}: text must be a nonempty string")
        if not isinstance(item.get("metadata"), dict):
            raise ValueError(f"line {number}: metadata must be an object")
        if item["id"] in seen_ids:
            raise ValueError(f"line {number}: duplicate chunk id")
        seen_ids.add(item["id"])

        # The full archive also includes quarantined source questions. Keep the
        # reviewed default policy even if --input points at that archive.
        if item["metadata"].get("retrieval_ready") is False:
            continue
        visibility = item["metadata"].get("visibility")
        if visibility == "question":
            if contains_answer_payload(item["text"]) or contains_answer_payload(
                item["metadata"]
            ):
                continue
        elif visibility == "internal_answer" and include_answers:
            pass
        else:
            # Missing, unknown, or internal visibility is denied by default.
            continue
        documents.append(
            {"id": item["id"], "text": item["text"], "metadata": item["metadata"]}
        )
    return documents


def search(
    query: str, documents: list[dict[str, Any]], top_k: int
) -> list[dict[str, Any]]:
    """Rank matching whole chunks using BM25 (k1=1.5, b=0.75)."""
    query_tokens = set(tokenize(query))
    if not documents or not query_tokens:
        return []
    frequencies = [Counter(tokenize(item["text"])) for item in documents]
    lengths = [sum(frequency.values()) for frequency in frequencies]
    average_length = sum(lengths) / len(documents)
    if not average_length:
        return []
    document_frequencies = Counter(
        token
        for frequency in frequencies
        for token in frequency
        if token in query_tokens
    )
    results = []
    k1, b = 1.5, 0.75
    for item, frequency, length in zip(documents, frequencies, lengths):
        score = 0.0
        for token in query_tokens.intersection(frequency):
            count = frequency[token]
            df = document_frequencies[token]
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = count + k1 * (1 - b + b * length / average_length)
            score += idf * count * (k1 + 1) / denominator
        if score > 0:
            results.append({"score": round(score, 6), **item})
    results.sort(key=lambda item: (-item["score"], item["id"]))
    return results[:top_k]


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "离线真题 RAG 候选检索示例：按整题进行 BM25 排序；"
            "这是 retrieval 阶段，不包含模型生成或完整 RAG 流程。"
        )
    )
    parser.add_argument("query", help="中文知识点、代码标识符或自然语言检索词")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="JSONL 语料路径（默认使用仓库 ready 题面语料）",
    )
    parser.add_argument(
        "--top-k", type=positive_int, default=3, help="最多返回条数，默认 3"
    )
    parser.add_argument(
        "--include-answers",
        action="store_true",
        help="显式允许 internal_answer 记录，仅供内部使用；默认只接受 question 记录",
    )
    args = parser.parse_args()
    try:
        documents = load_documents(args.input, args.include_answers)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            search(args.query, documents, args.top_k), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
