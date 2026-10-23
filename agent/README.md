# EZStore quotation agent (`quotation_agent`)

A natural-language assistant for EZStore quotations, built with Google ADK 2.x as a **graph Workflow**. It talks to the backend only through the MCP server (`mcp_server/`, 6 tools). The ADK app name is `quotation_agent`, which the Chat UI (`frontend/src/api/agentApi.ts`) relies on.

Scaffolded with `agents-cli scaffold create ezstore-agent --agent adk --deployment-target none --prototype --agent-directory quotation_agent --root-agent-name quotation_agent --agent-guidance-filename CLAUDE.md` (agents-cli 1.10).

## Project layout

```
agent/
├── quotation_agent/
│   ├── agent.py            # the Workflow graph: Intent schema, nodes, routing rules, App
│   ├── prompts.py          # classifier instruction + every fixed reply (refusal, clarification, errors)
│   ├── fast_api_app.py     # ADK FastAPI server (/run_sse, sessions, A2A) — what Docker and agents-cli run
│   └── app_utils/          # scaffold helpers: shared session service, A2A routes
├── tests/
│   ├── unit/               # routing rules, no LLM, no MCP
│   ├── integration/        # whole graph with a fake classifier + real MCP; real-model tests behind RUN_LLM_TESTS=1
│   └── eval/               # agents-cli eval: datasets, eval_config.yaml, metric code (see "Evaluation")
├── Dockerfile              # image for the `agent` Compose service (port 8080)
├── pyproject.toml / uv.lock
└── .env.example            # copy to .env for local runs
```

## Graph design

```
START → load_context → classify_intent (LLM, output_schema=Intent) → route
          ├─ get_quotation / list_customer_quotations / duplicate_quotation
          ├─ update_pricing_factor / adjust_total_price / convert_to_order   ← each calls one MCP tool
          ├─ clarify      (missing fields → ask, remember state.pending_intent)
          ├─ off_topic    (fixed refusal)
          └─ model_error  (LLM unavailable → straight to respond)
        all → respond     (emits the reply, updates state)
```

| Node | Kind | What it does |
|---|---|---|
| `load_context` | function | Builds the classifier input: the new message, the last 3 exchanges (`state.chat_history`) and any half-finished operation (`state.pending_intent`). Stores the message in `state.current_message`. |
| `classify_intent` | `LlmAgent` | **The only LLM call.** `output_schema=Intent`: an intent label plus extracted fields (quotation number, customer name, pricing factor, target total). `include_contents="none"`, temperature 0. |
| `route` | function | **Decides everything in code** (below) and emits a route: an operation name, `clarify`, `off_topic` or `model_error`. |
| 6 operation nodes | function | Each calls exactly one MCP tool with the arguments chosen by `route` and returns the tool's text. For `update_pricing_factor` and `adjust_total_price` they append a note that the original quotation was left unchanged. |
| `clarify` | function | Asks for the missing fields (`prompts.CLARIFY_TEMPLATE`) and keeps the operation in `pending_intent`. |
| `off_topic` | function | Fixed refusal (`prompts.OFF_TOPIC_REPLY`). |
| `respond` | function | The **only** node whose text the Chat UI shows: the frontend filters on `nodeInfo.path` ending in `/respond@N`. It rewrites any Markdown link `[text](url)` to plain text and updates `chat_history` / `pending_intent`. |

**What `route` decides, and why it's code rather than prompt:**
- **Arguments:** regexes read the quotation number (`QT-YYYYMMDD-NNN`), pricing factor, target total and customer name straight from the message, and override what the LLM extracted. A malformed quotation number is asked for again rather than guessed.
- **Refusals:**
  - Creating, changing or deleting customers or products (`ENTITY_CRUD_RE`) is refused even if the LLM picked an operation.
  - An operation also needs quotation vocabulary in the message (`DOMAIN_RE`: 報價 / 訂單 / QT-…), unless the message answers a pending clarification question.
- **Multi-turn:**
  - If a pending operation exists and the new message supplies a missing field, the operation continues, even if the LLM labelled that message `off_topic`.
  - When a client seeds a session with earlier turns as plain events but no state (as `agents-cli eval` does for multi-turn cases), `load_context` rebuilds the history from those events, and recognizes the agent's own clarification question there to recover `pending_intent`.
- **Model failures:** missing credentials, 429 and 503 errors become `Intent(intent="model_error")` through ADK callbacks and go straight to `respond` with a clear message. `docker compose up` therefore works without an API key.

Every user message runs the graph again from `START`. Session state carries what one turn needs from the previous one.

## How to add an operation

Example: an MCP tool `archive_quotation(quotation_number)` already exists in `mcp_server/server.py`.

1. **`agent.py` → `OPERATIONS`:** add `"archive_quotation": ("quotation_number",)`, mapping the tool name to its required fields. The `McpToolset` filter is built from this dict.
2. **`agent.py` → `Intent.intent`:** add `"archive_quotation"` to the `Literal`.
3. **`agent.py` → node:** add an operation node and list it in `OPERATION_NODES`. The function name must equal the tool name, because it's also the route value:
   ```python
   async def archive_quotation(ctx: Context, node_input: ToolCall) -> dict:
       return (await _call_mcp(ctx, node_input)).model_dump()
   ```
   The graph wires `route → archive_quotation → respond` from `OPERATION_NODES` automatically.
4. **`prompts.py`:**
   - Describe the intent in `CLASSIFIER_INSTRUCTION`.
   - Add a label to `OPERATION_LABELS`, used in clarification questions and error messages.
   - List the new operation in the menus of `OFF_TOPIC_REPLY` and `UNCLEAR_REPLY`.
5. **New argument types** (e.g. a date): add the field to `Intent`, a regex in `_extract_fields`, and a label in `prompts.FIELD_LABELS`. If users may phrase the request without 報價/訂單/QT-, extend `DOMAIN_RE`.
6. **Copy-on-write tools:** add the name to `MODIFYING_OPERATIONS` so the reply says the original was not changed.
7. **Tests:**
   - Add a case to `tests/unit/test_routing.py` (message → route + args).
   - Add a graph test to `tests/integration/test_agent.py` with `fake_llm`.
   - Add an eval case (`eval_case_id` = the tool name) to `tests/eval/datasets/quotation-actions.json`.
   - Run `uv run pytest tests -q` (no model calls).

## Configuration

Set these in `agent/.env` for local runs. Docker Compose reads the root `.env` instead.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Google AI Studio key (option A) |
| `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | —, —, `global` | Vertex AI instead of an API key (option B). `GOOGLE_CLOUD_PROJECT` is also used by `agents-cli eval`. |
| `AGENT_MODEL` | `gemini-3.8-flash` | model for `classify_intent` |
| `JUDGE_MODEL` | `AGENT_MODEL` | model for the eval LLM judges (see "Evaluation") |
| `MCP_URL` | `http://localhost:8010/mcp` | MCP server. Compose sets `http://mcp-server:8000/mcp`. |
| `ALLOW_ORIGINS` | — | CORS origins for the agent API |
| `RUN_LLM_TESTS` | unset | `1` runs the pytest tests that call the real model |

`agent.py` loads `agent/.env` itself, because `fast_api_app.py` imports the agent before its own `load_dotenv()`. Variables already set in the environment win over the file.

## Local development

```bash
# backing services: db, backend and mcp-server (published on localhost:8010)
docker compose up -d db backend mcp-server
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql

cd agent
cp .env.example .env                 # fill GEMINI_API_KEY; MCP_URL=http://localhost:8010/mcp
uv sync --group dev --extra eval
```

**Playground on port 8501.** `agents-cli playground` defaults to port **8080**, which the `backend` container already publishes. Run it on 8501 with either command; the first one starts the second:

```bash
agents-cli playground --port 8501
uv run adk web . --host 127.0.0.1 --port 8501 --allow_origins '*' --reload_agents
```

Open http://localhost:8501 and pick `quotation_agent`. The playground shows every event. The answer is the last one, from `respond`; the JSON above it is `classify_intent`'s output.

```bash
agents-cli run "我要查詢報價單，報價單編號：QT-20260330-001"   # one-off request from the terminal

uv run pytest tests/unit -q          # routing rules: no LLM, no MCP
uv run pytest tests/integration -q   # whole graph, fake classifier, real MCP (skipped if MCP is down); no model calls
RUN_LLM_TESTS=1 uv run pytest tests/integration -q   # also the real-model tests (uses quota)
uv run --extra lint ruff check quotation_agent tests
```

Each chat message costs exactly one model call (`classify_intent`). On the AI Studio free tier (20 requests/day per model), you can develop on a different model, e.g. `AGENT_MODEL=gemini-3.5-flash-lite`. Switch back to `gemini-3.8-flash` for acceptance runs.

## Docker

The `agent` service in `docker-compose.yml` runs `uvicorn quotation_agent.fast_api_app:app` on port 8080. That port is only reachable inside the Compose network, and the frontend's nginx forwards `/agent-api/` to it. The service waits for `mcp-server`. It reads `GEMINI_API_KEY`, the Vertex variables, `AGENT_MODEL` and `ALLOW_ORIGINS` from the root `.env`. `docker-compose.build.yml` builds it from this directory, and CI builds and pushes the image as `ghcr.io/<repo>/agent`.

Vertex AI inside Docker also needs the gcloud credentials file in the container. It is not mounted by default, so that `docker compose up` works on machines without gcloud. Add it with an override, for example:

```yaml
services:
  agent:
    volumes:
      - ${HOME}/.config/gcloud/application_default_credentials.json:/gcloud/adc.json:ro
    environment:
      GOOGLE_APPLICATION_CREDENTIALS: /gcloud/adc.json
```


## Running the eval

Two datasets in `tests/eval/datasets/` (`quotation-actions.json` with the 6 operations; `quotation-guardrails.json` with 2 off-topic refusals plus a multi-turn clarification) are scored on four metrics from `tests/eval/eval_config.yaml`: `custom_response_quality`, `link_present`, `refusal_or_action` and `agent_turn_count`.

```bash
gcloud auth application-default login   # once: agents-cli's grader needs gcloud credentials (no billing needed)

agents-cli eval run --dataset tests/eval/datasets/quotation-guardrails.json --qps 0.2
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql   # the actions cases create data
agents-cli eval run --dataset tests/eval/datasets/quotation-actions.json --qps 0.2

python3 ../scripts/eval_summary.py artifacts/grade_results/results_<timestamp>.json --explain
```

- **Use `--qps 0.2`.** agents-cli dispatches judge calls at 15/s by default, which hits the free tier's 15 requests/minute limit.
- **Re-grade without rerunning the agent.** Saved traces can be scored again with `agents-cli eval grade --traces artifacts/traces/<file>.json --qps 0.2`.

## Evaluation: `refusal_or_action` runs as a local judge (deviation from spec 2.7)

`tests/eval/eval_config.yaml` runs the four metrics from spec 2.7: `custom_response_quality`, `link_present`, `refusal_or_action` and `agent_turn_count`. One of them is implemented differently from the spec:

- **Spec:** `refusal_or_action` is an LLM judge defined by a `prompt_template`. agents-cli sends any `prompt_template`-only metric to the **Vertex AI eval service**.
- **Problem:** that service only runs on a GCP project **with billing enabled**. On a project without billing it fails with
  `403 PERMISSION_DENIED … This API method requires billing to be enabled`.
  With the placeholder `GOOGLE_CLOUD_PROJECT=local-only` it fails with `403 … SERVICE_DISABLED`. agents-cli 1.9.0 and 1.10.0 behave the same.
- **What we do instead:** the entry also has `custom_function_file: refusal_judge.py`. agents-cli then runs the metric in-process, and `refusal_judge.py` sends the judge prompt to Gemini through `GEMINI_API_KEY` (AI Studio) on `JUDGE_MODEL` (see below). It returns the same 0/1 score.
- **The rules still live in the `prompt_template`.** `refusal_judge.py` hard-codes no rules. At grading time it reads the `prompt_template` of `refusal_or_action` from the config (the `--config` file, else `tests/eval/eval_config.yaml`) and fills in `{response}` and `{agent_data}`. Editing the template, as `eval-lab.md` section 5 asks, changes the judge's behavior. This was verified: inverting rule 1 turned the `off_topic_weather` score from 1 to 0, and restoring it brought back 1.
- **Switching back to Vertex AI** once a project has billing: delete the `custom_function_file: refusal_judge.py` line. The commented-out original definition in `eval_config.yaml` shows the result.

Remaining requirements and limits:

- **gcloud credentials are still required.** agents-cli's grader creates a Google Cloud Storage client even when every metric runs locally, so run `gcloud auth application-default login` once. No billing is needed.
- **`scripts/grading` is unchanged.** Its own `eval_config.yaml` still defines `refusal_or_action` as a Vertex-only `prompt_template`, so on a project without billing `grade_agent.py` cannot score that component.
- **Judge calls use your model quota.** Each graded case costs one call per LLM judge on top of the agent's own call. Point the judges at a different model with `JUDGE_MODEL` (below) to keep them off the agent model's quota.

### `JUDGE_MODEL`: model for the eval judges

Both LLM judges, `custom_response_quality` (`response_quality.py`) and `refusal_or_action` (`refusal_judge.py`), call the model named in `JUDGE_MODEL`. If it's unset they use `AGENT_MODEL`, and if that's unset too, `gemini-3.8-flash`. Set it in `agent/.env`; agents-cli loads that file when it grades.

```
AGENT_MODEL=gemini-3.8-flash         # the agent under test (spec 2.6)
JUDGE_MODEL=gemini-3.5-flash-lite    # the two eval judges
```

The spec only fixes the agent's model. A separate judge model keeps grading off the agent model's quota. On the AI Studio free tier (20 requests/day per model), a full `agents-cli eval run` over both datasets costs 9 agent calls plus 18 judge calls. With `JUDGE_MODEL` on another model, only the 9 agent calls count against `gemini-3.8-flash`.

`scripts/grading` has its own judge (`scripts/grading/response_quality.py`) that reads `AGENT_MODEL`, not `JUDGE_MODEL`. `grade_agent.py` therefore still spends agent-model quota on judging.
