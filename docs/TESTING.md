# 测试策略

- Schema：合法值、非法枚举、范围和必填字段。
- 状态机：合法转换、非法转换和异常状态。
- GraphService：掌握度、错误严重度边界及审计记录。
- LLM：Schema 失败重试一次、再次失败后安全回退。
- E2E：全部使用 MockLLMProvider，覆盖答错、追问、下一题和最终提交。
- 前端：Markdown、Python 代码块、键盘发送、时间线、图谱刷新、WebSocket 和内部 JSON 防泄露。

后端全量测试：

```bash
conda activate langchain
PYTHONPATH=services/api python -m unittest discover -s services/api/tests -v
```

前端测试与生产构建：

```bash
cd apps/web
npm ci
npm test
npm run build
```

前端测试使用 Vitest、jsdom 和 Testing Library，覆盖统一输入框键盘行为、Markdown/Python 高亮、时间线、图谱、REST/WebSocket 状态更新和内部 JSON 防泄露。

## Docker 和真实通信 Smoke Test

```bash
docker compose up -d --build --wait
make smoke
```

`scripts/e2e_smoke.py` 使用真实 REST 和 WebSocket，覆盖：

```text
创建会话
→ 学生答错
→ Critic 反馈
→ 学生追问
→ Critic 解释
→ 学生请求下一题
→ 图谱提交
→ 展示新题
```

脚本还会检查学生可见响应中不存在参考答案、评分标准、内部图谱更新、掌握度或错误严重度。
脚本最多等待 API 就绪 60 秒，并绕过本机 HTTP/WebSocket 代理。

## Alembic 隔离验证

迁移升降级应在临时数据库中执行，避免修改开发数据：

```text
upgrade head → downgrade base → upgrade head
```

验收标准：

- 首次 upgrade 后为 `0001 (head)`，共 14 张表；
- downgrade 后业务表为 0；
- 再次 upgrade 后回到 `0001 (head)`。
