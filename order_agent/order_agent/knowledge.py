"""Read the OKF knowledge bundle (order_agent/knowledge/).

Concepts are chosen by code — a status name maps to a fixed file path — so
there is no retrieval step and no vector database. Replies quote the bundle
and cite the concept ID (the path without ".md").
"""

import functools
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel

KNOWLEDGE_DIR = Path(
    os.getenv("KNOWLEDGE_DIR", Path(__file__).resolve().parents[1] / "knowledge")
)
STATUSES = ("pending", "confirmed", "completed", "cancelled")

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
_FOOTNOTE_REF_RE = re.compile(r"\[\^[\w-]+\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^[\w-]+\]:.*$", re.M)


class Concept(BaseModel):
    id: str
    title: str
    summary: str
    sections: dict[str, str]


def status_concept_id(status: str) -> str:
    return f"glossary/order-status-{status}"


def _plain(text: str) -> str:
    """Bundle Markdown → reply text: drop footnote markers and code backticks."""
    return _FOOTNOTE_REF_RE.sub("", text).replace("`", "").strip()


@functools.cache
def load_concept(concept_id: str) -> Concept:
    path = KNOWLEDGE_DIR / f"{concept_id}.md"
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path} has no frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = _FOOTNOTE_DEF_RE.sub("", text[match.end() :])
    sections: dict[str, str] = {}
    for block in re.split(r"^## ", body, flags=re.M)[1:]:
        heading, _, content = block.partition("\n")
        sections[heading.strip()] = _plain(content)
    return Concept(
        id=concept_id,
        title=_plain(meta.get("title", concept_id)),
        summary=_plain(meta.get("summary", "")),
        sections=sections,
    )


def status_summary(status: str) -> tuple[str, str] | None:
    """(one-line meaning, concept ID) for a known status, else None."""
    if status not in STATUSES:
        return None
    concept = load_concept(status_concept_id(status))
    return concept.summary, concept.id


def explain_status(status: str) -> str:
    """Reply text built only from the status concept file."""
    concept = load_concept(status_concept_id(status))
    lines = [concept.title]
    for heading in ("意義", "常見的下一步", "聯絡窗口"):
        if concept.sections.get(heading):
            lines.append(f"{heading}：{concept.sections[heading]}")
    lines.append(f"來源：{concept.id}")
    return "\n".join(lines)
