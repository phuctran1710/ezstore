"""Local LLM-as-judge for `custom_response_quality` (see eval_config.yaml)."""

import os
import threading

from google import genai
from google.genai import types
from pydantic import BaseModel

_local = threading.local()


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _client() -> genai.Client:
    """One client per grading thread.

    The eval SDK grades cases on its own thread pool; this initialization runs once
    per thread. Avoids creating a new client for each eval case, which would re-do
    ADC and the TLS handshake every time. Each thread gets its own client, because
    google-auth freezes the SSL context after the first connection when a client
    certificate is present.
    """
    client = getattr(_local, "client", None)
    if client is None:
        # AI Studio (GEMINI_API_KEY) or Gemini platform (ADC).
        client = _local.client = genai.Client()
    return client


def _judge_model() -> str:
    """JUDGE_MODEL, else the agent's AGENT_MODEL, else the spec default."""
    return (
        os.environ.get("JUDGE_MODEL")
        or os.environ.get("AGENT_MODEL")
        or "gemini-3.8-flash"
    )


def _user_prompt(instance) -> str:
    """The prompt, or the last user message for multi-turn cases (no prompt)."""
    prompt = instance.get("prompt")
    if prompt:
        return str(prompt)
    turns = (instance.get("agent_data") or {}).get("turns") or []
    for turn in reversed(turns):
        for event in reversed(turn.get("events") or []):
            if event.get("author") == "user":
                parts = (event.get("content") or {}).get("parts") or []
                return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return ""


def evaluate(instance):
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, and clarity."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
            # The agent's own rules (e.g. spec 1.8: plain-text links only) outrank
            # a user's formatting request; the expected answer states them.
            " The expected answer states the assistant's required behavior, which"
            " takes precedence over any conflicting user request (for example, a"
            " request for Markdown links when plain-text links are required). If the"
            " response follows the expected answer's required behavior, do NOT deduct"
            " any points for not doing what the user asked instead; grade only"
            " accuracy, relevance and clarity."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise AI assistant. {rubric}\n"
        f"User Prompt: {_user_prompt(instance)}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    response = _client().models.generate_content(
        model=_judge_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,  # deterministic grading
            response_mime_type="application/json",
            response_schema=_Verdict,  # guaranteed schema-valid JSON
        ),
    )
    verdict = response.parsed
    if verdict is None:  # model returned nothing usable
        return {"score": 0, "explanation": response.text or ""}
    return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
