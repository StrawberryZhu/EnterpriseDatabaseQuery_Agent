from fastapi.testclient import TestClient

from app.main import app
from app.repository import Repository
from app.service import derive_thread_title


def test_derive_thread_title_removes_filler_and_limits_length():
    assert derive_thread_title("请帮我分析一下每个月的销售额趋势如何？") == "每个月的销售额趋势如何"
    assert derive_thread_title("这是一个超过二十四个字符并且需要截断的会话标题测试问题") == "这是一个超过二十四个字符并且需要截断的会话标题…"


def test_thread_rename_pin_order_and_unpin():
    repo = Repository()
    first = repo.create_thread(title="thread management first")
    second = repo.create_thread(title="thread management second")
    try:
        repo.update_thread(first.id, title="renamed thread")
        repo.set_thread_pinned(first.id, True)
        ordered = repo.list_threads()
        assert ordered[0].id == first.id
        assert repo.get_thread(first.id).title == "renamed thread"
        assert repo.get_thread(first.id).pinned_at is not None

        repo.set_thread_pinned(first.id, False)
        assert repo.get_thread(first.id).pinned_at is None
    finally:
        repo.delete_thread(first.id)
        repo.delete_thread(second.id)


def test_thread_management_api():
    client = TestClient(app)
    created = client.post("/api/v1/threads", json={"title": "API thread management"})
    assert created.status_code == 200
    thread_id = created.json()["id"]
    try:
        renamed = client.patch(f"/api/v1/threads/{thread_id}", json={"title": "手动重命名"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "手动重命名"

        pinned = client.patch(f"/api/v1/threads/{thread_id}", json={"pinned": True})
        assert pinned.status_code == 200
        assert pinned.json()["pinned_at"] is not None
        assert client.get("/api/v1/threads").json()[0]["id"] == thread_id
    finally:
        client.delete(f"/api/v1/threads/{thread_id}")
