FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /code

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY quotation_agent ./quotation_agent

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION} \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=20 \
  CMD uv run --no-sync python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/list-apps', timeout=2)"

CMD ["uv", "run", "--no-sync", "uvicorn", "quotation_agent.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]
