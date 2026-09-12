from app.config import get_settings
from app.service import AnalysisService


def build_mock_service(monkeypatch) -> AnalysisService:
    """让图测试固定使用Mock模型，避免消耗真实API额度。"""
    monkeypatch.setenv("MOCK_LLM", "true")
    get_settings.cache_clear()
    return AnalysisService()


def execute_without_queue(service: AnalysisService, question: str):
    thread = service.repo.create_thread()
    user_message = service.repo.add_message(thread.id, "user", question)
    run = service.repo.create_run(thread.id, "guest", question, 20_000)
    service.repo.update_run(run.id, state={"user_message_id": user_message.id})
    service.execute_run(run.id)
    return service.repo.get_run(run.id)


def test_mock_function_calling_graph_end_to_end(monkeypatch):
    service = build_mock_service(monkeypatch)
    run = execute_without_queue(service, "销售额最高的10个商品是什么？")

    assert run.status == "completed"
    assert run.data_source_id is not None
    assert run.first_sql_success is True
    assert run.verification_passed is True
    assert len(run.answer["table"]["rows"]) == 10
    assert "商品" in run.answer["table"]["rows"][0]
    assert run.tool_call_count >= 1


def test_general_chat_does_not_query_database(monkeypatch):
    service = build_mock_service(monkeypatch)
    run = execute_without_queue(service, "你是谁？")

    assert run.status == "completed"
    assert run.tool_call_count == 0
    assert "InsightForge Agent" in run.answer["summary"]
