# PyCoach Lab MVP 实施计划

## 执行原则

- 每个阶段均以可运行、可测试、可验收为完成标准。
- 优先完成 Mock LLM 驱动的最小学习闭环，再接真实 OpenAI-compatible 模型。
- 阶段未通过对应测试前，不进入依赖该阶段的产品扩展。
- 当前仓库骨架完成情况使用 `[x]` 标记；待实现项使用 `[ ]` 标记。

## Phase 1：项目基础架构

目标：建立前后端、数据库、容器和本地开发入口。

- [x] FastAPI 应用与 `/health` 健康检查
- [x] React + TypeScript + Vite 页面骨架
- [x] PostgreSQL 与 Docker Compose 服务定义
- [x] SQLAlchemy 2、Alembic 配置和首个迁移骨架
- [x] OpenAICompatibleLLMProvider 与 MockLLMProvider 接口
- [x] `.env.example`、Makefile、README 和基础测试入口
- [x] 统一 Python 3.10.19 项目基线并提供 `requirements.txt`
- [x] 前端依赖锁文件和生产构建验证
- [x] 容器按项目依赖完成安装并执行 Alembic `0001` 迁移
- [x] 验证 `docker compose up --build` 三服务联通

验收：

```bash
docker compose up --build
curl http://localhost:8000/health
```

验收结果（2026-06-23）：

- `web`、`api`、`postgres` 三个容器均正常运行。
- PostgreSQL 健康检查为 `healthy`。
- `/health` 返回 `{"status":"ok","service":"pycoach-api"}`。
- Alembic 当前版本为 `0001 (head)`。
- 数据库已创建 13 张业务表及 `alembic_version` 表。
- Phase 1 验收通过，可以进入 Phase 2。

## Phase 2：知识图谱数据层

目标：初始化全局图谱、个人状态和错误图谱。

- [x] 课程节点、关系和错误类型 JSON 种子文件
- [x] 任务书要求的数据库实体定义
- [x] 实现种子导入命令并保证幂等
- [x] 初始化 `demo_user`
- [x] 实现个人知识图谱与错误图谱 Repository/Service
- [x] 实现两个只读图谱 API
- [x] 增加图谱更新审计测试

验收：可查询 `demo_user` 的个人知识图谱和错误图谱，返回学生可见状态名称且无精确小数泄露。

验收结果（2026-06-23）：

- 启动时自动导入 10 个知识节点、10 条关系和 9 个错误类型。
- 初始化 1 个 `demo_user`、5 条个人知识状态和 1 条活跃错误记录。
- 重复执行 `python -m app.seed` 后记录数量不变，且不会覆盖已有个人学习进度。
- 两个图谱 API 在真实 PostgreSQL 上返回 `200`，未知学习者返回 `404`。
- 学生可见响应只包含状态名称，不包含 `mastery`、`severity` 或内部图谱 JSON。
- 图谱更新公式和 `graph_update_events` 审计记录已由自动化测试覆盖。
- 后端共 14 个测试通过，Phase 2 验收通过。

## Phase 3：Questioner

目标：从学习状态生成严格合法的 QuestionPacket。

- [x] QuestionPacket Pydantic Schema
- [x] Questioner Prompt 文件占位与职责边界
- [x] 构建 Questioner 输入上下文
- [x] 实现结构化调用、校验失败重试一次
- [x] 实现四种题型种子题回退
- [x] 实现相邻题去重与题型比例约束

验收：Mock LLM 和失败回退均能返回合法 QuestionPacket。

验收结果（2026-06-23）：

- `QuestionContextBuilder` 可从数据库构建全局图谱、个人图谱和错误图谱输入。
- Questioner 输入与输出均经过严格 Pydantic Schema 校验。
- 非法 Schema、错误题型、未知节点、超长代码和重复题均触发一次修正重试。
- 完全重复及只替换数字或变量名的表面变体均会被拒绝。
- 连续两次失败后，从四种题型的种子题库选择合法回退题，并生成新的题目 UUID。
- 题型调度以 40% / 35% / 15% / 10% 为目标比例。
- Mock LLM 自动化测试覆盖正常生成、重试、语义去重和回退。
- 后端共 22 个测试通过，Phase 3 验收通过。

## Phase 4：Critic 审题

目标：题目展示给学生的同时，Critic 并行审题。

- [x] QuestionReview Pydantic Schema
- [x] 实现异步审题
- [x] 实现 `approved`、`needs_revision`、`invalid` 分支
- [x] 实现学生作答前后两种无效题处理

验收：歧义题和无效题不产生学生图谱惩罚。

验收结果（2026-06-23）：

- 题目可先投影给学生，Critic 审题任务在后台并行执行。
- 审题输入包含完整 QuestionPacket、目标知识点、期望难度和近期题目。
- QuestionReview 强制 Pydantic 校验，非 approved 状态必须给出 issue。
- Schema 失败会携带校验错误重试一次；连续失败后暂停可靠评价且禁止图谱更新。
- approved、needs_revision、invalid 三种状态均有固定后端处理决策。
- 无效题在学生作答前会直接替换；作答后会说明问题、禁止图谱更新并替换。
- 有效审题结果写入 `question_reviews`，同时更新题目状态。
- 自动化测试覆盖歧义题、无效答案、并行审题、重试和持久化。
- 后端共 28 个测试通过，Phase 4 验收通过。

## Phase 5：Critic 对话控制

目标：所有学生自由输入均由 Critic 结合状态和上下文处理。

- [x] CriticTurnResult、DiscussionSummary 和图谱更新 Schema
- [x] 实现 13 类意图的结构化识别
- [x] 实现做题阶段提示、评价和复合输入
- [x] 实现反馈阶段追问、举例、质疑和纠错
- [x] 实现 Schema 失败重试与安全回退

验收：任务书意图测试集在 `QUESTION_ACTIVE` 和 `FEEDBACK_DISCUSSION` 下全部覆盖。

验收结果（2026-06-23）：

- `CriticTurnContext` 包含当前状态、完整题目、审题结果、回合历史、当前消息和候选题状态。
- 13 类意图均可通过严格 Schema；任务书给出的 12 条输入已分别在两种状态下覆盖，共 24 个上下文意图用例。
- 做题阶段覆盖答案评价、不确定、作答前提示和“答案+问题”复合输入。
- 反馈阶段覆盖继续追问、请求示例、确认、下一题和质疑改判。
- 质疑导致诊断变化时会标记候选题失效。
- “我不确定”不能生成具体负面知识证据或激活具体错误。
- CriticTurnResult 和 DiscussionSummary 均支持 Schema 失败重试一次。
- 连续失败后返回固定安全回复，verdict 为 `critic_uncertain`，图谱更新为空。
- DiscussionSummary 支持 original/final verdict、诊断变更和最终图谱建议。
- 后端共 38 个测试通过，Phase 5 验收通过。

## Phase 6：会话编排

目标：跑通含追问、候选题和最终图谱提交的完整回合。

- [x] 会话与候选题状态枚举
- [x] 确定消息通信契约：POST 返回 202，结果通过 WebSocket 推送
- [x] 建立 WebSocket 连接管理器和学生可见事件 Schema 骨架
- [x] 实现状态机合法转换
- [x] 保存 provisional 更新但不立即提交
- [x] 首次评价后异步预生成候选题
- [x] 诊断变化时使候选题 stale 并重生成
- [x] 回合结束生成 DiscussionSummary 并提交审计事件
- [x] 将 Critic、Questioner 后台任务接入 WebSocket 事件

验收：Mock LLM 端到端流程从创建会话运行至下一题展示。

验收结果（2026-06-23）：

- `POST /api/sessions` 已实现首题生成、回合持久化和后台并行审题。
- 学生消息保存后立即返回 `202 processing`，Critic 结果通过 WebSocket 推送。
- provisional 图谱建议保存在 CriticTurnResult 中，回合结束前不会修改个人图谱。
- 首次评价后生成 `candidate_provisional` 候选题。
- 质疑改判会将候选题标记为 stale，发送 `candidate_question_stale` 并重新生成。
- “下一题”会生成 DiscussionSummary、事务提交图谱更新和审计事件，再展示新题。
- 无效题不会提交图谱更新，并生成替代题。
- Questioner 只接收 Critic 结构化结果或 DiscussionSummary，不接收学生原始讨论。
- `GET /api/sessions/{id}` 支持断线恢复，且不暴露 critic_content、评分规则或内部更新 JSON。
- FastAPI TestClient 已验证 REST `202` 与 WebSocket 的 `critic_reply_ready`、`candidate_question_ready`、`session_summary_ready`、`question_ready` 事件。
- Mock LLM 端到端测试覆盖：创建会话 → 答错 → 反馈 → 追问 → 解释 → 下一题 → 图谱提交 → 新题。
- 本地后端共 45 个测试通过，并验证连续完成 10 个学习回合后仍保持 `QUESTION_ACTIVE`。
- 本阶段功能随后在 Phase 8 的 Docker 冷启动与真实 REST/WebSocket Smoke Test 中完成最终镜像复验。

## Phase 7：前端学习页面

目标：提供无内部 JSON、无业务按钮的单页学习体验。

- [x] 双栏布局、消息时间线和统一输入框骨架
- [x] Enter 发送、Shift+Enter 换行交互
- [x] 个人知识图谱和错误图谱列表骨架
- [x] 接入 Markdown 渲染和 Python 代码高亮骨架
- [x] 接入 Session API 和 WebSocket
- [x] 根据状态切换 placeholder
- [x] 增加前端组件测试与内部 JSON 防泄露测试

验收：学生仅通过文本框完成答题、追问和切题。

验收结果（2026-06-24）：

- 页面启动时创建或恢复 `demo_user` 学习会话，并保存 session ID 用于刷新恢复。
- 学生消息采用乐观渲染，REST 返回 `202` 后等待 WebSocket 的 Critic 回复。
- 接入 `critic_reply_ready`、`candidate_question_ready`、`candidate_question_stale`、`question_invalid`、`session_summary_ready` 和 `question_ready`。
- 回合完成后自动刷新个人知识图谱、错误图谱和完成题数。
- 做题阶段与反馈讨论阶段使用不同 placeholder。
- 页面仍只有统一文本输入框，不存在提交、不会、疑问或下一题按钮。
- Markdown 和 Python 代码高亮已接入真实消息时间线。
- 前端 DTO 只声明学生可见字段，源码不引用参考答案、评分规则、mastery、severity 或 provisional 更新。
- 5 个前端测试文件、7 个测试全部通过。
- 前端 TypeScript 检查和 Vite 生产构建通过。
- Docker Web 镜像改用 `package-lock.json` + `npm ci`，构建上下文排除本地 `node_modules` 和 `dist`。
- Docker 中 web、api、postgres 三服务正常运行；前端首页、健康检查和真实创建会话 API 均返回 `200`。
- Phase 7 验收通过。

## Phase 8：测试与交付

- [x] 后端单元、集成、Mock LLM E2E 全部通过
- [x] 前端组件和交互测试全部通过
- [x] Alembic 升降级验证通过
- [x] Docker Compose 冷启动验证通过
- [x] README 与实际命令一致
- [x] 记录已知限制和未验证项

当前验收结果（2026-06-24）：

- 后端 45 个测试通过，覆盖 Schema、图谱、Questioner、Critic、状态机、REST/WebSocket 和连续 10 回合。
- 前端 5 个测试文件、7 个测试通过。
- Ruff、Python 编译、`pip check`、课程 JSON 和 Compose 配置检查通过。
- `npm ci`、TypeScript、Vite 生产构建通过，npm 审计为 0 个漏洞。
- Alembic 在隔离数据库完成 `upgrade head → downgrade base → upgrade head`。
- 首次 upgrade 创建 13 张业务表及 `alembic_version`，downgrade 后业务表为 0，最终回到 `0001 (head)`。
- 新增 `scripts/e2e_smoke.py`，用于真实 REST + WebSocket 完整回合复验和学生可见数据防泄露检查。
- Docker Compose 冷启动成功，`postgres` 和 `api` 健康检查均通过，`web` 正常运行。
- Smoke Test 已通过：创建会话 → 答错 → Critic 反馈 → 追问 → 下一题 → 图谱提交 → 展示新题。
- Smoke Test 会等待 API 就绪并绕过本机代理；Compose 中的 `web` 会等待 `api` 健康后再启动。
- Phase 8 验收通过。

## 当前环境说明

- 经项目决策，Python 运行基线统一为本地 `langchain` Conda 环境的 Python 3.10.19。
- 后端依赖由根目录 `requirements.txt` 固定版本；前端依赖由 `apps/web/package-lock.json` 固定版本。
- Phase 1 至 Phase 8 已全部实现并验收。
