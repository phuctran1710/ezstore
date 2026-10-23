---
type: decision
title: ADR 0002：報價單問題透過 A2A 交給 quotation_agent
summary: 報價單相關問題透過 A2A 交給 quotation_agent，order_agent 不直接讀報價單內容。
status: accepted
date: 2026-10-23
sources:
  - id: spec
    path: agent2-spec-prompt.md
  - id: orders-system
    path: order_agent/knowledge/systems/ezstore-orders.md
updated: 2026-10-23
---

# ADR 0002：報價單問題透過 A2A 交給 quotation_agent

## Context
使用者常問「這張訂單是從哪張報價單來的」。訂單只記錄 `quotation_id`，沒有報價單編號或內容[^orders-system]。EZStore 已有負責報價單的 quotation_agent，並以 A2A 對外提供服務[^spec]。

## Options considered
1. **透過 A2A 委派**：order_agent 用 quotation_id 查到報價單編號後，請 quotation_agent 查詢該報價單。
2. **直接呼叫後端或 quotation 的 MCP Server** 讀取報價單內容。
3. **把使用者原句轉給 quotation_agent**。

## Decision
採用選項 1。order_agent 只傳送由程式組成的查詢句「我要查詢報價單，報價單編號：<編號>」，從不轉送使用者原文，並且只採用對方 `respond` 節點的回覆文字。

## Consequences
- 報價單的呈現方式與規則（例如純文字連結）只在 quotation_agent 維護一份。
- 由程式組句可避免使用者文字讓 quotation_agent 執行修改類操作（複製、改價、轉訂單）。
- 多一次網路呼叫；quotation_agent 無法連線時，order_agent 必須回覆清楚的錯誤訊息，並仍可提供報價單編號與連結。

[^spec]: `agent2-spec-prompt.md` 0 與 2.4：quotation_agent 的 A2A 位址，以及只送程式組成的查詢句、只用 respond 節點文字的要求。
[^orders-system]: 見 `systems/ezstore-orders`：訂單記錄 quotation_id，查詢訂單時不會帶出報價單內容。
