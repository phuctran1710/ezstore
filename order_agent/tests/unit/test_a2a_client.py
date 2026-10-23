"""Which parts of a quotation-agent A2A reply are used (no network)."""

import pytest
from a2a.types import Artifact, Part
from google.protobuf.struct_pb2 import Struct

from order_agent import a2a_client


def _artifact(author: str, text: str) -> Artifact:
    meta = Struct()
    meta.update({"adk_author": author})
    return Artifact(artifact_id=author, parts=[Part(text=text)], metadata=meta)


def test_only_respond_text_is_used():
    artifacts = [
        _artifact("classify_intent", '{"intent": "get_quotation"}'),
        _artifact("quotation_agent", "報價單編號: QT-20260330-001"),
    ]
    assert a2a_client._respond_text(artifacts) == "報價單編號: QT-20260330-001"


def test_lookup_sentence_is_built_by_code():
    assert (
        a2a_client.lookup_sentence("QT-20260310-001")
        == "我要查詢報價單，報價單編號：QT-20260310-001"
    )


@pytest.mark.asyncio
async def test_unreachable_quotation_agent_raises(monkeypatch):
    monkeypatch.setattr(
        a2a_client, "QUOTATION_AGENT_URL", "http://127.0.0.1:1/a2a/quotation_agent"
    )
    with pytest.raises(a2a_client.QuotationAgentError):
        await a2a_client.ask_quotation_agent("QT-20260310-001")
