from __future__ import annotations

import hashlib
import json
import time
from typing import Any, TypedDict

from app.config import get_settings
from app.context import ContextBuilder, MemoryExtractor
from app.northwind import METRIC_DEFINITIONS
from app.runtime import CheckpointManager, EventBus
from app.model import BaseModelGateway
from app.presenter import build_business_answer
from app.prompts import PromptRegistry
from app.repository import Repository
from app.tools import ToolRegistry

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    user_id: str
    question: str
    token_budget: int
    system_prompt: str
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    last_tool_result: dict[str, Any] | None
    answer_text: str
    answer_payload: dict[str, Any]
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    loop_count: int
    tool_call_count: int
    repeated_calls: dict[str, int]
    verification_passed: bool
    should_replan: bool
    error: str
    started_at_epoch: float


class AnalysisGraph:
    """Inspectible LangGraph loop with PostgreSQL checkpoints.

    Each Run uses its run_id as LangGraph thread_id. A worker restart can call
    the same Run again and LangGraph resumes from the latest durable checkpoint.
    """

    def __init__(
        self,
        repo: Repository,
        context_builder: ContextBuilder,
        prompts: PromptRegistry,
        model: BaseModelGateway,
        tools: ToolRegistry,
        events: EventBus,
    ) -> None:
        self.repo = repo
        self.context_builder = context_builder
        self.prompts = prompts
        self.model = model
        self.tools = tools
        self.events = events
        self.memory = MemoryExtractor()
        self.settings = get_settings()
        self.checkpoints = CheckpointManager()
        self.compiled = self._compile_langgraph()

    @property
    def runtime_name(self) -> str:
        return "LangGraph + PostgreSQL Checkpoint"

    def _compile_langgraph(self):
        graph = StateGraph(AgentState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("model", self._model)
        graph.add_node("tools", self._tools)
        graph.add_node("verify", self._verify)
        graph.add_node("memory", self._memory)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "model")
        graph.add_conditional_edges("model", self._after_model, {"tools": "tools", "verify": "verify"})
        graph.add_edge("tools", "model")
        graph.add_conditional_edges("verify", self._after_verify, {"model": "model", "memory": "memory"})
        graph.add_edge("memory", END)
        return graph.compile(checkpointer=self.checkpoints.saver)

    def invoke(self, state: AgentState) -> AgentState:
        config = {"configurable": {"thread_id": state["run_id"]}}
        return dict(self.compiled.invoke(state, config=config))

    def _prepare(self, state: AgentState) -> dict[str, Any]:
        self.events.publish(state["run_id"], "context_building", {"message": "正在理解问题和业务口径"})
        pack = self.context_builder.build(
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            user_id=state["user_id"],
            question=state["question"],
            token_budget=state["token_budget"],
        )
        metrics = (
            "\n".join(f"- {item['name']}：{item['formula']}" for item in METRIC_DEFINITIONS)
            if self.context_builder.source.is_system(state["run_id"])
            else "无预设业务指标，请依据当前 Schema 分析。"
        )
        sql_policy = self.prompts.render(
            "nl2sql", question=state["question"], schema=pack.schema, metrics=metrics
        )
        rendered = self.prompts.render(
            "agent",
            context=pack.prompt_text(),
            sql_policy=sql_policy.text,
            token_budget=state["token_budget"],
            max_loops=self.settings.max_agent_loops,
        )
        for prompt in (sql_policy, rendered):
            self.repo.save_prompt_snapshot(
                state["run_id"], prompt.name, prompt.version, prompt.prompt_hash, prompt.text
            )
        self.events.publish(
            state["run_id"], "context_ready",
            {"message": "已准备相关数据结构和业务知识", "estimated_tokens": pack.estimated_tokens},
        )
        return {
            "system_prompt": rendered.text,
            "messages": [{"role": "user", "content": state["question"]}],
            "pending_tool_calls": [],
            "last_tool_result": None,
            "answer_text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "embedding_tokens": 0,
            "loop_count": 0,
            "tool_call_count": 0,
            "repeated_calls": {},
            "verification_passed": False,
            "should_replan": False,
            "error": "",
            "started_at_epoch": time.time(),
        }

    def _model(self, state: AgentState) -> dict[str, Any]:
        loops = int(state.get("loop_count", 0)) + 1
        total_tokens = int(state.get("input_tokens", 0)) + int(state.get("output_tokens", 0))
        elapsed = time.time() - float(state.get("started_at_epoch", time.time()))
        if loops > self.settings.max_agent_loops or total_tokens >= state["token_budget"] or elapsed > self.settings.max_runtime_seconds:
            text = state.get("answer_text") or "已达到本次分析预算，我根据现有结果结束分析。"
            return {"answer_text": text, "pending_tool_calls": [], "loop_count": loops}

        self.events.publish(state["run_id"], "thinking", {"message": "正在选择合适的数据工具", "loop": loops})
        self.events.publish(
            state["run_id"],
            "answer_reset",
            {"message": "正在组织回答", "loop": loops},
            durable=False,
        )
        streamed = False

        def on_token(delta: str) -> None:
            nonlocal streamed
            if not delta:
                return
            if not streamed:
                self.events.publish(
                    state["run_id"],
                    "answer_start",
                    {"message": "正在生成回答"},
                    durable=False,
                )
                streamed = True
            self.events.publish(
                state["run_id"],
                "answer_delta",
                {"delta": delta},
                durable=False,
            )

        decision = self.model.invoke(
            state["system_prompt"],
            state.get("messages", []),
            self.tools.schemas(),
            on_token=on_token,
        )
        if streamed:
            self.events.publish(
                state["run_id"],
                "answer_end",
                {"message": "回答生成完成"},
                durable=False,
            )
        messages = list(state.get("messages", []))
        pending = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in decision.tool_calls
        ]
        messages.append({
            "role": "assistant",
            "content": decision.content,
            "tool_calls": pending,
        })
        return {
            "messages": messages,
            "pending_tool_calls": pending,
            "answer_text": decision.content or state.get("answer_text", ""),
            "input_tokens": int(state.get("input_tokens", 0)) + decision.input_tokens,
            "output_tokens": int(state.get("output_tokens", 0)) + decision.output_tokens,
            "loop_count": loops,
        }

    def _after_model(self, state: AgentState) -> str:
        return "tools" if state.get("pending_tool_calls") else "verify"

    def _tools(self, state: AgentState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        repeated = dict(state.get("repeated_calls", {}))
        last_result: dict[str, Any] | None = None
        count = int(state.get("tool_call_count", 0))
        first_sql_success: bool | None = None

        for call in state.get("pending_tool_calls", []):
            if count >= self.settings.max_tool_calls:
                last_result = {"ok": False, "error": "已达到工具调用上限"}
                break
            fingerprint = hashlib.sha256(
                f"{call['name']}|{json.dumps(call['arguments'], sort_keys=True, ensure_ascii=False)}".encode()
            ).hexdigest()
            repeated[fingerprint] = repeated.get(fingerprint, 0) + 1
            if repeated[fingerprint] > 2:
                last_result = {"ok": False, "error": "检测到重复且无进展的工具调用，已停止循环"}
                break

            self.events.publish(
                state["run_id"], "tool_running",
                {"message": self._business_tool_message(call["name"]), "tool": call["name"]},
            )
            last_result = self.tools.execute(state["run_id"], call["name"], call["arguments"], self.repo)
            count += 1
            if call["name"] == "query_database" and first_sql_success is None:
                first_sql_success = bool(last_result.get("ok"))
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": call["name"],
                "content": last_result,
            })
            self.events.publish(
                state["run_id"], "tool_finished",
                {"message": "数据工具执行完成" if last_result.get("ok") else "数据工具执行失败", "ok": last_result.get("ok")},
            )

        updates: dict[str, Any] = {
            "messages": messages,
            "pending_tool_calls": [],
            "last_tool_result": last_result,
            "tool_call_count": count,
            "repeated_calls": repeated,
        }
        if first_sql_success is not None:
            self.repo.update_run(state["run_id"], first_sql_success=first_sql_success)
        return updates

    def _verify(self, state: AgentState) -> dict[str, Any]:
        self.events.publish(state["run_id"], "verifying", {"message": "正在核对数据结果"})
        result = state.get("last_tool_result")
        text = (state.get("answer_text") or "").strip()
        passed = bool(text)
        reason = "回答已生成"
        if result is not None:
            passed = bool(result.get("ok")) and bool(text)
            reason = "工具执行成功且已形成回答" if passed else result.get("error", "结果不完整")

        can_retry = (
            not passed
            and int(state.get("loop_count", 0)) < self.settings.max_agent_loops
            and int(state.get("tool_call_count", 0)) < self.settings.max_tool_calls
        )
        messages = list(state.get("messages", []))
        if can_retry:
            messages.append({
                "role": "user",
                "content": f"上一步未通过验证：{reason}。请更换查询方式，不要重复相同调用。",
            })
            self.events.publish(state["run_id"], "replanning", {"message": "结果不完整，正在调整分析方法"})
        else:
            self.events.publish(
                state["run_id"], "verified",
                {"message": "结果核对完成", "passed": passed, "reason": reason},
            )
        return {"verification_passed": passed, "should_replan": can_retry, "messages": messages}

    def _after_verify(self, state: AgentState) -> str:
        return "model" if state.get("should_replan") else "memory"

    def _memory(self, state: AgentState) -> dict[str, Any]:
        candidates = self.memory.persist(self.repo, state["user_id"], state["question"])
        tokens = self._token_summary(state)
        payload = build_business_answer(
            state.get("answer_text") or "本次分析未能形成有效结论。",
            state.get("last_tool_result"),
            tokens=tokens,
            verification_passed=bool(state.get("verification_passed")),
        )
        self.events.publish(
            state["run_id"], "completed",
            {"message": "分析完成", "memory_updates": len(candidates)},
        )
        return {"answer_payload": payload}

    def _token_summary(self, state: AgentState) -> dict[str, Any]:
        input_tokens = int(state.get("input_tokens", 0))
        output_tokens = int(state.get("output_tokens", 0))
        embedding_tokens = int(state.get("embedding_tokens", 0))
        total = input_tokens + output_tokens + embedding_tokens
        estimated_cost = (
            input_tokens / 1_000_000 * self.settings.input_cost_per_million
            + output_tokens / 1_000_000 * self.settings.output_cost_per_million
            + embedding_tokens / 1_000_000 * self.settings.embedding_cost_per_million
        )
        return {
            "input": input_tokens,
            "output": output_tokens,
            "embedding": embedding_tokens,
            "total": total,
            "budget": state["token_budget"],
            "usage_ratio": round(total / max(1, state["token_budget"]) * 100, 2),
            "estimated_cost": round(estimated_cost, 6),
            "currency": "CNY配置估算",
        }

    @staticmethod
    def _business_tool_message(name: str) -> str:
        return {
            "inspect_schema": "正在确认数据结构",
            "query_database": "正在查询经营数据",
            "get_metric_definition": "正在核对指标口径",
            "web_search": "正在联网查找外部资料",
        }.get(name, "正在调用分析工具")
