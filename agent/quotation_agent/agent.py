"""EZStore quotation management agent: an ADK graph Workflow.

  START → load_context → classify_intent (LLM, output_schema=Intent) → route
            ├─ get_quotation / list_customer_quotations / duplicate_quotation
            ├─ update_pricing_factor / adjust_total_price / convert_to_order
            ├─ clarify     (missing fields → ask, keep state.pending_intent)
            └─ off_topic   (fixed refusal, decided by code)
          all → respond    (emit text + update state)

Only classify_intent calls the LLM. Tool choice, tool arguments, clarification
and refusal are all decided by the code in `route`.
"""

import logging
import os
import re
from typing import Any, Literal

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.models import Gemini, LlmRequest, LlmResponse
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel

from . import prompts

logger = logging.getLogger(__name__)

# Read agent/.env before the settings below. fast_api_app.py imports this
# module (via the package) before its own load_dotenv() call. Variables that
# are already set, e.g. by Docker Compose, take precedence.
load_dotenv()

MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8010/mcp")

# The MCP server is plain HTTP on the internal network. Without this, ADK's MCP
# session manager probes Google ADC for mTLS on the first connection, which
# stalls ~12s waiting for the GCE metadata server outside Google Cloud.
os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")

# Number of past user/agent exchanges given to the classifier as context.
HISTORY_TURNS = 3

OPERATIONS: dict[str, tuple[str, ...]] = {
    "get_quotation": ("quotation_number",),
    "list_customer_quotations": ("customer_name",),
    "duplicate_quotation": ("quotation_number",),
    "update_pricing_factor": ("quotation_number", "new_pricing_factor"),
    "adjust_total_price": ("quotation_number", "target_total_price"),
    "convert_to_order": ("quotation_number",),
}
MODIFYING_OPERATIONS = {"update_pricing_factor", "adjust_total_price"}

QUOTATION_NUMBER_RE = re.compile(r"QT-\d{8}-\d{3}", re.IGNORECASE)
# Number right after the keyword (optionally "改為", "：", ...), never digits
# inside a quotation number such as "總價，報價單編號：QT-20260330-001".
_VALUE = r"\s*(?:改為|改成|調整為|調整成|調為|設為|設定為|變更為|為|是|=|:|：)?\s*(\d+(?:\.\d+)?)(?![\d.-])"
PRICING_FACTOR_RE = re.compile(r"報價因子" + _VALUE)
TOTAL_PRICE_RE = re.compile(r"總價" + _VALUE)
CUSTOMER_NAME_RE = re.compile(r"客戶(?:名稱)?\s*[:：]\s*([^\s，,。]+)")
# A message must mention the quotation domain for an operation to run.
DOMAIN_RE = re.compile(r"報價|訂單|QT-\d", re.IGNORECASE)
# Creating/modifying/deleting customers or products is out of scope even
# though it mentions entities that also appear in quotations.
ENTITY_CRUD_RE = re.compile(
    r"(新增|建立|增加|修改|更新|編輯|刪除|移除|改)[^，,。\n]{0,6}(客戶|產品|商品)"
    r"|(客戶|產品|商品)[^，,。\n]{0,6}(新增|建立|修改|更新|編輯|刪除|移除)"
)
TOOL_ERROR_PREFIX_RE = re.compile(r"^Error executing tool \w+:\s*")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


class Intent(BaseModel):
    """Structured output of the classify_intent LLM node."""

    intent: Literal[
        "get_quotation",
        "list_customer_quotations",
        "duplicate_quotation",
        "update_pricing_factor",
        "adjust_total_price",
        "convert_to_order",
        "off_topic",
        "unclear",
        "model_error",
    ]
    quotation_number: str | None = None
    customer_name: str | None = None
    new_pricing_factor: float | None = None
    target_total_price: float | None = None
    error_detail: str | None = None


class ToolCall(BaseModel):
    """What `route` hands to an operation node."""

    tool: str
    args: dict[str, Any]


class Reply(BaseModel):
    """What every branch hands to `respond`."""

    text: str
    pending_intent: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Model credentials / errors
# ---------------------------------------------------------------------------


def _has_credentials() -> bool:
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return True
    use_vertex = (
        os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "")
        or os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "")
    ).lower() in ("1", "true", "yes")
    return use_vertex and bool(os.getenv("GOOGLE_CLOUD_PROJECT"))


def _error_response(detail: str) -> LlmResponse:
    payload = Intent(intent="model_error", error_detail=detail)
    return LlmResponse(
        content=types.Content(
            role="model", parts=[types.Part.from_text(text=payload.model_dump_json())]
        )
    )


def _check_credentials(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    if _has_credentials():
        return None
    return _error_response(prompts.NO_CREDENTIALS_DETAIL)


def _on_model_error(
    callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
) -> LlmResponse | None:
    logger.error("classify_intent model call failed: %s", error)
    return _error_response(_describe_model_error(error))


def _describe_model_error(error: Exception) -> str:
    text = str(error)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return "模型請求過於頻繁或配額已用完（429），請稍後再試。"
    if "503" in text or "UNAVAILABLE" in text:
        return "模型服務暫時忙碌（503），請稍後再試。"
    if any(
        code in text for code in ("401", "403", "API_KEY_INVALID", "PERMISSION_DENIED")
    ):
        return "模型憑證無效或沒有權限（請檢查 GEMINI_API_KEY 或 Vertex AI 設定）。"
    return f"{type(error).__name__}: {text}"[:300]


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL),
    tool_filter=list(OPERATIONS),
    tool_list_cache_ttl_seconds=300,
)


async def _call_mcp(ctx: Context, call: ToolCall) -> Reply:
    """Run one MCP tool and turn its text result into a Reply."""
    operation = prompts.OPERATION_LABELS[call.tool]
    try:
        tools = {tool.name: tool for tool in await mcp_toolset.get_tools(ctx)}
        tool = tools.get(call.tool)
        if tool is None:
            raise RuntimeError(f"MCP Server 沒有提供工具 {call.tool}")
        result = await tool.run_async(args=call.args, tool_context=ctx)
    except Exception as e:  # MCP server down, network error, ...
        logger.exception("MCP tool %s failed", call.tool)
        detail = f"無法連線報價單服務（MCP Server: {MCP_URL}）：{type(e).__name__}"
        return Reply(
            text=prompts.MCP_ERROR_REPLY.format(operation=operation, detail=detail)
        )

    text = _result_text(result)
    if _is_error(result):
        detail = TOOL_ERROR_PREFIX_RE.sub("", text).strip()
        if "找不到" in detail:  # not found: say so plainly, invent nothing
            return Reply(text=prompts.NOT_FOUND_REPLY.format(detail=detail))
        return Reply(
            text=prompts.MCP_ERROR_REPLY.format(operation=operation, detail=detail)
        )
    if call.tool in MODIFYING_OPERATIONS:
        text = f"{text}\n{prompts.COPY_ON_WRITE_NOTE}"
    return Reply(text=text)


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        parts = result.get("content") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
        if texts:
            return "\n".join(t for t in texts if t).strip()
        if "error" in result:
            return str(result["error"])
    return str(result)


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and bool(
        result.get("isError") or result.get("is_error") or "error" in result
    )


# ---------------------------------------------------------------------------
# Workflow nodes
# ---------------------------------------------------------------------------


def _content_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    return "".join(p.text or "" for p in content.parts if not p.thought).strip()


def _history_from_events(ctx: Context) -> list[dict[str, str]]:
    """Past exchanges read from the session events.

    Used when session state has no chat_history, e.g. when a client (such as
    `agents-cli eval` multi-turn cases) seeds a session with prior events only.
    """
    history: list[dict[str, str]] = []
    for event in ctx.session.events:
        if event.invocation_id == ctx.invocation_id:
            continue
        text = _content_text(event.content)
        if not text:
            continue
        if event.author == "user":
            history.append({"user": text, "agent": ""})
        elif event.author != classify_intent.name and not text.startswith("{"):
            if history:
                history[-1]["agent"] = text
    return history


def _pending_from_history(history: list[dict[str, str]]) -> dict[str, Any] | None:
    """Recognize our own clarification question as the last agent reply."""
    if not history:
        return None
    last_reply = history[-1]["agent"]
    for intent, label in prompts.OPERATION_LABELS.items():
        if last_reply.startswith(prompts.CLARIFY_TEMPLATE.split("{")[0] + label):
            fields = _extract_fields(history[-1]["user"], Intent(intent=intent))
            missing = [f for f in OPERATIONS[intent] if f not in fields]
            return {"intent": intent, "missing": missing, "fields": fields}
    return None


def load_context(ctx: Context, node_input: types.Content) -> Event:
    """Build the classifier input from the new message plus session state."""
    message = _content_text(node_input)
    history: list[dict[str, str]] = ctx.state.get("chat_history") or []
    pending: dict[str, Any] | None = ctx.state.get("pending_intent")
    if not history:
        history = _history_from_events(ctx)
        pending = pending or _pending_from_history(history)

    lines = []
    if history:
        lines.append("最近的對話：")
        for turn in history[-HISTORY_TURNS:]:
            lines.append(f"使用者：{turn['user']}")
            lines.append(f"助理：{turn['agent'][:200]}")
        lines.append("")
    if pending:
        missing = "、".join(pending.get("missing", []))
        lines.append(
            f"上一輪待補資料的操作：{pending['intent']}（缺少：{missing}；"
            f"已知欄位：{pending.get('fields', {})}）"
        )
        lines.append("")
    lines.append(f"使用者最新的一句話：{message}")
    return Event(
        output="\n".join(lines),
        state={"current_message": message, "pending_intent": pending},
    )


classify_intent = LlmAgent(
    name="classify_intent",
    model=Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3)),
    instruction=prompts.CLASSIFIER_INSTRUCTION,
    output_schema=Intent,
    include_contents="none",
    generate_content_config=types.GenerateContentConfig(
        temperature=0,
        # Classification is easy; low thinking keeps latency down.
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    ),
    before_model_callback=_check_credentials,
    on_model_error_callback=_on_model_error,
)


def _extract_fields(message: str, intent: Intent) -> dict[str, Any]:
    """Fields from the LLM, overridden by what regexes find in the message."""
    fields: dict[str, Any] = {
        k: v
        for k, v in intent.model_dump(exclude={"intent", "error_detail"}).items()
        if v not in (None, "")
    }
    if m := QUOTATION_NUMBER_RE.search(message):
        fields["quotation_number"] = m.group(0).upper()
    elif "quotation_number" in fields:
        number = str(fields["quotation_number"]).strip().upper()
        if QUOTATION_NUMBER_RE.fullmatch(number):
            fields["quotation_number"] = number
        else:  # malformed → ask again instead of guessing
            del fields["quotation_number"]
    if m := PRICING_FACTOR_RE.search(message):
        fields["new_pricing_factor"] = float(m.group(1))
    if m := TOTAL_PRICE_RE.search(message):
        fields["target_total_price"] = float(m.group(1))
    if m := CUSTOMER_NAME_RE.search(message):
        fields["customer_name"] = m.group(1)
    return fields


def route(ctx: Context, node_input: Intent) -> Event:
    """Deterministically pick the next node and the tool arguments."""
    message: str = ctx.state.get("current_message", "")
    pending: dict[str, Any] | None = ctx.state.get("pending_intent")

    if node_input.intent == "model_error":
        detail = node_input.error_detail or "未知錯誤"
        reply = Reply(
            text=prompts.MODEL_ERROR_REPLY.format(detail=detail), pending_intent=pending
        )
        return Event(output=reply.model_dump(), route="model_error")

    fields = _extract_fields(message, node_input)
    intent = node_input.intent

    # Code-level guardrails: the LLM label alone never runs an operation.
    if ENTITY_CRUD_RE.search(message) and not QUOTATION_NUMBER_RE.search(message):
        intent = "off_topic"
    elif intent in OPERATIONS and not DOMAIN_RE.search(message):
        # No quotation vocabulary: only allowed as an answer to a clarification.
        intent = pending["intent"] if pending else "off_topic"
    elif intent in ("off_topic", "unclear") and pending:
        # A bare answer such as "QT-20260330-001" to the previous question.
        if any(f in fields for f in pending.get("missing", [])):
            intent = pending["intent"]
    if intent == "unclear" and not DOMAIN_RE.search(message):
        intent = "off_topic"

    if intent == "off_topic":
        return Event(output={"reason": "off_topic"}, route="off_topic")
    if intent == "unclear":
        return Event(
            output={"intent": None, "missing": [], "fields": {}}, route="clarify"
        )

    if pending and pending["intent"] == intent:
        fields = {**pending.get("fields", {}), **fields}
    required = OPERATIONS[intent]
    args = {f: fields[f] for f in required if f in fields}
    missing = [f for f in required if f not in args]
    if missing:
        return Event(
            output={"intent": intent, "missing": missing, "fields": args},
            route="clarify",
        )
    return Event(output=ToolCall(tool=intent, args=args).model_dump(), route=intent)


async def get_quotation(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


async def list_customer_quotations(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


async def duplicate_quotation(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


async def update_pricing_factor(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


async def adjust_total_price(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


async def convert_to_order(ctx: Context, node_input: ToolCall) -> dict:
    return (await _call_mcp(ctx, node_input)).model_dump()


def clarify(node_input: dict[str, Any]) -> dict:
    """Ask for the missing fields and remember the half-finished operation."""
    intent = node_input.get("intent")
    if not intent:
        return Reply(text=prompts.UNCLEAR_REPLY).model_dump()
    fields = "、".join(prompts.FIELD_LABELS[f] for f in node_input["missing"])
    text = prompts.CLARIFY_TEMPLATE.format(
        operation=prompts.OPERATION_LABELS[intent], fields=fields
    )
    return Reply(text=text, pending_intent=node_input).model_dump()


def off_topic(node_input: dict[str, Any]) -> dict:
    """Fixed refusal; the decision was made by `route`, not by the LLM."""
    return Reply(text=prompts.OFF_TOPIC_REPLY).model_dump()


def respond(ctx: Context, node_input: Reply) -> Event:
    """The only node whose text is shown to the user (see frontend agentApi.ts)."""
    # Requirement 1.8: plain-text links only.
    text = MARKDOWN_LINK_RE.sub(
        lambda m: f"{m.group(1)} {m.group(2)}".strip(), node_input.text
    )
    history = list(ctx.state.get("chat_history", []))
    history.append({"user": ctx.state.get("current_message", ""), "agent": text})
    return Event(
        message=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
        output=text,
        state={
            "chat_history": history[-10:],
            "pending_intent": node_input.pending_intent,
        },
    )


OPERATION_NODES = [
    get_quotation,
    list_customer_quotations,
    duplicate_quotation,
    update_pricing_factor,
    adjust_total_price,
    convert_to_order,
]

root_agent = Workflow(
    name="quotation_agent",
    description="EZStore 報價單管理助理：查詢、複製、修改報價因子／總價、轉訂單。",
    edges=[
        ("START", load_context, classify_intent, route),
        (
            route,
            {
                **{op.__name__: op for op in OPERATION_NODES},
                "clarify": clarify,
                "off_topic": off_topic,
                "model_error": respond,
            },
        ),
        *[(op, respond) for op in OPERATION_NODES],
        (clarify, respond),
        (off_topic, respond),
    ],
)

app = App(
    root_agent=root_agent,
    name="quotation_agent",
)
