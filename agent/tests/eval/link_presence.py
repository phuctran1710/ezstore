"""Deterministic `link_present` metric (see eval_config.yaml).

1. A Markdown link [text](url) → 0 (spec 1.8 requires plain-text links).
2. eval_case_id starting with "off_topic" → 1, a refusal needs no link.
3. Otherwise the reply must contain a plain http(s)://.../quotations/<id> or
   .../orders/<id> link → 1, else 0.
"""

import re

_LINK = re.compile(r"https?://\S+/(quotations|orders)/\d+")
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(https?://[^)]+\)")


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
    if case_id.startswith("off_topic"):
        return {"score": 1, "explanation": "Off-topic refusal needs no link"}
    if _LINK.search(text):
        return {"score": 1, "explanation": "Plain-text system link present"}
    return {
        "score": 0,
        "explanation": "No plain-text /quotations/<id> or /orders/<id> link",
    }
