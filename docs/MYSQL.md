# MySQL 与评估数据迁移

后端通过 SQLAlchemy 同时支持 MySQL 和 PostgreSQL。MySQL 使用 PyMySQL 驱动，推荐使用支持 CHECK 约束的 MySQL 8.0.16 或更新版本。开发和自动化测试仍可使用 SQLite；不需要 Redis、图数据库或额外运行时 Agent。

## 本机 MySQL

为应用准备独立的数据库和账号，数据库字符集使用 `utf8mb4`。在项目根目录的 `.env` 中设置自己的连接信息：

```dotenv
DATABASE_URL=mysql+pymysql://pycoach:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:3306/pycoach?charset=utf8mb4
LLM_PROVIDER=mock
```

密码中的 `@`、`%`、`/` 等字符必须进行 URL 编码；不要把密码提交进仓库。已有 `.env` 不会被迁移工具改写。

```bash
conda activate langchain
python -m pip install -r requirements.txt
cd services/api
python -m alembic upgrade head
```

然后从项目根目录执行 `make seed`、`make api-dev`。现有 Docker Compose 仍提供 PostgreSQL；本机 API 使用上述 MySQL 连接即可。若 API 在 Docker Desktop 容器中运行，访问本机数据库时使用 `host.docker.internal`，并为该连接配置合适的数据库权限。

更换连接字符串不会复制原 PostgreSQL 数据。已有数据需要单独进行跨数据库导入；Alembic 负责目标数据库的结构升级。

## 0003 数据结构

- `curriculum_chapters` 与 `knowledge_nodes.chapter_id`：课程目录及知识点章节归属。
- `source_documents`：PDF 来源、样题/历年卷类型、年份、页数、文件指纹。
- `bank_questions`：稳定原题身份和原卷题号。
- `bank_question_revisions`：版本化题面、内部答案、难度、教学标注、来源页码和规范化记录。
- `question_knowledge_mappings`：评估目标与前置知识的关联。
- `assessment_evidence`：回合最终结算的逐知识点评估、辅助情况、重复题情况、计数决定和原因。
- `questions.bank_question_revision_id`：将会话题目快照关联到当时使用的真题版本。
- `learner_knowledge_nodes`：新增有效评估题数、正确题数和评分规则版本。
- `graph_update_events`：保留计分前后的题数、正确数及其评估证据引用。

同一回合、同一知识点的证据唯一。计入统计的稳定题目身份使用唯一哈希键；被排除的记录使用空键，可保存多条复习或提示记录。原题文字修订不会变成一条新的原题身份。

## 20 题规则及旧数据

规则版本为 `correct_over_max_20_v1`。设 N 为有效评估题数，C 为正确题数：

```text
assessment_score = C / max(20, N)
accuracy = C / N                    # N=0 时为空
sample_coverage = min(N / 20, 1)
```

N、C 达到 20 后继续累加。只在回合最终结束后，连同评估证据和审计事件一起提交计数变化。

旧版 `attempt_count` 和正负证据次数并不等于独立题目数与正确题数。0003 不会将这些值冒充 N、C：

1. 保存原画像到 `legacy_mastery`、`legacy_status`。
2. 新 N、C 从零开始，`mastery` 回到 0，状态为 `not_started`；此时表示新规则尚未测评。
3. 保留原消息、旧证据计数和审计记录。
4. 回退到 0002 时恢复保存的旧画像；0003 新增题库及评估明细表会被移除。

升级前应按常规流程备份数据库。`alembic upgrade head` 重复执行不会重新清零已升级后的记录。

MySQL 的正文列使用 LONGTEXT、分数列使用 DOUBLE、时间列保留微秒精度，防止同一秒内的讨论消息顺序丢失。已有 MySQL 时间和正文列也由 0003 升级到相应存储类型。

## 测试

```bash
conda activate langchain
make test-api
```

常规测试验证 SQLite 全新升级、旧画像保留、回退、再次升级、数据库约束及 MySQL DDL。模型调用使用 MockLLMProvider，不依赖真实模型 API。

真实 MySQL 迁移测试通过 `TEST_MYSQL_URL` 开启。请在本地环境配置该变量，使用有创建数据库权限的测试账号，然后运行：

```bash
PYTHONPATH=services/api python -m unittest services/api/tests/test_database_migrations.py -v
```

测试忽略 URL 中指定的现有数据库，始终创建随机 `pycoach_test_<uuid>` 数据库，执行升级与回退后清理该测试数据库。未提供 `TEST_MYSQL_URL` 时仅跳过真实 MySQL 用例。

真实 MySQL 的题库与评估集成测试也复用同一个变量：

```bash
PYTHONPATH=services/api python -m unittest services/api/tests/test_mysql_integration.py -v
```

该测试覆盖中文题库内容、20 题边界、重复题、并发评估及 Mock 学习回合，并使用独立随机测试库。

## 题库结构与本地管理

当前实现包括数据结构、回合评估、本地题库管理和学生真题测试。AI 练习使用现有 Questioner 出题；真题测试按个人画像、题目难度和历史作答检索已审核的原题，由 Critic 评价。当前检索使用 MySQL 结构化数据，未新增通用 PDF 自动解析、embedding 或向量检索服务。

0004 为章节增加 `reference_url`，为知识点增加 `reference_url`、`reference_section`、`is_supplementary` 和 `runtime_enabled`。章节以 `curriculum/python_tutorial_catalog.json` 中的 Python 官方教程第 1～16 章为依据；项目细分的知识点记录对应小节。教程未直接覆盖的 IPO、turtle 等概念明确标注为补充专题。已有知识点 ID 和个人学习进度保持不变。

题库内容审核与 AI 课程启用分别判断。`approved` 表示题面、答案与知识点映射已审核；普通题库服务仍保留迭代器范围限制。用户明确选择的“真题测试”使用独立的已审核题库池，可以覆盖整份试卷。为全卷映射而新增的目录知识点默认 `runtime_enabled=false`，不会进入普通 Questioner 的课程上下文；学生完成这些知识点的有效评估后，相关掌握记录会显示在其个人知识图谱中。

从项目根目录执行以下命令。`schema` 不连接数据库；其余命令使用 `.env` 的 `DATABASE_URL`。

```bash
PYTHONPATH=services/api python -m app.question_bank_cli schema
PYTHONPATH=services/api python -m app.question_bank_cli import-json 'python考试真题/结构化示例/前三题.json'
PYTHONPATH=services/api python -m app.question_bank_cli query --node python.iterator.state --min-difficulty 1 --max-difficulty 3
```

该导入命令兼容本次提供的前三题示例和原生题库 JSON。前三题不属于当前迭代器课程，因此保持 `draft`，保留原题、标签、答案来源和规范化记录；候选题查询只返回审核通过且具有合法课程评估目标的题目。

原生 JSON 可以通过 `knowledge_mappings` 指定 `assessed` 评估目标和 `prerequisite` 前置背景，字段契约以 `schema` 命令输出为准。审核使用：

```bash
PYTHONPATH=services/api python -m app.question_bank_cli review REVISION_ID approved
```

这是本地管理命令，内部答案和评分材料不通过学生 API 暴露。发布后题面或答案的修改应创建新版本，不能覆盖历史作答使用的版本。

## 全卷审核与五星展示

```bash
python scripts/review_python_exam.py
PYTHONPATH=services/api python -m app.question_bank_cli import-json 'python考试真题/结构化真题/ncre-python-sample/bank_import.reviewed.json'
```

审核脚本根据固定 PDF 指纹、逐题审核标注和官方教程目录生成 36 题的审核版本、审核报告、可读 HTML 及题面/内部答案分别存放的检索资料。各题独立保留版本号，原始提取文件和历史版本保留。缺失答案的第 31～36 题使用项目补充参考答案；第 15 题保留原卷 B，并将纠错后的 C 单独标明来源。含无法唯一判分问题的原题记录为 `invalid`，不进入审核后的默认检索资料。

数据库难度仍存 1～5 的整数。学生页面通过公开字段 `question_metadata` 接收难度、知识点名称及来源摘要，以五颗实心星展示：前 N 颗金黄色，其余灰色。REST 历史消息、当前题目和 WebSocket 新题均使用同一公开字段契约；内部答案、评分依据、文件路径和指纹不进入该契约。

学生从侧栏“真题测试”选择试卷开始，页面通过 `GET /api/exams` 读取实际可用题数与排除题数，再以 `module=python_exam_practice` 和可选 `source_document_id` 创建学习会话。会话固定当时审核题库池，出题前再次检查最新审核状态；同一会话不会重复原题。下一题在上一回合评估提交后选择，题库耗尽即完成测试，不回退到生成题。作答、追问、“下一题”和结束测试均沿用统一文本框。
