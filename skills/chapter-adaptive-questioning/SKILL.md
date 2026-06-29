---
name: chapter-adaptive-questioning
description: Generate high-quality adaptive question sets for a learning chapter. Use when the user asks to create, design, evaluate, or plan chapter-based practice questions, quizzes, drills, or a "skill" for topics such as Python iterators, where questions must align to chapter core ideas, learner level, knowledge graph state, error patterns, and structured QuestionPacket-style outputs.
---

# Chapter Adaptive Questioning

## Purpose

Create chapter-level adaptive practice sets without modifying product runtime code. Treat this as a reusable question-design skill and artifact generator, not as a third Agent or service module.

Default output is a 10-question set unless the user requests another count.

## Hard Rules

- Do not edit `apps/` or `services/` unless the user explicitly asks to integrate generated artifacts.
- Do not create a third runtime Agent. Use this skill as an offline/planning capability that supports an existing Questioner flow.
- Separate student-visible content from internal critic content.
- Generate from chapter core principles first, not from random variable/name substitutions.
- Validate every question for answerability, chapter scope, difficulty fit, and non-duplication.

## Workflow

1. Build a chapter model:
   - core principles
   - knowledge nodes
   - concept dependencies
   - typical error types
   - canonical code patterns
   - seed examples, if available

2. Build a learner profile:
   - mastery by knowledge node
   - active error severity
   - recent questions and attempts
   - inferred level: novice, intermediate, or advanced

3. Create a question blueprint before writing questions:
   - target knowledge node per slot
   - target error type per slot
   - question type
   - difficulty
   - cognitive goal
   - pedagogical strategy

   When structured chapter and learner JSON are available, run:

   ```bash
   python scripts/generate_blueprint.py --chapter chapter.json --learner learner.json --count 10 --output blueprint.json
   ```

4. Generate each question as a structured packet:
   - student-visible markdown
   - input hint
   - reference answer
   - acceptable answers
   - grading rubric
   - expected reasoning
   - knowledge node IDs
   - target error IDs

5. Review the set:
   - no out-of-scope concepts
   - no duplicate or variable-renamed questions
   - multiple choice questions include complete A/B/C/D options
   - code fits the intended difficulty
   - every item has a clear answer and grading rubric
   - the set covers recognition, application, tracing, explanation, and transfer

## Adaptive Difficulty

Use learner mastery and error severity to shape the set:

- Mastery below 0.35: emphasize recognition, simple code blanks, and single-step tracing.
- Mastery 0.35 to 0.70: mix code blanks, output prediction, state tracing, and explanation.
- Mastery above 0.70: emphasize multi-step tracing, edge cases, exceptions, protocol transfer, and concise explanations.

If an error type has high severity, add at least one question targeting it. Prefer active errors over already resolved errors.

## Recommended 10-Question Shape

For Python iterator chapters:

1. iterable vs iterator recognition
2. `iter()` creation / identity
3. `next()` retrieval
4. iterator state after one or two calls
5. repeated `iter(obj)` vs repeated `next(it)`
6. output prediction with exhaustion
7. `StopIteration` handling
8. for-loop protocol mapping
9. generator as iterator source
10. transfer or short explanation tying the chapter together

Adjust the shape to the learner profile; do not force advanced topics for a novice.

## References

- Read `references/output-contracts.md` when producing structured question packets.
- Read `references/quality-rubric.md` when reviewing or improving a question set.
- Read `references/python-iterator-chapter.md` when the chapter is Python iterators and no richer chapter source is provided.
