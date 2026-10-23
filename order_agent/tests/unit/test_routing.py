"""Deterministic routing tests: no LLM and no MCP server needed."""

from types import SimpleNamespace

import pytest

from order_agent import prompts
from order_agent.agent import Intent, Reply, clarify, read_only, respond, route

ORD = "ORD-20260118-001"


def _ctx(message: str, pending: dict | None = None):
    return SimpleNamespace(
        state={
            "current_message": message,
            "pending_intent": pending,
            "chat_history": [],
        }
    )


def _route(message: str, pending: dict | None = None, **intent):
    event = route(_ctx(message, pending), Intent(**intent))
    return event.actions.route, event.output


@pytest.mark.parametrize(
    ("message", "intent", "expected_args"),
    [
        (f"我要查詢訂單，訂單編號：{ORD}", "get_order", {"order_number": ORD}),
        (f"Show me order {ORD.lower()}", "get_order", {"order_number": ORD}),
        (
            "我要查詢客戶的訂單清單，客戶名稱：史塔克工業",
            "list_customer_orders",
            {"customer_name": "史塔克工業"},
        ),
        ("訂單狀態 pending 是什麼意思？", "explain_status", {"status": "pending"}),
        ("訂單狀態「已取消」是什麼意思？", "explain_status", {"status": "cancelled"}),
        (
            "What does the order status canceled mean?",
            "explain_status",
            {"status": "cancelled"},
        ),
        (f"訂單 {ORD} 是從哪張報價單來的？", "order_quotation", {"order_number": ORD}),
    ],
)
def test_operations_take_args_from_message(message, intent, expected_args):
    # The LLM gave no fields at all; the code extracts the arguments.
    next_node, output = _route(message, intent=intent)
    assert next_node == intent
    assert output == {"tool": intent, "args": expected_args}


@pytest.mark.parametrize(
    "message",
    [
        f"幫我取消訂單 {ORD}",
        f"幫我把訂單 {ORD} 取消",
        "幫我新增一個客戶，名稱是韋恩企業",
        "請刪除產品 A4 影印紙",
        f"Please cancel order {ORD}",
        "update the customer address for 史塔克工業",
    ],
)
def test_write_requests_are_refused_by_code(message):
    # Even when the LLM thinks it is a lookup, code refuses the write.
    next_node, _ = _route(message, intent="get_order", order_number=ORD)
    assert next_node == "read_only"


def test_status_word_is_not_a_write_verb():
    next_node, _ = _route("訂單 ORD-20260315-001 已取消了嗎？", intent="get_order")
    assert next_node == "get_order"


@pytest.mark.parametrize(
    ("message", "llm_intent"),
    [
        ("今天台北天氣如何？", "off_topic"),
        ("今天台北天氣如何？", "get_order"),  # LLM mistake is overridden by code
        ("講個笑話", "unclear"),
        ("What's the weather in Taipei today?", "list_customer_orders"),
    ],
)
def test_off_topic_is_decided_by_code(message, llm_intent):
    next_node, _ = _route(message, intent=llm_intent)
    assert next_node == "off_topic"


def test_missing_order_number_then_completes():
    next_node, output = _route("我要查詢訂單", intent="get_order")
    assert next_node == "clarify"
    reply = Reply(**clarify(output))
    assert "訂單編號" in reply.text
    next_node, output = _route(ORD, pending=reply.pending_intent, intent="off_topic")
    assert next_node == "get_order"
    assert output["args"] == {"order_number": ORD}


@pytest.mark.parametrize("answer", ["2", "中央城快遞", "中央城快遞股份有限公司"])
def test_ambiguous_customer_answer_picks_candidate(answer):
    pending = {
        "intent": "list_customer_orders",
        "missing": ["customer_name"],
        "fields": {},
        "candidates": ["藍貓快遞有限公司", "中央城快遞股份有限公司"],
    }
    next_node, output = _route(answer, pending=pending, intent="off_topic")
    assert next_node == "list_customer_orders"
    assert output["args"] == {"customer_name": "中央城快遞股份有限公司"}


def test_model_error_goes_straight_to_respond():
    next_node, output = _route("anything", intent="model_error", error_detail="boom")
    assert next_node == "model_error"
    assert "boom" in output["text"]


def test_read_only_reply_points_to_web_ui():
    assert "http://localhost:3000" in Reply(**read_only({})).text
    assert prompts.READ_ONLY_REPLY == Reply(**read_only({})).text


def test_respond_strips_markdown_links():
    event = respond(
        _ctx("hi"), Reply(text="請看 [訂單](http://localhost:3000/orders/1)")
    )
    assert event.output == "請看 訂單 http://localhost:3000/orders/1"
