# InsightForge Agent 本地部署指南

## 1. 适用范围

本文说明如何在 Windows、macOS 或 Linux 上通过 Docker Compose 部署本地学习与演示环境。当前配置只将 API 和 MCP 端口绑定到 `127.0.0.1`，不适合直接作为公网生产服务。

## 2. 环境要求

- Docker Desktop，或 Docker Engine + Compose Plugin；
- 可访问 Docker Hub；
- DashScope API Key；
- 至少 4 GB 可用内存和足够的镜像、数据卷空间；
- Tavily API Key 可选，仅用于联网搜索 MCP。

检查 Docker：

```bash
docker --version
docker compose version
docker info
```

## 3. 配置环境变量

复制示例文件：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

至少设置：

```dotenv
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
MOCK_LLM=false
```

注意：

- `.env` 已被 Git 和 Docker 构建上下文忽略；
- 不要在截图、Issue、日志或提交记录中公开 API Key；
- API Key 被平台封禁后必须重新生成，修改 `.env` 后需要重新创建容器。

## 4. 启动和验证

Windows 推荐：

```bat
insightforge.bat start
```

通用方式：

```bash
docker compose up -d --build
docker compose ps -a
```

`bootstrap` 正常状态是 `Exited (0)`；其他长期服务应显示 `Up`，其中 PostgreSQL、Redis、Worker 和 API 应通过健康检查。

验证健康接口：

```bash
curl http://127.0.0.1:6006/api/v1/health
```

访问地址：

- Web：<http://127.0.0.1:6006>
- API 文档：<http://127.0.0.1:6006/docs>
- MCP：<http://127.0.0.1:8010/mcp>

## 5. 常用维护命令

```bash
docker compose ps -a
docker compose logs -f --tail=200
docker compose restart api worker web-mcp insightforge-mcp
docker compose exec -T api pytest -q tests
docker compose exec -T api python evals/run_eval.py
docker compose down
```

`docker compose down` 会删除容器和网络，但保留 PostgreSQL 与 Redis 数据卷。

以下命令会删除项目数据，必须谨慎使用：

```bash
docker compose down -v
```

## 6. 更新 `.env`

仅执行 `docker compose restart` 不一定会重新加载环境变量。修改 `.env` 后使用：

```bash
docker compose up -d --force-recreate
```

如果同时修改了依赖或源代码：

```bash
docker compose up -d --build
```

## 7. 数据卷与旧版本兼容

当前版本沿用以下固定卷名，以保留早期 QueryMind 本地部署的数据：

```text
querymind_querymind_postgres
querymind_querymind_redis
```

全新安装时 Docker Compose 会自动创建这两个卷。已有 QueryMind 部署会继续使用原数据，因此更换应用品牌不会清空会话和分析记录。

查看卷：

```bash
docker volume inspect querymind_querymind_postgres
docker volume inspect querymind_querymind_redis
```

卷名属于内部兼容标识，并不影响页面、API 或容器显示为 InsightForge Agent。

## 8. 常见问题

### API 返回 401 或 `API-key is blocked`

Key 已失效、被平台封禁或没有对应模型权限。创建新 Key，更新 `.env`，再执行强制重新创建容器。

### `bootstrap` 显示 Exited

先检查退出码。`Exited (0)` 表示初始化完成，是正常状态；非零退出码需要查看：

```bash
docker compose logs bootstrap
```

### 页面打开但 Redis 或 Worker 不在线

```bash
docker compose ps -a
docker compose logs --tail=200 redis worker
```

确认 Redis 健康，并确认 Worker 心跳没有持续报错。

### 修改代码后页面没有变化

镜像使用 `COPY . .`，没有挂载本地源码。修改后需要重新构建：

```bash
docker compose up -d --build
```

随后强制刷新浏览器缓存。

### C 盘空间没有在 `down` 后恢复

停止容器不会删除镜像、构建缓存或数据卷。使用 `docker system df` 查看占用。Docker Desktop 的磁盘镜像文件也可能不会立即缩小；不要在不了解影响时执行全局清理命令。

## 9. 外部 PostgreSQL 验收

动态数据源建议使用独立只读账号，并依次完成“测试连接”“同步结构”“启用”和智能分析查询。Supabase 等托管 PostgreSQL 应开启 TLS；当 Docker 所在网络不支持 IPv6 直连时，可使用 Session Pooler 地址。

验收时至少确认：

- 数据源状态为 `online`；
- Schema 中的业务表和字段可被识别；
- 当前数据源标签切换正确；
- 聚合、排序和跨表查询结果与数据库原始数据一致；
- 只读账号无法执行写操作。

## 10. 部署安全说明

- 不要将 API 和数据库端口改为公网监听，除非已经增加身份认证和访问控制；
- 不要使用真实生产数据库管理员账号；
- 接入外部数据库时应创建最小权限只读账号；
- 正式环境应使用独立密钥管理、TLS、反向代理、审计和备份方案。
