---
name: python-foundation-diagnostic
description: Generate adaptive baseline diagnostics for Python Tutorial chapters 3-9. Use when the user asks for a Python-wide placement test, new-learner baseline, overall Python mastery diagnosis, or a skill that creates structured diagnostic question sets across Python basics, control flow, data structures, modules, I/O, exceptions, and classes.
---

# Python Foundation Diagnostic

## Purpose

Create Python-wide diagnostic question sets for chapters 3-9 of the official Python Tutorial. Treat this as a reusable question-design skill and artifact generator that feeds the existing Questioner/Critic flow; do not add a third runtime Agent.

Default output is 35 questions: 7 chapters x 5 core knowledge nodes. Use another count only when the user explicitly requests it.

## Hard Rules

- Use chapters 3-9 only unless the user explicitly expands scope.
- Keep student-visible markdown separate from internal reference answers, rubrics, and graph updates.
- Emit or design structured QuestionPacket-compatible items.
- Make the set diagnostic, not just practice: every chapter must have enough signal to estimate mastery.
- Include direct mappings from each question to knowledge node IDs and likely error IDs.
- Let Critic update mastery and error nodes only at round finalization.
- Do not execute student code.

## Workflow

1. Read `references/python-tutorial-3-9-map.md` when designing or reviewing the diagnostic blueprint.
2. Build a learner profile from available graph data:
   - mastery by node
   - active error severity
   - recent attempts
   - inferred level: novice, intermediate, advanced
3. Create the diagnostic blueprint:
   - 5 slots per chapter
   - one primary knowledge node per slot
   - mixed question types: multiple choice, code blank, output prediction, short explanation
   - early recognition and simple application, then tracing, debugging, transfer, and explanation
4. Generate each item as student-visible content plus Critic-only grading material.
5. Review the complete set for coverage, answerability, non-duplication, and scope.

## Diagnostic Shape

For each chapter, cover:

1. a concept recognition question
2. a small code-completion question
3. an output-prediction or execution-trace question
4. a common misconception or edge-case question
5. a short explanation or transfer question

For novices, prefer shorter code, single-step reasoning, and explicit options. For intermediate learners, mix two-step traces and concise explanations. For advanced learners, use edge cases, API boundaries, namespace reasoning, exception flow, and class/instance lookup.

## Scoring Guidance

Summarize results by chapter and node:

- Correct: positive evidence, strengthen mastery.
- Partially correct: weak positive evidence, keep the node in learning status.
- Incorrect or uncertain: negative evidence, activate or strengthen the related error type.
- Repeated failures in prerequisite nodes should lower confidence in downstream nodes.

The diagnostic result should report an overall level and chapter-level gaps, but the student should see only learner-friendly feedback.
