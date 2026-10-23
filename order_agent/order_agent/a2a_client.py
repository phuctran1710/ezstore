"""A2A client for asking the quotation agent about one quotation.

Rules (spec 2.4, ADR 0002):
- Only a lookup sentence built here is sent; user text is never forwarded.
- Only the quotation agent's `respond`-node text is used. ADK's A2A server puts
  each event's author in the artifact metadata (`adk_author`). In the quotation
  Workflow the only text events authored by the workflow itself
  ("quotation_agent") come from `respond`; the classifier's JSON is authored
  by "classify_intent" and is dropped.
- The agent card is read from QUOTATION_AGENT_URL, but requests go to
  QUOTATION_AGENT_URL as well: the card advertises one URL (valid inside the
  Compose network), which may not be reachable from where this agent runs.
"""

import os
import uuid

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from google.protobuf.json_format import MessageToDict

QUOTATION_AGENT_URL = os.getenv(
    "QUOTATION_AGENT_URL", "http://localhost:8081/a2a/quotation_agent"
)
QUOTATION_AGENT_NAME = "quotation_agent"
TIMEOUT_SECONDS = 60.0

_FAILED_STATES = {
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_CANCELED,
}


class QuotationAgentError(Exception):
    """The quotation agent could not be reached or gave no usable answer."""


def lookup_sentence(quotation_number: str) -> str:
    return f"我要查詢報價單，報價單編號：{quotation_number}"


def _respond_text(artifacts) -> str:
    texts = []
    for artifact in artifacts:
        meta = MessageToDict(artifact.metadata) if artifact.metadata else {}
        if meta.get("adk_author") != QUOTATION_AGENT_NAME:
            continue
        texts.extend(part.text for part in artifact.parts if part.text)
    return "\n".join(t.strip() for t in texts if t.strip())


async def ask_quotation_agent(quotation_number: str) -> str:
    """Send the lookup sentence over A2A; return the quotation agent's reply."""
    url = QUOTATION_AGENT_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
            card = await A2ACardResolver(http, url).get_agent_card()
            for interface in card.supported_interfaces:
                interface.url = url
            client = await create_client(
                card, ClientConfig(streaming=False, httpx_client=http)
            )
            message = Message(
                message_id=f"order-agent-{uuid.uuid4()}",
                role=Role.ROLE_USER,
                parts=[Part(text=lookup_sentence(quotation_number))],
            )
            artifacts, state = [], None
            async for chunk in client.send_message(SendMessageRequest(message=message)):
                if chunk.HasField("task"):
                    artifacts.extend(chunk.task.artifacts)
                    state = chunk.task.status.state
                elif chunk.HasField("artifact_update"):
                    artifacts.append(chunk.artifact_update.artifact)
                elif chunk.HasField("status_update"):
                    state = chunk.status_update.status.state
    except Exception as e:
        raise QuotationAgentError(f"{type(e).__name__}，位址 {url}") from e

    if state in _FAILED_STATES:
        raise QuotationAgentError(f"報價單助理回報失敗（{TaskState.Name(state)}）")
    text = _respond_text(artifacts)
    if not text:
        raise QuotationAgentError("報價單助理沒有回覆內容")
    return text
