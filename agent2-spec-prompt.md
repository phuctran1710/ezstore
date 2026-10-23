# Spec: Order & Customer Service Agent (order_agent)

## 0. Existing parts (do not rewrite)
- Backend REST API (backend/), frontend (frontend/) and mcp_server/: must NOT be modified.
- Quotation agent (agent/, app quotation_agent): exposes A2A at http://agent:8080/a2a/quotation_agent. Small config changes in agent/ and its Compose service are allowed (e.g. APP_URL so the agent card advertises the right URL, a clean skills list).
- Seed data: scripts/seed-test-data.sql (10 orders, e.g. ORD-20260118-001 for customer 史塔克工業).

## 1. Features (read-only agent)
1.1 Order lookup: "我要查詢訂單，訂單編號：ORD-20260118-001" → customer, status, total, items, notes, plain-text link http://localhost:3000/orders/<id>, plus a one-line meaning of the status taken from the knowledge base.
1.2 Customer's orders: "我要查詢客戶的訂單清單，客戶名稱：史塔克工業" → all orders with number, status, total, link. If several customers match, ask which one.
1.3 Status explanation from knowledge: "訂單狀態 pending 是什麼意思？" → answer only from the OKF knowledge bundle, and cite the concept used (e.g. "來源：glossary/order-status-pending").
1.4 Source quotation via A2A: "訂單 ORD-20260118-001 是從哪張報價單來的？" → order → quotation_id → quotation number → ask the quotation agent over A2A for that quotation → reply with the quotation summary and link. If quotation_id is null, say the order was not created from a quotation.
1.5 Read-only: requests to create, cancel, change or delete orders/customers/products are refused politely in code, pointing the user to the web UI.
1.6 Off-topic requests (weather, chat, etc.) are refused in code, not only by prompt.
1.7 Missing data (e.g. no order number) → ask for it; the next message continues the task.
1.8 All links are plain text, never Markdown.
1.9 Replies in Traditional Chinese; English input must also be understood.

## 2. Technical requirements
2.1 Python 3.12, Google ADK >= 2.10, graph Workflow API, same pattern as agent/: load_context → classify_intent (the only LLM node, Pydantic output) → route → operation nodes → respond. ADK app name: order_agent. Scaffold with agents-cli into order_agent/ like agent/ was. Use uv and commit uv.lock.
2.2 New MCP server in order_mcp_server/ (mcp Python SDK 2.x, Streamable HTTP), read-only tools that call the backend: get_order_by_number (list and filter, since the backend has no order_number filter), list_customer_orders (customer name → id → orders), get_quotation_number (quotation id → number).
2.3 OKF knowledge bundle in order_agent/knowledge/ following Open Knowledge Format: one concept per .md file, frontmatter with required `type` (plus title, sources), index.md for progressive disclosure, log.md with dated changes, footnote citations [^id]. Minimum content:
  - glossary/: one file per order status (pending, confirmed, completed, cancelled): meaning, typical next step, who to contact.
  - playbooks/order-fulfillment.md: the order lifecycle.
  - decisions/: ADRs (Context, Options considered, Decision, Consequences) for "the order agent is read-only" and "quotation questions are delegated to the quotation agent via A2A".
  - systems/ezstore-orders.md: what the order data contains and its limits (no status history, no order_number filter).
  The agent selects concept files by code (status name → file path); no vector database.
2.4 A2A client: call the quotation agent at QUOTATION_AGENT_URL (env var). Only send lookup sentences built by code (我要查詢報價單，報價單編號：<number>); never forward user text. Use only the respond-node text from the reply. Handle the quotation agent being unreachable with a clear message. order_agent should also expose its own A2A agent card.
2.5 Docker Compose: add order-mcp-server and order-agent services; expose order_agent's ADK dev UI on a free host port (suggest 8502) for the demo. Local playground runs must also be able to reach the quotation agent's A2A endpoint; choose a host port that does not clash with the backend (8080).
2.6 Model via AGENT_MODEL (default gemini-3.8-flash), same credentials as agent/.
2.7 Eval with agents-cli: order_agent/tests/eval/datasets/order-actions.json (1.1–1.4) and order-guardrails.json (1.5, 1.6, a 2-turn 1.7 case). Reuse the four metric names and the local judges (JUDGE_MODEL); run with --qps 0.2.

## 3. Docs
order_agent/README.md: graph diagram, OKF bundle layout and how to add a concept, A2A sequence (order agent → quotation agent), how to run. Add a short section to the root README.

## 4. Stages (stop after each)
4.1 order MCP server: run it and call each tool with curl; show me the outputs.
4.2 OKF bundle: write it and show me the tree and one concept file to review.
4.3 Agent in the playground (port 8502): you tell me what each test sentence should return.
4.4 Docker + A2A end to end: all services up; the source-quotation question works through A2A.
4.5 Eval: both datasets on the dev model.
4.6 Docs and commit.
