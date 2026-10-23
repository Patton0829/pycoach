# PyCoach Lab

面向 Python 初学者的双 Agent AI 陪练 MVP。当前版本已跑通章节出题规划、Questioner 出题、Critic 审题与对话、候选题预生成、图谱更新、WebSocket 流式回复和 React 学习页面。

## 系统架构

系统由 React + TypeScript 前端、FastAPI 模块化单体和 SQLAlchemy 数据层组成，支持 MySQL / PostgreSQL。Questioner 负责生成题目，Critic 负责审题、评价、答疑和回合总结。两个 Agent 使用 LangChain Prompt / LCEL 调用链；LangGraph `StateGraph` 执行模型调用、校验、一次修复重试和失败回退。后端会话状态机负责持久化和推送，章节规划器按固定规则提供出题约束。完整模型输出通过 Pydantic 2 校验后才能保存并推进业务状态。

真实模型适配器使用 `langchain-openai.ChatOpenAI` 的异步结构化调用，并复用其配置的异步 SDK 客户端接收 SSE，保留现有 `LLM_*` 配置与 Mock Provider。模型 SDK 内部重试设为 0，由 LangGraph 统一控制最多两次尝试；工作流状态按调用隔离，最终图谱提交仍由回合结算事务完成。`asyncio` 后台审题、候选题预热与 WebSocket 推送继续使用现有调度。

当前架构图、模块职责、交互时序和数据边界见 [架构说明](docs/ARCHITECTURE.md)。Docker 部署包含 `web`、`api`、`postgres` 三个服务，Web 容器内的 Nginx 提供静态页面，并代理 REST 和 WebSocket。

## 当前课程与测试模式

| 模式 | 模块 ID | 当前行为 |
| --- | --- | --- |
| 迭代器练习 | `python_iterator` | API 保留的 10 题迭代器蓝图，覆盖可迭代对象、迭代器、`iter()`、`next()`、状态、耗尽和 `StopIteration`。 |
| 综合诊断 | `python_foundation_diagnostic` | 前端提供的 Python 教程第 3–9 章综合能力测试，规划 35 题。 |
| 章节测试 | `python_tutorial_ch3` 至 `python_tutorial_ch9` | 前端提供的分章测试，每章规划 10 题。 |
| 单题闯关 | `python_challenge_ch3` 至 `python_challenge_ch9` | 前端提供的分章闯关，逐题优先选择未掌握知识点，以章节知识点掌握情况判断完成。 |

当前代码和默认种子导入已接入 `python_iterator_v1`、`python_foundation_v1` 两套课程数据。上述基础课程扩展已超出 `AGENTS.md` 中声明的“仅迭代器”MVP 范围；此处记录实现现状，仓库约束仍以该文件为准。

## 仓库内 Skill

- [`chapter-adaptive-questioning`](skills/chapter-adaptive-questioning/SKILL.md)：章节自适应出题 Skill，用于根据章节核心知识点、用户掌握度和错误图谱生成 10 题练习蓝图，并约束题目质量、难度梯度和学生可见内容边界。
- [`python-foundation-diagnostic`](skills/python-foundation-diagnostic/SKILL.md)：Python 教程第 3–9 章综合诊断 Skill，默认设计 35 题诊断蓝图，衔接现有 Questioner/Critic 流程。

仓库内 Skill 提供可复用的设计说明；运行时章节规划由 `ChapterQuestioningService` 的固定规则实现。

## 本地环境

项目基线为 Python 3.10.19、Node.js 20、PostgreSQL 16。

首次克隆后创建后端环境：

```bash
conda create -n langchain python=3.10.19
conda activate langchain
python -m pip install -r requirements.txt
```

本地已有 `langchain` 环境时，只需激活并安装或同步依赖：

```bash
conda activate langchain
python -m pip install -r requirements.txt
```

启动后端：

```bash
make api-dev
```

数据库迁移和课程种子导入：

```bash
cd services/api
alembic upgrade head
cd ../..
make seed
```

启动前端：

```bash
cd apps/web
npm ci
npm run dev
```

`requirements.txt` 固定后端和测试工具版本；`apps/web/package-lock.json` 固定前端依赖版本。

代码默认 `LLM_PROVIDER=mock`，可使用演示 Mock 模型运行学习闭环；本地 `.env` 可覆盖该默认值。使用 OpenAI-compatible 模型时，在根目录 `.env` 配置：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-model
LLM_TIMEOUT_SECONDS=75
LLM_EXTRA_BODY=
```

阿里云百炼千问建议关闭思考模式以提高结构化 JSON 的稳定性：

```env
LLM_EXTRA_BODY={"enable_thinking":false}
```

API Key 只能写入已被 `.gitignore` 排除的 `.env`，不要写入 `.env.example`。

完整容器启动（已有 `.env` 时保留现有配置，跳过复制步骤）：

```bash
cp .env.example .env
docker compose up -d --build --wait
make smoke
```

容器启动时会自动执行 Alembic 迁移和幂等种子导入。`--wait` 会等待 PostgreSQL 和 API 健康检查通过。

学生可见图谱 API：

```text
GET /api/learners/demo_user/knowledge-graph
GET /api/learners/demo_user/error-graph
```

## 学习会话 API

查询当前支持的模块：

```text
GET /api/sessions/modules
```

创建会话时传入所选模块 ID，例如迭代器练习：

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"learner_id":"demo_user","module":"python_iterator"}'
```

会话处于可接收消息的状态时，提交学生消息会返回 `202 processing`，模型处理在后台继续：

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"next(iterator)"}'
```

前端提交消息时还会携带 UUID 格式的 `client_message_id`，用于消息关联和后端重复检查。会话处理中提交新消息会返回 `409`；这不是跨状态、跨进程的完整幂等保证。

异步结果和 Critic 学生可见文本增量通过以下 WebSocket 推送：

```text
ws://localhost:8000/ws/sessions/{session_id}
```

已知会话 ID 时，后端可查询已保存的学生可见消息、当前题目、状态和图谱摘要：

```text
GET /api/sessions/{session_id}
```

当前前端初始化时会清除浏览器中的旧会话标识并返回测试选择流程，不会在页面刷新后自动续接上一会话；已提交的个人学习画像仍从数据库加载。学习过程中前端会按需查询会话以同步状态，WebSocket 当前没有自动重连机制。

学习页面只有一个统一文本输入框：

```text
Enter          发送
Shift + Enter  换行
```

中文输入法选字期间的 Enter 只确认候选字，不会提前发送消息。输入框保持固定的舒适高度，长内容在输入框内部滚动。

前端不会渲染参考答案、评分规则、掌握度小数、错误严重度或 provisional 图谱更新。
进入下一题时，页面只保留当前题及本题对话；历史回合仍保存在数据库中，但不会继续堆叠在学习页面。
Questioner 完整生成并通过校验后一次性展示题目；Critic 的学生可见 Markdown 通过 WebSocket 增量推送。流式文本是临时预览，完整模型 JSON 结束后仍必须通过 Pydantic Schema 校验才能持久化和推进状态机；校验失败会发送重置事件，清除临时回复并重试。
下一题采用后台候选题预生成：首题创建完成后就会启动下一题预热，候选题由 Questioner 生成并经 Critic 审查。用户在反馈讨论阶段输入“下一题”后，优先发布已准备好的题并开启新回合，上一题总结、最终图谱提交和后续候选题预热在后台继续完成，因此图谱可能晚于新题展示刷新。讨论中的 provisional 证据本身不会直接修改个人图谱。

## 测试

```bash
make test
make build-web
```

启动 Docker 后执行真实通信测试：

```bash
make smoke
make stream-smoke
```

实施状态和验收步骤见 [PLANS.md](PLANS.md)。

## 当前限制

- 当前课程包含迭代器练习和 Python 教程第 3–9 章测试，尚未覆盖完整 Python 课程；课程扩展与仓库声明范围的差异见上文。
- 当前只有 `demo_user`，没有登录、注册或多用户权限。
- MVP 不执行学生代码，复杂代码答案由 Critic 直接理解和评价。
- 掌握度和错误严重度使用简单、可审计的固定增减规则。
- 后台任务、候选题生成防重状态和 WebSocket 连接运行在单个 FastAPI 进程中；服务重启时未完成的内存任务不会继续执行，当前没有跨进程任务和推送协调。
- Questioner 仍是完整题目一次性展示；Critic 回复支持 WebSocket 增量输出。
- OpenAI-compatible Provider 已实现；真实模型质量、延迟和供应商兼容性仍需要按供应商单独验证。
- 第一版没有 Redis、Celery、Neo4j、代码沙箱、登录、支付或排行榜。
