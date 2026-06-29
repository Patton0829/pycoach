# 架构

```text
React Web
  │ REST / WebSocket
FastAPI Orchestrator
  ├── Questioner ── LLMProvider
  ├── Critic ────── LLMProvider
  ├── Pydantic output validation
  └── SQLAlchemy repositories ── PostgreSQL
```

后端不判断答案。Questioner 与 Critic 的模型输出先进入 Pydantic Schema；校验成功后才能改变会话状态或形成 provisional 更新。图谱更新仅在 Critic 最终总结后由 GraphService 提交并写入审计事件。

学生端 DTO 必须单独定义，只包含消息 Markdown、学生可见图谱摘要和会话状态，禁止直接序列化 Agent 内部结果。

## 前后端通信决策

采用异步 REST + WebSocket：

```text
学生按 Enter
  ↓
POST /api/sessions/{session_id}/messages
  ↓ 202 Accepted
前端立即显示学生消息和“Critic 正在思考”
  ↓
FastAPI 后台调用 Critic、校验 Schema、保存结果
  ↓
WebSocket: critic_reply_ready
  ↓
前端显示 Critic 的完整回复
```

- REST 用于创建会话、提交命令、查询会话和断线恢复。
- WebSocket 用于 Questioner/Critic 后台任务完成后的主动推送。
- 浏览器不直接连接 LLM，也不直接连接 Questioner 或 Critic。
- WebSocket 只推送学生可见 DTO，禁止携带参考答案、评分规则、推理过程或图谱更新建议。
- 第一版按完整消息推送，不实现逐 token 流式输出。
- 客户端可传 `client_message_id`，后续用于幂等提交和重连去重。

## 会话编排

`LearningSessionOrchestrator` 是非 Agent 的确定性编排层。它只执行固定状态转换、调用两个 Agent、Schema 校验、持久化和事件推送，不重新判断题目或答案。

```text
POST /api/sessions
  → Questioner 生成正式题
  → 保存 session / round / question / questioner message
  → 返回 QUESTION_ACTIVE
  → 后台 Critic 审题

POST /api/sessions/{id}/messages
  → 保存 student message
  → 返回 202 CRITIC_PROCESSING
  → 后台 CriticTurnResult
  → 保存 provisional evidence
  → WebSocket critic_reply_ready
```

首次答案评价后，Questioner 根据 Critic 的结构化结果生成候选题。候选题保存在 `questions` 表，通过 `candidate_provisional`、`candidate_ready`、`candidate_stale` 和 `candidate_failed` 状态管理。

学生请求下一题时：

1. Critic 生成 `DiscussionSummary`。
2. 后端在事务中提交 final graph updates 和审计事件。
3. provisional evidence 本身不直接修改个人图谱。
4. 诊断变化时使旧候选题 stale，并只将 Critic 总结发送给 Questioner 重新生成。
5. 候选题绑定到新回合并通过 `question_ready` 推送。

页面刷新或 WebSocket 重连后，前端通过 `GET /api/sessions/{id}` 恢复学生可见消息、当前题目和图谱摘要。
