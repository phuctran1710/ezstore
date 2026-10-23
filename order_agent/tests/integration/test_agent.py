"""Run the whole order Workflow in-process.

The Gemini call of classify_intent is replaced with fixed Intents, so these
tests need no model credentials. Tests that call the order MCP server are
skipped when it is not reachable; the quotation agent is faked or pointed at a
closed port, so no A2A model call is made either.
"""

import os
import urllib.request

import pytest
from google.adk.events.event import Event
from google.adk.models import Gemini, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from order_agent import a2a_client, prompts
from order_agent import agent as agent_module
from order_agent.agent import Intent, app


def _mcp_reachable() -> bool:
    try:
        urllib.request.urlopen(agent_module.MCP_URL, timeout=2)
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False
    return True


needs_mcp = pytest.mark.skipif(
    not _mcp_reachable(), reason="order MCP server not reachable"
)


@pytest.fixture
def fake_llm(monkeypatch):
    answers: list[Intent] = []

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=answers.pop(0).model_dump_json())],
            )
        )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(Gemini, "generate_content_async", generate_content_async)
    return answers


async def _chat(*messages: str, seed: list[tuple[str, str]] = ()) -> list[str]:
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=app.name, user_id="test"
    )
    for author, text in seed:
        await runner.session_service.append_event(
            session,
            Event(
                author=author,
                content=types.Content(
                    role="user" if author == "user" else "model",
                    parts=[types.Part.from_text(text=text)],
                ),
            ),
        )
    replies = []
    for message in messages:
        texts = []
        async for event in runner.run_async(
            user_id="test",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text=message)]
            ),
        ):
            if "/respond@" in (event.node_info.path or "") and event.content:
                texts.append("".join(p.text or "" for p in event.content.parts))
        replies.append("".join(texts))
    return replies


@pytest.mark.asyncio
async def test_no_credentials_gives_clear_error(monkeypatch):
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_GENAI_USE_ENTERPRISE",
    ):
        monkeypatch.delenv(var, raising=False)
    [reply] = await _chat("我要查詢訂單，訂單編號：ORD-20260118-001")
    assert "GEMINI_API_KEY" in reply


@pytest.mark.asyncio
async def test_status_explanation_comes_from_knowledge(fake_llm):
    fake_llm.append(Intent(intent="explain_status"))
    [reply] = await _chat("訂單狀態 pending 是什麼意思？")
    assert "待處理" in reply and reply.endswith("來源：glossary/order-status-pending")


@pytest.mark.asyncio
async def test_write_request_is_refused(fake_llm):
    fake_llm.append(Intent(intent="get_order"))  # wrong label; code still refuses
    [reply] = await _chat("幫我取消訂單 ORD-20260118-001")
    assert reply == prompts.READ_ONLY_REPLY


@needs_mcp
@pytest.mark.asyncio
async def test_order_lookup(fake_llm):
    fake_llm.append(Intent(intent="get_order"))
    [reply] = await _chat("我要查詢訂單，訂單編號：ORD-20260118-001")
    assert "史塔克工業" in reply and "completed（已完成）" in reply
    assert "來源：glossary/order-status-completed" in reply
    assert "http://localhost:3000/orders/1" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_ambiguous_customer_then_pick(fake_llm):
    fake_llm.extend([Intent(intent="list_customer_orders"), Intent(intent="off_topic")])
    first, second = await _chat("我要查詢客戶的訂單清單，客戶名稱：快遞", "2")
    assert (
        "找到多位符合「快遞」的客戶" in first and "2. 中央城快遞股份有限公司" in first
    )
    assert "中央城快遞股份有限公司" in second and "/orders/" in second


@needs_mcp
@pytest.mark.asyncio
async def test_clarify_from_seeded_events(fake_llm):
    fake_llm.append(Intent(intent="off_topic"))  # worst case: LLM misses the context
    [reply] = await _chat(
        "ORD-20260118-001",
        seed=[
            ("user", "我要查詢訂單"),
            (
                "order_agent",
                "好的，我可以幫您查詢訂單，請提供訂單編號（例如 ORD-20260118-001）。",
            ),
        ],
    )
    assert "ORD-20260118-001" in reply and "/orders/1" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_order_without_quotation(fake_llm):
    fake_llm.append(Intent(intent="order_quotation"))
    [reply] = await _chat("訂單 ORD-20260328-001 是從哪張報價單來的？")
    assert "不是由報價單轉來的" in reply and "/orders/8" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_source_quotation_via_a2a(fake_llm, monkeypatch):
    sent = []

    async def fake_ask(quotation_number):
        sent.append(quotation_number)
        return (
            "報價單編號: QT-20260310-001\n系統連結: http://localhost:3000/quotations/8"
        )

    monkeypatch.setattr(a2a_client, "ask_quotation_agent", fake_ask)
    fake_llm.append(Intent(intent="order_quotation"))
    [reply] = await _chat("訂單 ORD-20260325-001 是從哪張報價單來的？")
    assert sent == ["QT-20260310-001"]  # only the number, never the user's text
    assert "來自報價單 QT-20260310-001" in reply and "透過 A2A" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_quotation_agent_unreachable(fake_llm, monkeypatch):
    monkeypatch.setattr(
        a2a_client, "QUOTATION_AGENT_URL", "http://127.0.0.1:1/a2a/quotation_agent"
    )
    fake_llm.append(Intent(intent="order_quotation"))
    [reply] = await _chat("訂單 ORD-20260325-001 是從哪張報價單來的？")
    assert "QT-20260310-001" in reply and "目前無法連線報價單助理" in reply


@pytest.mark.skipif(
    os.getenv("RUN_LLM_TESTS") != "1",
    reason="set RUN_LLM_TESTS=1 to call the real model",
)
@needs_mcp
@pytest.mark.asyncio
async def test_real_llm_order_lookup():
    [reply] = await _chat("我要查詢訂單，訂單編號：ORD-20260118-001")
    assert "/orders/1" in reply or "429" in reply or "503" in reply
