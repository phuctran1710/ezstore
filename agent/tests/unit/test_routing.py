"""Deterministic routing tests: no LLM and no MCP server needed."""

from types import SimpleNamespace

import pytest

from quotation_agent import prompts
from quotation_agent.agent import Intent, Reply, clarify, off_topic, respond, route

QT = "QT-20260330-001"


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
        (
            f"我要查詢報價單，報價單編號：{QT}",
            "get_quotation",
            {"quotation_number": QT},
        ),
        (
            "我要查詢客戶的報價單清單，客戶名稱：史塔克工業",
            "list_customer_quotations",
            {"customer_name": "史塔克工業"},
        ),
        (
            f"我要複製報價單，報價單編號：{QT}",
            "duplicate_quotation",
            {"quotation_number": QT},
        ),
        (
            f"我要修改報價單報價因子，報價單編號：{QT}，報價因子改為 1.5",
            "update_pricing_factor",
            {"quotation_number": QT, "new_pricing_factor": 1.5},
        ),
        (
            f"我要修改報價單總價，報價單編號：{QT}，總價改為 8000",
            "adjust_total_price",
            {"quotation_number": QT, "target_total_price": 8000.0},
        ),
        (
            f"我要將報價單轉訂單，報價單編號：{QT}",
            "convert_to_order",
            {"quotation_number": QT},
        ),
    ],
)
def test_operations_take_args_from_message(message, intent, expected_args):
    # Even with no fields from the LLM, the code extracts the arguments.
    next_node, output = _route(message, intent=intent)
    assert next_node == intent
    assert output == {"tool": intent, "args": expected_args}


def test_code_overrides_wrong_llm_numbers():
    message = f"我要修改報價單總價，報價單編號：{QT}，總價改為 8000"
    _, output = _route(
        message,
        intent="adjust_total_price",
        quotation_number=QT,
        target_total_price=20260330,
    )
    assert output["args"]["target_total_price"] == 8000.0


@pytest.mark.parametrize(
    ("message", "llm_intent"),
    [
        ("今天台北天氣如何？", "off_topic"),
        ("今天台北天氣如何？", "get_quotation"),  # LLM mistake is overridden by code
        ("幫我新增一個客戶，名稱是韋恩企業", "list_customer_quotations"),
        ("請修改產品 A4 影印紙的價格", "unclear"),
        ("講個笑話", "unclear"),
    ],
)
def test_off_topic_is_decided_by_code(message, llm_intent):
    next_node, _ = _route(message, intent=llm_intent)
    assert next_node == "off_topic"


def test_missing_field_goes_to_clarify_then_completes():
    next_node, output = _route("我要複製報價單", intent="duplicate_quotation")
    assert next_node == "clarify"
    assert output == {
        "intent": "duplicate_quotation",
        "missing": ["quotation_number"],
        "fields": {},
    }

    reply = Reply(**clarify(output))
    assert "報價單編號" in reply.text
    assert reply.pending_intent == output

    # The next message only carries the number; the LLM may call it off_topic.
    next_node, output = _route(QT, pending=reply.pending_intent, intent="off_topic")
    assert next_node == "duplicate_quotation"
    assert output["args"] == {"quotation_number": QT}


def test_clarify_keeps_known_fields():
    pending = {
        "intent": "adjust_total_price",
        "missing": ["quotation_number"],
        "fields": {"target_total_price": 8000.0},
    }
    next_node, output = _route(
        QT, pending=pending, intent="adjust_total_price", quotation_number=QT
    )
    assert next_node == "adjust_total_price"
    assert output["args"] == {"quotation_number": QT, "target_total_price": 8000.0}


def test_malformed_quotation_number_is_asked_again():
    next_node, output = _route(
        "我要查詢報價單 12345", intent="get_quotation", quotation_number="12345"
    )
    assert next_node == "clarify"
    assert output["missing"] == ["quotation_number"]


def test_model_error_goes_straight_to_respond():
    next_node, output = _route("anything", intent="model_error", error_detail="boom")
    assert next_node == "model_error"
    assert "boom" in output["text"]


def test_off_topic_reply_is_fixed():
    assert Reply(**off_topic({})).text == prompts.OFF_TOPIC_REPLY


def test_respond_strips_markdown_links_and_clears_pending():
    ctx = _ctx("hi", pending={"intent": "get_quotation"})
    event = respond(
        ctx, Reply(text="請看 [報價單](http://localhost:3000/quotations/12)")
    )
    assert event.output == "請看 報價單 http://localhost:3000/quotations/12"
    assert event.actions.state_delta["pending_intent"] is None
    assert event.actions.state_delta["chat_history"][-1]["agent"] == event.output
