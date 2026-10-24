"""Deterministic `link_present` metric for order_agent (see eval_config.yaml).

1. A Markdown link [text](url) → 0 (spec 1.8 requires plain-text links).
2. Cases whose answer has no system page need no link → 1:
   eval_case_id starting with "off_topic" or "read_only" (refusals) or
   "explain_status" (answered from the knowledge bundle; cites a concept ID).
3. A "not found" reply (contains 找不到) needs no link → 1: there is no page
   to link to, and linking one would invent data.
4. Otherwise the reply must contain a plain http(s)://.../orders/<id> or
   .../quotations/<id> link → 1, else 0.
"""

import re

_LINK = re.compile(r"https?://\S+/(orders|quotations)/\d+")
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(https?://[^)]+\)")
_NO_LINK_NEEDED = ("off_topic", "read_only", "explain_status")


def _response_text(instance) -> str:
    response = instance.get("response") or {}
    if isinstance(response, str):
        return response
    parts = response.get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def evaluate(instance):
    text = _response_text(instance)
    case_id = str(instance.get("eval_case_id", ""))

    if _MARKDOWN_LINK.search(text):
        return {
            "score": 0,
            "explanation": "Markdown link found; plain-text links are required",
        }
    if case_id.startswith(_NO_LINK_NEEDED):
        return {"score": 1, "explanation": "Refusal or knowledge answer needs no link"}
    if "找不到" in text:
        return {"score": 1, "explanation": "Not-found reply needs no link"}
    if _LINK.search(text):
        return {"score": 1, "explanation": "Plain-text system link present"}
    return {
        "score": 0,
        "explanation": "No plain-text /orders/<id> or /quotations/<id> link",
    }
