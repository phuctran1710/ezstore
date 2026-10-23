"""The OKF knowledge bundle: structure, citations, and how the agent reads it."""

import re

import pytest
import yaml

from order_agent import knowledge

ROOT = knowledge.KNOWLEDGE_DIR
REPO = ROOT.parents[1]
CONCEPTS = {
    p.relative_to(ROOT).with_suffix("").as_posix(): p for p in ROOT.rglob("*.md")
}
CONCEPT_LINK_RE = re.compile(
    r"`((?:glossary|playbooks|decisions|systems|lessons)/[\w-]+)`"
)


def _split(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no frontmatter"
    return yaml.safe_load(match.group(1)), text[match.end() :]


@pytest.mark.parametrize("concept_id", sorted(CONCEPTS))
def test_concept_structure_and_citations(concept_id):
    meta, body = _split(CONCEPTS[concept_id])
    for key in ("type", "title", "summary", "sources"):
        assert key in meta, f"{concept_id}: missing {key}"
    for source in meta["sources"] or []:
        assert (REPO / source["path"]).exists(), f"{concept_id}: {source['path']}"
    refs = set(re.findall(r"\[\^([\w-]+)\](?!:)", body))
    defs = set(re.findall(r"^\[\^([\w-]+)\]:", body, re.M))
    assert refs == defs, f"{concept_id}: footnotes used {refs} vs defined {defs}"
    for other in CONCEPT_LINK_RE.findall(body):
        assert other in CONCEPTS, f"{concept_id}: unknown concept {other}"


def test_index_lists_every_concept():
    index = (ROOT / "index.md").read_text(encoding="utf-8")
    for concept_id in CONCEPTS:
        if concept_id not in ("index", "log"):
            assert f"`{concept_id}`" in index


@pytest.mark.parametrize("status", knowledge.STATUSES)
def test_every_status_has_a_glossary_concept(status):
    meta, _ = _split(ROOT / f"{knowledge.status_concept_id(status)}.md")
    assert meta["type"] == "glossary" and meta["status"] == status
    text = knowledge.explain_status(status)
    assert text.endswith(f"來源：glossary/order-status-{status}")
    assert "[^" not in text and "`" not in text


def test_unknown_status_has_no_summary():
    assert knowledge.status_summary("on_hold") is None
