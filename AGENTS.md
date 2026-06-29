# PyCoach Lab 项目地图

## 目录

- `apps/web/`：React + TypeScript + Vite 学习页面。
- `services/api/`：FastAPI、双 Agent 编排、数据模型和测试。
- `curriculum/python_iterator_v1/`：迭代器课程种子数据。
- `docs/`：MVP 规范、架构、Agent 契约和测试说明。
- `PLANS.md`：分阶段实施与验收清单。

## 关键命令

```bash
conda activate langchain
make api-dev
make web-dev
make test
docker compose up --build
```

## 不可违反的约束

1. 运行时只有 Questioner 和 Critic 两个 Agent；后端不得成为第三个 Agent。
2. 所有 LLM 结构化输出必须先通过 Pydantic 2 Schema 校验。
3. 学生端只展示学生可见 Markdown，不得暴露内部 JSON、评分规则或图谱更新建议。
4. 学生只通过统一文本框交互；不得添加提交、不会、疑问或下一题业务按钮。
5. MVP 不执行学生代码，由 Critic 直接理解和评价。
6. 图谱更新仅在回合最终结束时提交，并记录可审计事件。
7. 自动化测试必须使用 MockLLMProvider，不得依赖真实模型 API。
8. 课程范围仅限 Python 可迭代对象、迭代器、`iter()`、`next()`、状态、耗尽和 `StopIteration`。
9. 不引入 Redis、Celery、Neo4j、向量数据库、多 Agent 框架或第三个运行时 Agent。

