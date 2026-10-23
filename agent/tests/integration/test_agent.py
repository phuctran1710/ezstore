"""Run the whole Workflow graph in-process.

The offline tests replace the Gemini call of classify_intent with fixed Intents,
so they need no model credentials. Tests that
call MCP tools are skipped when the MCP server (MCP_URL) is not reachable.
"""

import os
import urllib.request

import pytest
from google.adk.models import Gemini, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from quotation_agent import agent as agent_module
from quotation_agent import prompts
from quotation_agent.agent import Intent, app


def _mcp_reachable() -> bool:
    try:
        urllib.request.urlopen(agent_module.MCP_URL, timeout=2)
    except urllib.error.HTTPError:
        return True  # server answered (e.g. 406 for a plain GET)
    except Exception:
        return False
    return True


needs_mcp = pytest.mark.skipif(not _mcp_reachable(), reason="MCP server not reachable")


@pytest.fixture
def fake_llm(monkeypatch):
    """Make classify_intent return the given Intents in order, without an LLM."""
    answers: list[Intent] = []

    async def generate_content_async(self, llm_request, stream=False):
        intent = answers.pop(0)
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=intent.model_dump_json())],
            )
        )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(Gemini, "generate_content_async", generate_content_async)
    return answers


async def _chat(*messages: str) -> list[str]:
    """Send messages in one session; return the respond-node text per turn."""
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=app.name, user_id="test"
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
    [reply] = await _chat("我要查詢報價單，報價單編號：QT-20260330-001")
    assert "GEMINI_API_KEY" in reply


@pytest.mark.asyncio
async def test_off_topic_is_refused(fake_llm):
    fake_llm.append(Intent(intent="get_quotation"))  # wrong label; code still refuses
    [reply] = await _chat("今天台北天氣如何？")
    assert reply == prompts.OFF_TOPIC_REPLY


@needs_mcp
@pytest.mark.asyncio
async def test_get_quotation_through_mcp(fake_llm):
    fake_llm.append(Intent(intent="get_quotation", quotation_number="QT-20260330-001"))
    [reply] = await _chat("我要查詢報價單，報價單編號：QT-20260330-001")
    assert "QT-20260330-001" in reply
    assert "/quotations/" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_clarify_then_complete(fake_llm):
    fake_llm.extend([Intent(intent="get_quotation"), Intent(intent="off_topic")])
    first, second = await _chat("我要查詢報價單", "QT-20260330-001")
    assert "報價單編號" in first
    assert "QT-20260330-001" in second and "/quotations/" in second


# Real model calls cost free-tier quota, so they only run on request.
@pytest.mark.skipif(
    os.getenv("RUN_LLM_TESTS") != "1",
    reason="set RUN_LLM_TESTS=1 to call the real model",
)
@needs_mcp
@pytest.mark.asyncio
async def test_real_llm_get_quotation():
    [reply] = await _chat("我要查詢報價單，報價單編號：QT-20260330-001")
    assert "/quotations/" in reply or "429" in reply or "503" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_clarify_from_seeded_events(fake_llm):
    """agents-cli eval seeds earlier turns as plain events, without state."""
    from google.adk.events.event import Event

    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name=app.name, user_id="test"
    )
    for author, text in [
        ("user", "我要查詢報價單"),
        (
            "quotation_agent",
            "好的，我可以幫您查詢報價單，請提供報價單編號（例如 QT-20260330-001）。",
        ),
    ]:
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
    fake_llm.append(Intent(intent="off_topic"))  # worst case: LLM misses the context
    texts = []
    async for event in runner.run_async(
        user_id="test",
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="QT-20260330-001")]
        ),
    ):
        if "/respond@" in (event.node_info.path or "") and event.content:
            texts.append("".join(p.text or "" for p in event.content.parts))
    reply = "".join(texts)
    assert "QT-20260330-001" in reply and "/quotations/" in reply


@needs_mcp
@pytest.mark.asyncio
async def test_not_found_is_reported_plainly(fake_llm):
    fake_llm.append(Intent(intent="get_quotation"))
    [reply] = await _chat("我要查詢報價單，報價單編號：QT-20990101-001")
    assert "找不到" in reply
    assert "Error executing tool" not in reply
    assert "/quotations/" not in reply
