---
type: playbook
title: 訂單履約流程
summary: 訂單從建立到結案（或取消）的一般流程，以及各階段可以做什麼。
sources:
  - id: order-service
    path: backend/services/order_service.go
  - id: order-handler
    path: backend/handlers/order_handler.go
  - id: convert-to-order
    path: mcp_server/server.py
  - id: seed
    path: scripts/seed-test-data.sql
updated: 2026-10-23
---

# 訂單履約流程

```
（報價單）──轉訂單──▶ pending ──確認──▶ confirmed ──交貨、驗收──▶ completed
                        │                 │
                        └──────取消───────┴──▶ cancelled
```

## 1. 建立訂單 → `pending`
訂單可以由報價單轉換而來（保留 `quotation_id`）[^convert-to-order]，也可以不經報價直接建立[^seed]。新訂單一律是 `pending`[^order-service]。詳見 `glossary/order-status-pending`。

## 2. 確認 → `confirmed`
內部核准、付款條件等確認後，訂單進入執行：備貨、出貨或安裝。詳見 `glossary/order-status-confirmed`。

## 3. 結案 → `completed`
交貨並完成驗收或啟用後結案。詳見 `glossary/order-status-completed`。

## 取消 → `cancelled`
在結案前都可能取消。詳見 `glossary/order-status-cancelled`。

## 注意
- 上圖是依狀態名稱與種子資料整理的**一般流程**；系統本身不強制狀態轉換順序，也沒有記錄狀態變更歷程[^order-service]。
- 狀態變更由內部人員處理；目前的 REST API 沒有變更訂單狀態的功能[^order-handler]。order_agent 只能查詢（見 `decisions/0001-order-agent-read-only`）。

[^order-service]: `backend/services/order_service.go`：Create 以 pending 建立訂單；Update 的輸入不含狀態欄位。
[^order-handler]: `backend/handlers/order_handler.go`：訂單 API 為列表、查詢、新增、更新、刪除，狀態可為 pending、confirmed、completed、cancelled。
[^convert-to-order]: `mcp_server/server.py` 的 `convert_to_order`：依報價單建立訂單並設定 `quotation_id`。
[^seed]: `scripts/seed-test-data.sql`：10 張範例訂單，其中 3 張沒有來源報價單（例如備註「急單 - 直接下訂不走報價」）。
