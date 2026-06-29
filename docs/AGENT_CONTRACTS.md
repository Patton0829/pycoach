# Agent 契约

## Questioner

输入为全局图谱、个人图谱、错误图谱、近期题目与尝试、Critic 总结、教学策略和候选题约束。输出必须符合 `QuestionPacket`。

Questioner 输入先由 `QuestionContextBuilder` 从数据库和当前回合摘要构建，并通过 `QuestionerContext` 校验。输出处理顺序：

1. Pydantic 校验 `QuestionPacket`。
2. 检查题型、知识点、错误类型、代码行数和近期重复。
3. 失败时将具体错误反馈给 Questioner，并重试一次。
4. 再次失败时从四种题型的种子题库中选择合法回退题。

题型调度按选择题 40%、代码填空 35%、输出预测 15%、简短概念题 10% 的目标比例选择当前欠采样题型。重复检查同时拦截完全相同内容，以及只替换数字或变量名的表面变体。

## Critic

Critic 有三个结构化任务：

1. 题目审查，输出 `QuestionReview`。
2. 每条学生消息处理，输出 `CriticTurnResult`。
3. 回合结束总结，输出 `DiscussionSummary`。

只有 `student_content.markdown` 和 `student_visible_reply_markdown` 可直接进入学生消息流。参考答案、评分标准、推理、图谱建议和讨论总结均为内部数据。

### 审题处理

Questioner 生成题目后，后端立即向学生投影 `student_content`，同时通过 `CriticQuestionReviewService.start_review()` 启动后台审题。Critic 接收完整题目包、目标知识点、期望难度和近期题目。

- `approved`：题目继续使用。
- `needs_revision`：题目继续使用，`grading_notes` 仅供 Critic 内部评分参考。
- `invalid` 且学生未作答：撤销并生成替代题。
- `invalid` 且学生已作答：向学生说明题目有问题，不提交图谱更新，并生成替代题。
- Schema 连续两次无效：暂停当前题的可靠评价，不更新图谱，等待重新审题。

后端只执行上述固定状态动作，不重新判断题目内容或学生答案。

### 对话控制

每条学生消息与当前状态、完整题目、审题结果、当前回合历史和上一次 Critic 结果一起组成 `CriticTurnContext`。Critic 输出 `CriticTurnResult`，后端只校验结构和状态动作是否一致。

- `QUESTION_ACTIVE` 下，作答进入反馈，作答前提问保持当前题目并优先给提示。
- `FEEDBACK_DISCUSSION` 下，追问、举例、延伸和质疑均留在当前回合。
- 质疑导致改判时，Critic 必须标记候选题失效。
- “下一题”生成 `finalize_round`，但正式提交图谱更新由 Phase 6 编排器执行。
- “我不确定”不能被转换为具体负面错误证据。
- Critic 不可靠、题目无效或结果不适用时，图谱更新列表必须为空。

Critic 输出 Schema 失败时携带错误重试一次。连续失败后返回固定学生可见回复：

```text
我暂时无法可靠判断这次回答，我们不更新你的学习记录。请重新发送一次。
```

回合结束时，Critic 根据完整回合生成 `DiscussionSummary`。只有最终确认的证据可以进入 final updates；Questioner 只接收 `next_question_guidance` 等总结，不接收全部对话原文。
