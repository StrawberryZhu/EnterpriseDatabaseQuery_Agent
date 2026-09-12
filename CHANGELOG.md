# Changelog

本项目从 InsightForge Agent `v0.1.0` 开始维护独立版本。

## v0.2.0 - 2026-09-10

### Added

- 动态 PostgreSQL 数据源新增、编辑、测试、Schema 同步、启用和软删除。
- Fernet 凭据加密和密钥版本字段。
- Schema 快照、Run 数据源绑定和 Northwind 系统数据源注册。
- 外部数据源 Agent 上下文与只读查询链路。
- 会话自动命名、重命名、置顶、取消置顶和删除。
- Supabase Session Pooler、TLS、只读角色和 RLS 外部验收记录。

### Security

- SQLGlot SELECT 校验、Schema/表白名单、查询超时和 200 行限制。
- 外部数据源密码仅写入、加密存储且不通过 API 返回。
- Northwind 专属 RAG 和指标不会注入外部数据源分析。

### Fixed

- 修复数据源按钮错误生成 `/undefined` 请求的问题。
- 修复 Docker 容器仍加载旧静态资源导致前端修复不生效的问题。

## v0.1.0 - 2026-09-08

- 建立安全配置基线、独立仓库、品牌迁移和可回退版本。
