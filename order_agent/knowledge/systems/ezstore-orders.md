---
type: system
title: EZStore 訂單資料
summary: EZStore 訂單資料包含哪些欄位，以及目前的限制（沒有狀態歷程、沒有依訂單編號查詢的 API）。
sources:
  - id: order-model
    path: backend/models/order.go
  - id: order-repo
    path: backend/repositories/order_repo.go
  - id: order-handler
    path: backend/handlers/order_handler.go
  - id: order-service
    path: backend/services/order_service.go
  - id: order-mcp
    path: order_mcp_server/server.py
updated: 2026-10-23
---

# EZStore 訂單資料

## 訂單包含的資料
- 訂單編號 `order_number`（格式 `ORD-YYYYMMDD-NNN`）、客戶、狀態、總價、備註、建立與更新時間[^order-model]。
- 品項：產品名稱、單價、數量、小計[^order-model]。
- 來源報價單：只有 `quotation_id`；不是由報價單轉來的訂單，這個欄位是空值[^order-model]。

## 限制
- **沒有依訂單編號查詢的 API**：後端只能依 ID 查單筆，列表只支援 `status` 與 `customer_id` 篩選；其他參數會被忽略並回傳全部訂單[^order-handler]。order_mcp_server 以「分頁列出後比對編號」處理[^order-mcp]。
- **查詢訂單不會帶出報價單內容**：後端載入訂單時只附上客戶與品項[^order-repo]，所以報價單編號要再用 `quotation_id` 查一次。
- **沒有狀態歷程**：只有目前的 `status`，看不到何時、由誰變更；也沒有變更狀態的 API[^order-service]。
- **狀態沒有驗證**：用不存在的狀態篩選時，後端回傳 200 和空結果，而不是錯誤[^order-handler]。

[^order-model]: `backend/models/order.go`：Order 與 OrderItem 欄位；`QuotationID` 可為空。
[^order-repo]: `backend/repositories/order_repo.go`：列表與單筆查詢只 `Preload("Customer")` 與 `Preload("Items")`。
[^order-handler]: `backend/handlers/order_handler.go`：列表參數為 page、page_size、status、customer_id。
[^order-service]: `backend/services/order_service.go`：Update 的輸入不含狀態欄位。
[^order-mcp]: `order_mcp_server/server.py`：`get_order_by_number`。
