# Output Contracts

Use these contracts for chapter-adaptive question generation artifacts. Field names are intentionally compatible with PyCoach-style `QuestionPacket` outputs, but this skill is not runtime application code.

## Chapter Model

```json
{
  "chapter_id": "python_iterator",
  "title": "Python 迭代器",
  "core_principles": [
    "可迭代对象可以传给 iter()",
    "迭代器保存消耗状态",
    "next() 返回当前元素并推进状态"
  ],
  "knowledge_nodes": [
    {
      "id": "python.iterator.next",
      "name": "next()",
      "difficulty": 2,
      "learning_objective": "Use next() on an iterator."
    }
  ],
  "knowledge_edges": [
    {
      "source_node_id": "python.iterator.next",
      "target_node_id": "python.iterator.exhaustion",
      "relation_type": "prerequisite_of"
    }
  ],
  "error_types": [
    {
      "id": "iter_vs_next",
      "name": "iter 与 next 混淆",
      "related_knowledge_nodes": ["python.iterator.iter", "python.iterator.next"]
    }
  ],
  "seed_questions": []
}
```

## Learner Profile

```json
{
  "learner_id": "demo_user",
  "knowledge_graph": [
    {
      "node_id": "python.iterator.next",
      "mastery": 0.42,
      "status": "learning"
    }
  ],
  "error_graph": [
    {
      "error_id": "iter_vs_next",
      "severity": 0.7,
      "status": "active"
    }
  ],
  "recent_questions": []
}
```

## Question Blueprint

Generate the blueprint before writing final questions.

```json
{
  "slot": 1,
  "question_type": "multiple_choice",
  "difficulty": 1,
  "cognitive_goal": "recognize",
  "target_knowledge_node_ids": ["python.iterable", "python.iterator"],
  "target_error_ids": ["iterable_vs_iterator"],
  "pedagogical_strategy": "retrieval_practice",
  "prompt_brief": "Ask the learner to distinguish an iterable object from an iterator.",
  "quality_checks": []
}
```

## Question Packet

Each generated question should follow this structure:

```json
{
  "question_id": "uuid",
  "question_type": "multiple_choice | code_blank | output_prediction | short_explanation",
  "difficulty": 1,
  "knowledge_node_ids": ["python.iterator.next"],
  "target_error_ids": ["iter_vs_next"],
  "pedagogical_strategy": "retrieval_practice",
  "student_content": {
    "markdown": "student-visible question markdown",
    "input_hint": "short student-facing hint"
  },
  "critic_content": {
    "learning_objective": "internal learning objective",
    "reference_answer": "internal answer",
    "acceptable_answers": ["equivalent answer"],
    "grading_rubric": {
      "correct": "criteria",
      "partial": "criteria",
      "incorrect": "criteria"
    },
    "expected_reasoning": "internal reasoning",
    "ambiguity_notes": null
  }
}
```

Student-visible output must only include `student_content`. Keep `critic_content` internal.
