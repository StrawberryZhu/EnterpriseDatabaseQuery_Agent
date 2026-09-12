from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_insightforge_brand():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "<title>InsightForge Agent</title>" in html
    assert "<strong>InsightForge Agent</strong>" in html
    assert '<div class="brand-mark">I</div>' in html


def test_frontend_contains_business_pages():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for label in ["智能分析", "经营看板", "系统表现", "数据源", "指标口径", "设置"]:
        assert label in html


def test_frontend_hides_internal_agent_debugging():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for label in ["LangGraph节点", "Prompt快照", "Tool Call参数", "隐藏思维链"]:
        assert label not in html


def test_frontend_contains_dynamic_data_source_management():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for label in ["新增 PostgreSQL 数据源", "测试连接", "同步结构", "允许的 Schema"]:
        assert label in html + script
    assert "/api/v1/data-sources" in script
    assert 'type="password"' in html
    assert "button.dataset.dsAction" in script
    assert "button.dataset.action" not in script


def test_frontend_contains_thread_management():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    for marker in ["threadActionMenu", "renameThreadModal", 'data-thread-action="rename"', 'data-thread-action="pin"', 'data-thread-action="delete"']:
        assert marker in html + script
    assert "thread.pinned_at" in script
    assert ".thread-action-menu" in styles


def test_single_deployment_architecture():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ["postgres:", "redis:", "worker:", "api:", "web-mcp:", "insightforge-mcp:"]:
        assert service in compose
    assert "name: insightforge-agent" in compose
    assert "image: insightforge-agent-app:0.2.0" in compose
    assert "external: true" not in compose
    assert "sqlite" not in compose.lower()
