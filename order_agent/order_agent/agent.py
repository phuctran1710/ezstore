"""EZStore order & customer service agent (read-only): an ADK graph Workflow.

  START → load_context → classify_intent (LLM, output_schema=Intent) → route
            ├─ get_order / list_customer_orders      ← one order MCP tool each
            ├─ explain_status                        ← OKF knowledge bundle, chosen by code
            ├─ order_quotation ─has_quotation─▶ find_quotation_number ─found─▶ ask_quotation_agent (A2A)
            ├─ clarify     (missing fields → ask, keep state.pending_intent)
            ├─ read_only   (create/cancel/change/delete → fixed refusal, decided by code)
            ├─ off_topic   (fixed refusal, decided by code)
            └─ model_error (LLM unavailable → straight to respond)
          all → respond    (emit text + update state)

Only classify_intent calls the LLM. Tool choice, tool arguments, knowledge
lookup, refusals and clarification are decided by the code in `route` and the
operation nodes.
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

from . import a2a_client, knowledge, prompts

logger = logging.getLogger(__name__)

# Read order_agent/.env before the settings below (fast_api_app.py imports this
# module before its own load_dotenv()). Already-set variables take precedence.
load_dotenv()

MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
MCP_URL = os.getenv("MCP_URL", "http://localhost:8011/mcp")

# The MCP server is plain HTTP on the internal network; skip ADK's mTLS probe,
# which otherwise stalls the first connection outside Google Cloud.
os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")

HISTORY_TURNS = 3

OPERATIONS: dict[str, tuple[str, ...]] = {
    "get_order": ("order_number",),
    "list_customer_orders": ("customer_name",),
    "explain_status": ("status",),
    "order_quotation": ("order_number",),
}
MCP_TOOLS = ("get_order_by_number", "list_customer_orders", "get_quotation_number")

ORDER_NUMBER_RE = re.compile(r"ORD-\d{8}-\d{3}", re.IGNORECASE)
CUSTOMER_NAME_RE = re.compile(r"客戶(?:名稱)?\s*[:：]\s*([^\s，,。？?]+)")
STATUS_WORDS = {
    "pending": "pending",
    "待處理": "pending",
    "confirmed": "confirmed",
    "已確認": "confirmed",
    "completed": "completed",
    "已完成": "completed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "已取消": "cancelled",
}
STATUS_RE = re.compile(
    r"\b(pending|confirmed|completed|cancell?ed)\b|(待處理|已確認|已完成|已取消)",
    re.IGNORECASE,
)
# An operation needs order vocabulary in the message (or a pending question).
DOMAIN_RE = re.compile(
    r"訂單|ORD-\d|客戶|狀態|報價|待處理|已確認|已完成|已取消"
    r"|\b(orders?|customers?|status|quotations?|pending|confirmed|completed|cancell?ed)\b",
    re.IGNORECASE,
)
# Write requests are refused by code (ADR 0001). "已取消" is a status, not a verb.
WRITE_RE = re.compile(
    r"(?<!已)(新增|建立|取消|修改|更改|變更|更新|刪除|移除|改成|改為)[^，,。？?\n]{0,10}(訂單|客戶|產品|商品)"
    r"|(把|將)[^，,。？?\n]{0,20}(訂單|客戶|產品|商品)[^，,。？?\n]{0,20}(取消|刪除|修改|更改|變更|更新|改)"
    r"|\b(cancel|delete|remove|update|change|modify|create|add|edit)\b[^.?!\n]{0,40}\b(orders?|customers?|products?)\b",
    re.IGNORECASE,
)
# A request that names an operation (with or without its fields) is that
# operation, even if the LLM calls it "unclear"; missing fields then go to
# clarify for that operation. Checked in order: the most specific first.
OPERATION_CUES: list[tuple[str, re.Pattern[str]]] = [
    (
        "order_quotation",
        re.compile(
            r"訂單.{0,30}(報價單|報價).{0,6}(來|來源)|(來源|原始)報價單"
            r"|\b(source|original)\s+quotation\b|\bwhich\s+quotation\b",
            re.IGNORECASE,
        ),
    ),
    (
        "list_customer_orders",
        re.compile(
            r"客戶.{0,10}訂單|訂單(清單|列表)"
            r"|\bcustomer'?s?\s+orders\b|\borders?\s+(of|for)\s+(a\s+|the\s+)?customer\b",
            re.IGNORECASE,
        ),
    ),
    (
        "explain_status",
        re.compile(
            r"狀態.{0,15}(意思|代表|說明|是什麼|是甚麼)"
            r"|\bstatus(es)?\b.{0,30}\b(mean|meaning)\b|\bwhat\s+does\b.{0,40}\bmean\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_order",
        re.compile(
            r"(查詢|查|看|找|調閱).{0,4}訂單|訂單.{0,4}(資訊|資料|明細|內容|狀態)"
            r"|\b(look\s*up|show|find|check|get)\b.{0,20}\border\b",
            re.IGNORECASE,
        ),
    ),
]


def _named_operation(message: str) -> str | None:
    for intent, pattern in OPERATION_CUES:
        if pattern.search(message):
            return intent
    return None


TOOL_ERROR_PREFIX_RE = re.compile(r"^Error executing tool \w+:\s*")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
CANDIDATE_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$", re.M)


class Intent(BaseModel):
    """Structured output of the classify_intent LLM node."""

    intent: Literal[
        "get_order",
        "list_customer_orders",
        "explain_status",
        "order_quotation",
        "read_only_request",
        "off_topic",
        "unclear",
        "model_error",
    ]
    order_number: str | None = None
    customer_name: str | None = None
    status: Literal["pending", "confirmed", "completed", "cancelled"] | None = None
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
# MCP (order_mcp_server)
# ---------------------------------------------------------------------------

mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL),
    tool_filter=list(MCP_TOOLS),
    tool_list_cache_ttl_seconds=300,
)


class ToolFailure(Exception):
    """An MCP tool failed; `reply` is the user-facing message."""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply


async def _call_tool(ctx: Context, name: str, args: dict, operation: str) -> dict:
    """Run one order MCP tool and return its structured result."""
    try:
        tools = {tool.name: tool for tool in await mcp_toolset.get_tools(ctx)}
        if name not in tools:
            raise RuntimeError(f"MCP Server 沒有提供工具 {name}")
        result = await tools[name].run_async(args=args, tool_context=ctx)
    except Exception as e:  # MCP server down, network error, ...
        logger.exception("MCP tool %s failed", name)
        detail = f"無法連線訂單服務（MCP Server: {MCP_URL}）：{type(e).__name__}"
        raise ToolFailure(
            prompts.TOOL_ERROR_REPLY.format(operation=operation, detail=detail)
        ) from e

    if result.get("isError"):
        parts = result.get("content") or []
        text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
        detail = TOOL_ERROR_PREFIX_RE.sub("", text).strip()
        if "找不到" in detail:
            raise ToolFailure(prompts.NOT_FOUND_REPLY.format(detail=detail))
        raise ToolFailure(
            prompts.TOOL_ERROR_REPLY.format(operation=operation, detail=detail)
        )
    return result.get("structuredContent") or {}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _amount(value: float) -> str:
    return f"{value:g}" if value != int(value) else str(int(value))


def _status_text(status: str) -> str:
    label = prompts.STATUS_LABELS.get(status)
    return f"{status}（{label}）" if label else status


def _format_order(o: dict) -> str:
    lines = [
        f"訂單編號: {o['order_number']}",
        f"客戶: {o['customer_name']}",
        f"狀態: {_status_text(o['status'])}",
    ]
    if found := knowledge.status_summary(o["status"]):
        summary, concept_id = found
        lines.append(f"狀態說明: {summary}（來源：{concept_id}）")
    lines += [
        f"總價: {_amount(o['total_price'])}",
        f"建立日期: {o['created_at'][:10]}",
        f"備註: {o['notes']}",
        "品項:",
    ]
    lines += [
        f"  {i}. {item['product_name']} — 單價: {_amount(item['unit_price'])}, "
        f"數量: {item['quantity']}, 小計: {_amount(item['subtotal'])}"
        for i, item in enumerate(o["items"], 1)
    ]
    lines.append(f"系統連結: {o['link']}")
    return "\n".join(lines)


def _format_customer_orders(data: dict) -> str:
    customer, orders = data["customer"], data["orders"]
    if not orders:
        return f"客戶「{customer['name']}」目前沒有任何訂單。"
    lines = [f"客戶「{customer['name']}」的訂單清單（共 {len(orders)} 筆）："]
    lines += [
        f"- {o['order_number']} | 狀態: {_status_text(o['status'])} | "
        f"總價: {_amount(o['total_price'])} | 連結: {o['link']}"
        for o in orders
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Workflow nodes
# ---------------------------------------------------------------------------


def _content_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    return "".join(p.text or "" for p in content.parts if not p.thought).strip()


def _history_from_events(ctx: Context) -> list[dict[str, str]]:
    """Past exchanges read from session events (sessions seeded without state)."""
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
    if last_reply.startswith(prompts.AMBIGUOUS_CUSTOMER_TEMPLATE.split("「")[0]):
        candidates = [name for _, name in CANDIDATE_LINE_RE.findall(last_reply)]
        return {
            "intent": "list_customer_orders",
            "missing": ["customer_name"],
            "fields": {},
            "candidates": candidates,
        }
    prefix = prompts.CLARIFY_TEMPLATE.split("{")[0]
    for intent, label in prompts.OPERATION_LABELS.items():
        if last_reply.startswith(prefix + label):
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
    if m := ORDER_NUMBER_RE.search(message):
        fields["order_number"] = m.group(0).upper()
    elif "order_number" in fields:
        number = str(fields["order_number"]).strip().upper()
        if ORDER_NUMBER_RE.fullmatch(number):
            fields["order_number"] = number
        else:  # malformed → ask again instead of guessing
            del fields["order_number"]
    if m := CUSTOMER_NAME_RE.search(message):
        fields["customer_name"] = m.group(1)
    if m := STATUS_RE.search(message):
        fields["status"] = STATUS_WORDS[m.group(0).lower()]
    return fields


def _pick_candidate(message: str, candidates: list[str]) -> str | None:
    """Answer to "which customer?": a number from the list or a (partial) name."""
    text = message.strip()
    if text.isdigit() and 1 <= int(text) <= len(candidates):
        return candidates[int(text) - 1]
    matches = [c for c in candidates if text and (text in c or c in text)]
    return matches[0] if len(matches) == 1 else None


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
    if WRITE_RE.search(message) or intent == "read_only_request":
        return Event(output={}, route="read_only")
    if pending and pending.get("candidates") and "customer_name" not in fields:
        if name := _pick_candidate(message, pending["candidates"]):
            fields["customer_name"], intent = name, "list_customer_orders"
    if intent in OPERATIONS and not DOMAIN_RE.search(message):
        # No order vocabulary: only allowed as an answer to a clarification.
        intent = pending["intent"] if pending else "off_topic"
    elif intent in ("off_topic", "unclear") and pending:
        if any(f in fields for f in pending.get("missing", [])):
            intent = pending["intent"]
        elif intent == "unclear" and pending.get("missing") == ["customer_name"]:
            fields["customer_name"] = message.strip(" ，,。？?")
            intent = pending["intent"]
    if intent in ("unclear", "off_topic") and (named := _named_operation(message)):
        intent = named
    if intent == "unclear" and not DOMAIN_RE.search(message):
        intent = "off_topic"

    if intent == "off_topic":
        return Event(output={}, route="off_topic")
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


async def get_order(ctx: Context, node_input: ToolCall) -> dict:
    try:
        order = await _call_tool(
            ctx,
            "get_order_by_number",
            node_input.args,
            prompts.OPERATION_LABELS["get_order"],
        )
    except ToolFailure as e:
        return Reply(text=e.reply).model_dump()
    return Reply(text=_format_order(order)).model_dump()


async def list_customer_orders(ctx: Context, node_input: ToolCall) -> dict:
    query = node_input.args["customer_name"]
    try:
        data = await _call_tool(
            ctx,
            "list_customer_orders",
            {"customer_name": query},
            prompts.OPERATION_LABELS["list_customer_orders"],
        )
    except ToolFailure as e:
        return Reply(text=e.reply).model_dump()
    if data.get("result") == "ambiguous":
        names = [c["name"] for c in data["candidates"]]
        listing = "\n".join(f"{i}. {name}" for i, name in enumerate(names, 1))
        pending = {
            "intent": "list_customer_orders",
            "missing": ["customer_name"],
            "fields": {},
            "candidates": names,
        }
        text = prompts.AMBIGUOUS_CUSTOMER_TEMPLATE.format(
            query=query, candidates=listing
        )
        return Reply(text=text, pending_intent=pending).model_dump()
    return Reply(text=_format_customer_orders(data)).model_dump()


def explain_status(node_input: ToolCall) -> dict:
    """Answer only from the knowledge bundle (status → concept file, by code)."""
    return Reply(text=knowledge.explain_status(node_input.args["status"])).model_dump()


async def order_quotation(ctx: Context, node_input: ToolCall) -> Event:
    """Step 1 of the source-quotation chain: the order and its quotation_id."""
    try:
        order = await _call_tool(
            ctx,
            "get_order_by_number",
            node_input.args,
            prompts.OPERATION_LABELS["order_quotation"],
        )
    except ToolFailure as e:
        return Event(output=Reply(text=e.reply).model_dump(), route="done")
    if order.get("quotation_id") is None:
        text = prompts.NO_QUOTATION_REPLY.format(
            order_number=order["order_number"], order_link=order["link"]
        )
        return Event(output=Reply(text=text).model_dump(), route="done")
    return Event(
        output={
            "order_number": order["order_number"],
            "order_link": order["link"],
            "quotation_id": order["quotation_id"],
        },
        route="has_quotation",
    )


async def find_quotation_number(ctx: Context, node_input: dict[str, Any]) -> Event:
    """Step 2: quotation_id → quotation number (the backend stores only the id)."""
    try:
        ref = await _call_tool(
            ctx,
            "get_quotation_number",
            {"quotation_id": node_input["quotation_id"]},
            prompts.OPERATION_LABELS["order_quotation"],
        )
    except ToolFailure as e:
        return Event(output=Reply(text=e.reply).model_dump(), route="done")
    return Event(
        output={
            **node_input,
            "quotation_number": ref["quotation_number"],
            "quotation_link": ref["link"],
        },
        route="found",
    )


async def ask_quotation_agent(node_input: dict[str, Any]) -> dict:
    """Step 3: ask the quotation agent over A2A with a sentence built by code."""
    fields = {
        k: node_input[k]
        for k in ("order_number", "order_link", "quotation_number", "quotation_link")
    }
    try:
        details = await a2a_client.ask_quotation_agent(node_input["quotation_number"])
    except a2a_client.QuotationAgentError as e:
        logger.warning("quotation agent unreachable: %s", e)
        text = prompts.QUOTATION_AGENT_DOWN_TEMPLATE.format(**fields, detail=str(e))
        return Reply(text=text).model_dump()
    return Reply(
        text=prompts.QUOTATION_FOUND_TEMPLATE.format(**fields, details=details)
    ).model_dump()


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


def read_only(node_input: dict[str, Any]) -> dict:
    """Fixed refusal for write requests (ADR 0001), decided by `route`."""
    return Reply(text=prompts.READ_ONLY_REPLY).model_dump()


def off_topic(node_input: dict[str, Any]) -> dict:
    """Fixed refusal; the decision was made by `route`, not by the LLM."""
    return Reply(text=prompts.OFF_TOPIC_REPLY).model_dump()


def respond(ctx: Context, node_input: Reply) -> Event:
    """The only node whose text is the agent's answer."""
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


root_agent = Workflow(
    name="order_agent",
    description="EZStore 訂單與客戶服務助理（唯讀）：查詢訂單、客戶的訂單清單、訂單狀態說明、訂單的來源報價單。",
    edges=[
        ("START", load_context, classify_intent, route),
        (
            route,
            {
                "get_order": get_order,
                "list_customer_orders": list_customer_orders,
                "explain_status": explain_status,
                "order_quotation": order_quotation,
                "clarify": clarify,
                "read_only": read_only,
                "off_topic": off_topic,
                "model_error": respond,
            },
        ),
        (order_quotation, {"has_quotation": find_quotation_number, "done": respond}),
        (find_quotation_number, {"found": ask_quotation_agent, "done": respond}),
        *[
            (node, respond)
            for node in (
                get_order,
                list_customer_orders,
                explain_status,
                ask_quotation_agent,
                clarify,
                read_only,
                off_topic,
            )
        ],
    ],
)

app = App(
    root_agent=root_agent,
    name="order_agent",
)
