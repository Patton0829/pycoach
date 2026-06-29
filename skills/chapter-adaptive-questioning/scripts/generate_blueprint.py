#!/usr/bin/env python3
"""Generate an adaptive chapter question blueprint.

The script is intentionally standalone and uses only Python's standard library.
It does not import or modify PyCoach application code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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

GOAL_NODE_HINTS = {
    "recognize": ["iterable", "iterator"],
    "construct": ["iter"],
    "retrieve": ["next"],
    "trace_state": ["state"],
    "contrast_operations": ["iter", "next", "state"],
    "predict_output": ["state", "next"],
    "diagnose_exhaustion": ["exhaustion", "stop_iteration"],
    "explain_protocol": ["for_loop", "protocol"],
    "transfer": ["generator", "for_loop", "protocol"],
    "synthesize": ["iterator", "state", "exhaustion"],
}

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
    "synthesize": ["python.iterator", "python.iterator.state", "python.iterator.exhaustion"],
}


def load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [
            {"id": key, **item} if isinstance(item, dict) else {"id": key, "value": item}
            for key, item in value.items()
        ]
    return []


def item_id(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def normalize_status_mastery(status: str) -> float:
    mapping = {
        "not_started": 0.1,
        "尚未学习": 0.1,
        "learning": 0.35,
        "正在学习": 0.35,
        "needs_practice": 0.4,
        "需要巩固": 0.4,
        "basic": 0.6,
        "基本掌握": 0.6,
        "mastered": 0.85,
        "已掌握": 0.85,
    }
    return mapping.get(status, 0.35)


def normalize_status_severity(status: str) -> float:
    mapping = {
        "resolved": 0.0,
        "已解决": 0.0,
        "inactive": 0.1,
        "learning": 0.45,
        "active": 0.7,
        "needs_practice": 0.75,
        "需要巩固": 0.75,
    }
    return mapping.get(status, 0.5)


def extract_nodes(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return as_list(
        chapter.get("knowledge_nodes")
        or chapter.get("nodes")
        or chapter.get("concepts")
    )


def extract_errors(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return as_list(
        chapter.get("error_types")
        or chapter.get("errors")
        or chapter.get("misconceptions")
    )


def learner_mastery(learner: dict[str, Any]) -> dict[str, float]:
    entries = as_list(
        learner.get("knowledge_graph")
        or learner.get("knowledge")
        or learner.get("mastery_by_node")
        or learner.get("learner_knowledge_nodes")
    )
    result: dict[str, float] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        node_id = item_id(entry, "node_id", "knowledge_node_id", "id")
        if not node_id:
            continue
        mastery = entry.get("mastery")
        if mastery is None:
            mastery = normalize_status_mastery(str(entry.get("status") or entry.get("display_status") or ""))
        result[node_id] = max(0.0, min(1.0, float(mastery)))
    return result


def learner_severity(learner: dict[str, Any]) -> dict[str, float]:
    entries = as_list(
        learner.get("error_graph")
        or learner.get("errors")
        or learner.get("severity_by_error")
        or learner.get("learner_error_nodes")
    )
    result: dict[str, float] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        error_id = item_id(entry, "error_id", "error_type_id", "id")
        if not error_id:
            continue
        severity = entry.get("severity")
        if severity is None:
            severity = normalize_status_severity(str(entry.get("status") or entry.get("display_status") or ""))
        result[error_id] = max(0.0, min(1.0, float(severity)))
    return result


def infer_level(masteries: dict[str, float], nodes: list[dict[str, Any]]) -> tuple[str, float]:
    if not nodes:
        avg = sum(masteries.values()) / len(masteries) if masteries else 0.0
    else:
        values = [
            masteries.get(item_id(node, "id", "node_id", "knowledge_node_id"), 0.0)
            for node in nodes
        ]
        avg = sum(values) / len(values) if values else 0.0
    if avg < 0.35:
        return "novice", avg
    if avg < 0.70:
        return "intermediate", avg
    return "advanced", avg


def related_error_ids(
    errors: list[dict[str, Any]],
    severities: dict[str, float],
    target_node_ids: list[str],
    slot: int,
) -> list[str]:
    overlapping: list[tuple[float, str]] = []
    global_scored: list[tuple[float, str]] = []
    target_set = set(target_node_ids)
    for error in errors:
        error_id = item_id(error, "id", "error_id", "error_type_id")
        if not error_id:
            continue
        related = set(as_list(error.get("related_knowledge_nodes")))
        overlap = len(target_set & related)
        severity = severities.get(error_id, 0.0)
        global_scored.append((severity, error_id))
        if overlap:
            overlapping.append((severity + overlap * 0.4, error_id))
    overlapping.sort(reverse=True)
    if overlapping:
        return [overlapping[0][1]]
    global_scored.sort(reverse=True)
    if global_scored and global_scored[0][0] > 0:
        return [global_scored[0][1]]
    if errors:
        fallback = errors[(slot - 1) % len(errors)]
        fallback_id = item_id(fallback, "id", "error_id", "error_type_id")
        return [fallback_id] if fallback_id else []
    return []


def score_node(
    node: dict[str, Any],
    masteries: dict[str, float],
    errors: list[dict[str, Any]],
    severities: dict[str, float],
) -> float:
    node_id = item_id(node, "id", "node_id", "knowledge_node_id")
    mastery_gap = 1.0 - masteries.get(node_id, 0.0)
    error_pressure = 0.0
    for error in errors:
        error_id = item_id(error, "id", "error_id", "error_type_id")
        if node_id in as_list(error.get("related_knowledge_nodes")):
            error_pressure = max(error_pressure, severities.get(error_id, 0.0))
    return mastery_gap + error_pressure


def choose_nodes_for_goal(
    goal: str,
    nodes: list[dict[str, Any]],
    masteries: dict[str, float],
    errors: list[dict[str, Any]],
    severities: dict[str, float],
    slot: int,
) -> list[str]:
    if not nodes:
        return []
    by_id = {
        item_id(node, "id", "node_id", "knowledge_node_id"): node
        for node in nodes
    }
    preferred = [
        by_id[node_id]
        for node_id in GOAL_NODE_PREFERENCES.get(goal, [])
        if node_id in by_id
    ]
    hints = GOAL_NODE_HINTS.get(goal, [])
    hinted = [
        node
        for node in nodes
        if any(
            segment == hint
            for hint in hints
            for segment in item_id(
                node,
                "id",
                "node_id",
                "knowledge_node_id",
            ).split(".")
        )
    ]
    pool = preferred or hinted or nodes
    pool = sorted(
        pool,
        key=lambda node: (
            -score_node(node, masteries, errors, severities),
            int(node.get("difficulty") or 3),
            item_id(node, "id", "node_id", "knowledge_node_id"),
        ),
    )
    first = pool[(slot - 1) % min(len(pool), max(1, len(pool)))]
    first_id = item_id(first, "id", "node_id", "knowledge_node_id")
    if goal in {"recognize", "contrast_operations", "synthesize"} and len(pool) > 1:
        second = pool[slot % len(pool)]
        second_id = item_id(second, "id", "node_id", "knowledge_node_id")
        return [value for value in [first_id, second_id] if value]
    return [first_id] if first_id else []


def repeating(sequence: list[Any], count: int) -> list[Any]:
    return [sequence[index % len(sequence)] for index in range(count)]


def prompt_brief(goal: str, target_nodes: list[str], target_errors: list[str]) -> str:
    node_text = ", ".join(target_nodes) or "chapter core concept"
    error_text = f" Target misconception: {', '.join(target_errors)}." if target_errors else ""
    briefs = {
        "recognize": "Ask the learner to identify or distinguish a core concept.",
        "construct": "Ask the learner to write the missing expression for a small code fragment.",
        "retrieve": "Ask the learner to use the correct API to get one element.",
        "trace_state": "Ask the learner to track iterator state after repeated operations.",
        "contrast_operations": "Ask the learner to contrast two similar operations.",
        "predict_output": "Ask the learner to predict deterministic code output.",
        "diagnose_exhaustion": "Ask the learner to reason about exhaustion or StopIteration.",
        "explain_protocol": "Ask the learner to explain the protocol behind a simple loop.",
        "transfer": "Ask the learner to transfer the idea to a related in-scope pattern.",
        "synthesize": "Ask the learner to summarize how several chapter ideas fit together.",
    }
    return f"{briefs.get(goal, 'Create a focused practice question')} Focus on {node_text}.{error_text}"


def generate_blueprint(
    chapter: dict[str, Any],
    learner: dict[str, Any],
    count: int,
) -> dict[str, Any]:
    nodes = extract_nodes(chapter)
    errors = extract_errors(chapter)
    masteries = learner_mastery(learner)
    severities = learner_severity(learner)
    level, average_mastery = infer_level(masteries, nodes)
    question_types = repeating(LEVEL_TYPE_SEQUENCES[level], count)
    difficulties = repeating(LEVEL_DIFFICULTIES[level], count)
    goals = repeating(COGNITIVE_GOALS, count)

    questions = []
    for index in range(count):
        slot = index + 1
        goal = goals[index]
        target_nodes = choose_nodes_for_goal(
            goal,
            nodes,
            masteries,
            errors,
            severities,
            slot,
        )
        target_errors = related_error_ids(errors, severities, target_nodes, slot)
        questions.append(
            {
                "slot": slot,
                "question_type": question_types[index],
                "difficulty": difficulties[index],
                "cognitive_goal": goal,
                "target_knowledge_node_ids": target_nodes,
                "target_error_ids": target_errors,
                "pedagogical_strategy": (
                    "retrieval_practice"
                    if goal in {"recognize", "retrieve"}
                    else "variation_practice"
                    if goal in {"trace_state", "predict_output", "contrast_operations"}
                    else "transfer"
                ),
                "prompt_brief": prompt_brief(goal, target_nodes, target_errors),
                "quality_checks": [
                    "student_content must not reveal reference answer",
                    "critic_content must include reference_answer and grading_rubric",
                    "question must remain inside chapter scope",
                    "reject duplicate or surface-only variants",
                ],
            }
        )

    active_errors = [
        {"error_id": error_id, "severity": severity}
        for error_id, severity in sorted(severities.items(), key=lambda item: item[1], reverse=True)
        if severity > 0.0
    ]
    return {
        "chapter_id": chapter.get("chapter_id") or chapter.get("id") or "chapter",
        "chapter_title": chapter.get("title") or chapter.get("name") or "Untitled Chapter",
        "question_count": count,
        "learner_id": learner.get("learner_id") or learner.get("id"),
        "learner_level": level,
        "average_mastery": round(average_mastery, 3),
        "active_error_priorities": active_errors,
        "core_principles": chapter.get("core_principles") or [],
        "questions": questions,
        "set_level_quality_checks": [
            "covers chapter core principles",
            "targets active learner errors",
            "orders questions from easier to harder",
            "keeps student-visible and internal fields separate",
            "keeps all questions answerable without executing student code",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", required=True, help="Path to chapter model JSON")
    parser.add_argument("--learner", required=True, help="Path to learner profile JSON")
    parser.add_argument("--count", type=int, default=10, help="Number of questions")
    parser.add_argument("--output", help="Output JSON path; stdout when omitted")
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be positive")

    blueprint = generate_blueprint(
        load_json(args.chapter),
        load_json(args.learner),
        args.count,
    )
    text = json.dumps(blueprint, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
