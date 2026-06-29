# Question Quality Rubric

Use this rubric before accepting any generated chapter question set.

## Reject A Question If

- It tests a concept outside the requested chapter scope.
- It has no single defensible answer or answer family.
- It relies on hidden assumptions not visible in the prompt.
- It asks for "which option" but does not include visible options.
- It is a duplicate or a surface rewrite of a recent question.
- The code is too long for the intended difficulty.
- The reference answer disagrees with the code.
- It leaks grading rules or reference answers in student-visible text.

## Multiple Choice Requirements

- Include exactly four options unless the user asks otherwise.
- Label options A, B, C, and D.
- Make distractors plausible and tied to known error types.
- Avoid joke options or obviously impossible distractors.

## Code Question Requirements

- Prefer short code blocks.
- Use deterministic code only.
- Do not require executing student code.
- Keep variable names descriptive but not answer-revealing.
- For output prediction, state whether exceptions should be named.

## Set-Level Coverage

A 10-question set should include:

- recognition of chapter vocabulary
- one-step application
- state tracing
- output prediction
- error diagnosis
- short explanation
- transfer to a related but in-scope pattern

## Difficulty Signals

- Difficulty 1: vocabulary, one API call, single concept.
- Difficulty 2: simple state trace, two calls, one common misconception.
- Difficulty 3: multi-step trace, exhaustion, or contrast between two objects.
- Difficulty 4: exception handling, for-loop protocol expansion, transfer.
- Difficulty 5: compact synthesis across several chapter principles.

## Final Review Checklist

- Every core principle appears at least once.
- Active high-severity errors are targeted.
- Questions are ordered from easier to harder unless the user asks for random order.
- There is no answer leakage in `student_content`.
- Every item can be graded by `critic_content`.
