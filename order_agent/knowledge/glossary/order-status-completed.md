---
type: glossary
title: 訂單狀態 completed（已完成）
summary: 已完成：已交貨並完成驗收或啟用，訂單結案。
status: completed
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

# 訂單狀態 `completed`（已完成）

## 意義
訂單已交貨並完成驗收或啟用，視為結案；網頁介面顯示為「已完成」[^status-badge][^seed]。

## 常見的下一步
訂單本身沒有後續狀態[^order-handler]（系統不強制轉換順序[^order-service]）。若需要再次採購，請建立新的報價單或訂單；產品問題請走售後服務。

## 聯絡窗口
客服窗口（售後服務）

[^order-handler]: `backend/handlers/order_handler.go`：訂單列表 API 說明列出四種狀態 pending（待處理）、confirmed（已確認）、completed（已完成）、cancelled（已取消）。
[^status-badge]: `frontend/src/components/shared/StatusBadge.tsx`：網頁介面顯示的中文狀態名稱。
[^order-service]: `backend/services/order_service.go`：新訂單一律以 pending 建立；更新訂單的 API 不包含狀態欄位，系統不強制狀態轉換規則。
[^seed]: `scripts/seed-test-data.sql`：completed 訂單的備註範例：「已完成交貨與驗收」「Q1耗材已全數到貨」。
