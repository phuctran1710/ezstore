"""Local LLM-as-judge for `refusal_or_action` (see eval_config.yaml).

The judge rules are NOT hard-coded here: they are read from the
`prompt_template` of the `refusal_or_action` entry in the eval config, so
editing that template (as eval-lab.md section 5 asks) changes how this judge
scores. The judge runs in-process through google-genai with GEMINI_API_KEY
(AI Studio) on AGENT_MODEL, instead of the Vertex AI eval service, which
refuses to run without billing (403 "This API method requires billing to be
enabled").

agents-cli loads this file with exec(), so there is no __file__; the config is
the one passed with `--config`, else tests/eval/eval_config.yaml under the
current directory (agents-cli runs from the agent project root).
"""

import json
import os
import sys
import threading

import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel

METRIC_NAME = "refusal_or_action"
DEFAULT_CONFIG = os.path.join("tests", "eval", "eval_config.yaml")

_local = threading.local()


class _Verdict(BaseModel):
    score: int  # 0 or 1
    explanation: str


def _client() -> genai.Client:
    """One client per grading thread (see response_quality.py)."""
    client = getattr(_local, "client", None)
    if client is None:
        client = _local.client = genai.Client()
    return client


def _config_path() -> str:
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--config="):
            return arg.split("=", 1)[1]
    return DEFAULT_CONFIG


def _prompt_template() -> str:
    """Read on every call, so the template in the config is the single source."""
    path = _config_path()
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for metric in config.get("custom_metrics") or []:
        if metric.get("name") == METRIC_NAME and metric.get("prompt_template"):
            return metric["prompt_template"]
    raise ValueError(f"No prompt_template for '{METRIC_NAME}' in {path}")


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict) and "parts" in value and len(value) <= 2:
        parts = value.get("parts") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return json.dumps(value, ensure_ascii=False, default=str)


def evaluate(instance):
    # Plain replace, not str.format: the template contains literal JSON braces.
    prompt = _prompt_template()
    for field in ("response", "agent_data", "prompt", "reference"):
        prompt = prompt.replace("{" + field + "}", _as_text(instance.get(field)))

    response = _client().models.generate_content(
        model=os.environ.get("AGENT_MODEL", "gemini-3.8-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,  # deterministic grading
            response_mime_type="application/json",
            response_schema=_Verdict,
        ),
    )
    verdict = response.parsed
    if verdict is None:
        return {"score": 0, "explanation": response.text or ""}
    return {"score": 1 if verdict.score >= 1 else 0, "explanation": verdict.explanation}
