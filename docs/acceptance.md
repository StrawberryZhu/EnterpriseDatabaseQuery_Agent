# InsightForge Agent v0.2.0 交付验收报告

## 1. 验收范围

本次交付覆盖动态 PostgreSQL 数据源、只读安全边界、Agent 数据源绑定、会话管理、数据库迁移和 Docker 本地运行。外部连接信息、账号和密码不写入仓库。

## 2. 自动化验证

| 项目 | 结果 |
|---|---|
| pytest | 32 passed |
| Alembic 当前版本 | `0004_thread_management` |
| Alembic 模型差异 | No new upgrade operations detected |
| API / Worker / PostgreSQL / Redis | healthy |
| Git 敏感信息检查 | 未发现真实 API Key、Fernet Key 或外部数据库密码 |

已覆盖连接器配置、凭据加密、数据源生命周期、SQL 写入拒绝、Schema/表白名单、动态 Agent 查询、会话重命名与置顶排序、前端关键交互标记。

## 3. 动态数据源验收

### 内置 Northwind

- 系统数据源保持兼容且不可删除；
- 动态连接可读取 `northwind` Schema；
- Agent 可识别 customers、orders、products 等业务表并完成查询。

### Supabase 外部 PostgreSQL

验收环境采用免费 Supabase PostgreSQL，使用 IPv4 Session Pooler、`sslmode=require`、独立只读角色、Schema 白名单和 RLS SELECT Policy。

示例 Schema `retail_demo` 包含：

| 表 | 验收记录数 |
|---|---:|
| products | 5 |
| sales | 8 |
| stores | 3 |

验证结果：

- 连接测试返回 online 且数据库会话为只读；
- Schema 同步识别三张表及主要字段；
- 启用后，新 Run 绑定外部数据源；
- Agent 正确返回三张表的记录数；
- Agent 可关联商品和销售记录计算销量与销售额；
- 未授权 Schema 和非 SELECT SQL 被应用安全层拒绝。

## 4. 会话管理验收

- 首次提问后自动生成最多 24 字的标题；
- 清理“请帮我分析”等常见前缀；
- 支持手动重命名且不会被后续问题覆盖；
- 支持置顶、取消置顶和稳定排序；
- 删除前二次确认，删除当前会话后自动打开下一条；
- 原有会话在新增 `pinned_at` 可空字段后保持可读。

## 5. 手工复验步骤

1. 执行 `docker compose up -d --build`。
2. 检查 `/api/v1/health` 和 `docker compose ps -a`。
3. 在数据源页面完成“测试连接 → 同步结构 → 启用”。
4. 新建会话，询问表结构、记录数量和跨表业务指标。
5. 验证重命名、置顶、取消置顶和删除。
6. 执行 `docker compose exec -T api pytest -q`。
7. 执行 `docker compose exec -T api alembic check`。

## 6. 已知边界

- 仅支持 PostgreSQL，不支持跨数据源 JOIN；
- 没有登录、RBAC 和多租户隔离；
- Supabase 免费项目可能因低活动暂停；
- Docker Compose 仅面向可信本地开发与演示；
- 当前演示视频待按 v0.2.0 功能重新录制。
