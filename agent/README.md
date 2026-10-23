# ezstore-agent

Simple ReAct agent
Agent generated with `agents-cli` version `1.10.0`

## Project Structure

```
ezstore-agent/
├── quotation_agent/         # Core agent code
│   ├── agent.py               # Main agent logic
│   ├── fast_api_app.py        # FastAPI Backend server
│   └── app_utils/             # App utilities and helpers
├── tests/                     # Unit, integration, and load tests
├── GEMINI.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

> 💡 **Tip:** Use [Antigravity CLI](https://antigravity.google/) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI - Install with `uv tool install google-agents-cli`
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        || [A2A Inspector](https://github.com/a2aproject/a2a-inspector) | Launch A2A Protocol Inspector                                                        |

## 🛠️ Project Management

| Command | What It Does |
|---------|--------------|
| `agents-cli scaffold enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `agents-cli infra cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `agents-cli scaffold upgrade` | Auto-upgrade to latest version while preserving customizations |

---

## Development

Edit your agent logic in `quotation_agent/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform, run `agents-cli scaffold enhance`.
To set up your production infrastructure, run `agents-cli infra cicd`.

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.

## A2A Inspector

This agent supports the [A2A Protocol](https://a2a-protocol.org/). Use the [A2A Inspector](https://github.com/a2aproject/a2a-inspector) to test interoperability.
See the [A2A Inspector docs](https://github.com/a2aproject/a2a-inspector) for details.

## Evaluation: `refusal_or_action` runs as a local judge (deviation from spec 2.7)

`tests/eval/eval_config.yaml` runs the four metrics from spec 2.7: `custom_response_quality`, `link_present`, `refusal_or_action` and `agent_turn_count`. One of them is implemented differently from the spec:

- **Spec:** `refusal_or_action` is an LLM judge defined by a `prompt_template`. agents-cli sends any `prompt_template`-only metric to the **Vertex AI eval service**.
- **Problem:** that service only runs on a GCP project **with billing enabled**. On a project without billing it fails with
  `403 PERMISSION_DENIED … This API method requires billing to be enabled`.
  With the placeholder `GOOGLE_CLOUD_PROJECT=local-only` it fails with `403 … SERVICE_DISABLED`. agents-cli 1.9.0 and 1.10.0 behave the same.
- **What we do instead:** the entry also has `custom_function_file: refusal_judge.py`. agents-cli then runs the metric in-process, and `refusal_judge.py` sends the judge prompt to Gemini through `GEMINI_API_KEY` (AI Studio) on `AGENT_MODEL`. It returns the same 0/1 score.
- **The rules still live in the `prompt_template`.** `refusal_judge.py` hard-codes no rules. At grading time it reads the `prompt_template` of `refusal_or_action` from the config (the `--config` file, else `tests/eval/eval_config.yaml`) and fills in `{response}` and `{agent_data}`. Editing the template, as `eval-lab.md` section 5 asks, changes the judge's behavior. This was verified: inverting rule 1 turned the `off_topic_weather` score from 1 to 0, and restoring it brought back 1.
- **Switching back to Vertex AI** once a project has billing: delete the `custom_function_file: refusal_judge.py` line. The commented-out original definition in `eval_config.yaml` shows the result.

Remaining requirements and limits:

- **gcloud credentials are still required.** agents-cli's grader creates a Google Cloud Storage client even when every metric runs locally, so run `gcloud auth application-default login` once. No billing is needed.
- **`scripts/grading` is unchanged.** Its own `eval_config.yaml` still defines `refusal_or_action` as a Vertex-only `prompt_template`, so on a project without billing `grade_agent.py` cannot score that component.
- **Judge calls use your model quota.** Both LLM judges call `AGENT_MODEL`, so each graded case costs one call per judge on top of the agent's own call.
