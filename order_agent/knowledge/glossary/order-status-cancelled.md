---
type: glossary
title: 訂單狀態 cancelled（已取消）
summary: 已取消：訂單已取消，不會再出貨。
status: cancelled
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

# 訂單狀態 `cancelled`（已取消）

## 意義
訂單已取消，不會再出貨或請款；網頁介面顯示為「已取消」[^status-badge]。常見原因是客戶預算或採購決策改變[^seed]。

## 常見的下一步
取消後沒有後續狀態[^order-handler]（系統不強制轉換順序[^order-service]）。若客戶之後仍有需求，請重新建立報價單或訂單。

## 聯絡窗口
負責這張訂單的業務窗口

[^order-handler]: `backend/handlers/order_handler.go`：訂單列表 API 說明列出四種狀態 pending（待處理）、confirmed（已確認）、completed（已完成）、cancelled（已取消）。
[^status-badge]: `frontend/src/components/shared/StatusBadge.tsx`：網頁介面顯示的中文狀態名稱。
[^order-service]: `backend/services/order_service.go`：新訂單一律以 pending 建立；更新訂單的 API 不包含狀態欄位，系統不強制狀態轉換規則。
[^seed]: `scripts/seed-test-data.sql`：cancelled 訂單的備註範例：「客戶預算凍結，取消訂單」「客戶改向其他供應商採購」。
