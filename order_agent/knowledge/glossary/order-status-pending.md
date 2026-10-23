---
type: glossary
title: 訂單狀態 pending（待處理）
summary: 待處理：訂單已建立，尚待內部核准或確認付款等條件。
status: pending
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

# 訂單狀態 `pending`（待處理）

## 意義
訂單已建立，但還沒有正式確認。每張新訂單一開始都是這個狀態[^order-service]，網頁介面顯示為「待處理」[^status-badge]。常見原因是等待內部核准或付款條件確認[^seed]。

## 常見的下一步
確認相關條件後，訂單會改為 `confirmed`（已確認）；若客戶或公司決定不做了，則改為 `cancelled`（已取消）[^order-handler]。

## 聯絡窗口
負責這張訂單的業務窗口

[^order-handler]: `backend/handlers/order_handler.go`：訂單列表 API 說明列出四種狀態 pending（待處理）、confirmed（已確認）、completed（已完成）、cancelled（已取消）。
[^status-badge]: `frontend/src/components/shared/StatusBadge.tsx`：網頁介面顯示的中文狀態名稱。
[^order-service]: `backend/services/order_service.go`：新訂單一律以 pending 建立；更新訂單的 API 不包含狀態欄位，系統不強制狀態轉換規則。
[^seed]: `scripts/seed-test-data.sql`：pending 訂單的備註範例：「等待採購主管核准」「待財務確認付款方式」「急單 - 直接下訂不走報價」。
