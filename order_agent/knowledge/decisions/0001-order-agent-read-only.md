---
type: decision
title: ADR 0001：order_agent 為唯讀
summary: order_agent 只能查詢，任何新增、修改、取消、刪除都請使用者到網頁介面操作。
status: accepted
date: 2026-10-23
sources:
  - id: spec
    path: agent2-spec-prompt.md
  - id: order-handler
    path: backend/handlers/order_handler.go
updated: 2026-10-23
---

# ADR 0001：order_agent 為唯讀

## Context
order_agent 是對外的訂單與客戶服務助理。後端 API 允許新增、更新、刪除訂單、客戶與產品[^order-handler]，但這些操作有商業影響，且目前沒有核准流程或稽核紀錄。規格要求這個 Agent 為唯讀[^spec]。

## Options considered
1. **完全唯讀**：只提供查詢，所有寫入請求由程式拒絕並引導到網頁介面。
2. **有限寫入**（例如取消訂單），搭配使用者確認。
3. **完整寫入**，與網頁介面功能相同。

## Decision
採用選項 1。寫入意圖由程式（不是只靠提示詞）判定並禮貌拒絕，回覆中指引使用者到網頁介面 http://localhost:3000 操作。order_mcp_server 只提供 GET 類工具。

## Consequences
- 優點：Agent 不會因誤判意圖而改到資料；資安與稽核風險低。
- 缺點：使用者需要切換到網頁介面才能修改。
- 若未來要支援寫入，需要新的 ADR，並加入確認步驟與稽核紀錄。

[^spec]: `agent2-spec-prompt.md` 1.5：建立、取消、變更、刪除訂單／客戶／產品的請求一律由程式拒絕。
[^order-handler]: `backend/handlers/order_handler.go`：訂單有 POST、PUT、DELETE 端點（客戶、產品亦同）。
