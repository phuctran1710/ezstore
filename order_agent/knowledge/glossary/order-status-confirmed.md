---
type: glossary
title: 訂單狀態 confirmed（已確認）
summary: 已確認：訂單已確認，正在備貨、出貨或安裝中。
status: confirmed
sources:
  - id: order-handler
    path: backend/handlers/order_handler.go
  - id: status-badge
    path: frontend/src/components/shared/StatusBadge.tsx
  - id: order-service
    path: backend/services/order_service.go
  - id: seed
    path: scripts/seed-test-data.sql
updated: 2026-10-24
---

# 訂單狀態 `confirmed`（已確認）

## 意義
訂單條件已確認，開始執行；網頁介面顯示為「已確認」[^status-badge]。此時通常正在下單備貨、安排出貨或安裝[^seed]。

## 常見的下一步
交貨並完成驗收或啟用後，訂單會改為 `completed`（已完成）；若在交貨前取消，則改為 `cancelled`（已取消）[^order-handler]（系統不強制轉換順序[^order-service]）。

## 聯絡窗口
負責這張訂單的業務窗口（交期與安裝排程）

[^order-handler]: `backend/handlers/order_handler.go`：訂單列表 API 說明列出四種狀態 pending（待處理）、confirmed（已確認）、completed（已完成）、cancelled（已取消）。
[^status-badge]: `frontend/src/components/shared/StatusBadge.tsx`：網頁介面顯示的中文狀態名稱。
[^order-service]: `backend/services/order_service.go`：新訂單一律以 pending 建立；更新訂單的 API 不包含狀態欄位，系統不強制狀態轉換規則。
[^seed]: `scripts/seed-test-data.sql`：confirmed 訂單的備註範例：「已確認，排定下週安裝」「軟體授權啟用中」「設備已下單，預計兩週到貨」。
