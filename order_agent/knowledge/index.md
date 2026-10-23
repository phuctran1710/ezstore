---
type: index
title: EZStore 訂單知識庫索引
summary: order_agent 的知識入口：先讀這頁的一行摘要，需要細節時再開對應的概念檔。
sources: []
updated: 2026-10-24
---

# EZStore 訂單知識庫

每個概念一個檔案。概念 ID = 相對於本資料夾、不含 `.md` 的路徑（例如 `glossary/order-status-pending`）。order_agent 依程式規則（狀態名稱 → 檔案路徑）選檔，不使用向量資料庫。

## glossary — 訂單狀態

| 概念 ID | 摘要 |
|---|---|
| `glossary/order-status-pending` | 待處理：訂單已建立，尚待內部核准或確認付款等條件。 |
| `glossary/order-status-confirmed` | 已確認：訂單已確認，正在備貨、出貨或安裝中。 |
| `glossary/order-status-completed` | 已完成：已交貨並完成驗收或啟用，訂單結案。 |
| `glossary/order-status-cancelled` | 已取消：訂單已取消，不會再出貨。 |

## playbooks — 作業流程

| 概念 ID | 摘要 |
|---|---|
| `playbooks/order-fulfillment` | 訂單從建立到結案（或取消）的一般流程，以及各階段可以做什麼。 |

## decisions — 架構決策（ADR）

| 概念 ID | 摘要 |
|---|---|
| `decisions/0001-order-agent-read-only` | order_agent 只能查詢，任何新增、修改、取消、刪除都請使用者到網頁介面操作。 |
| `decisions/0002-delegate-quotations-via-a2a` | 報價單相關問題透過 A2A 交給 quotation_agent，order_agent 不直接讀報價單內容。 |

## systems — 系統說明

| 概念 ID | 摘要 |
|---|---|
| `systems/ezstore-orders` | EZStore 訂單資料包含哪些欄位，以及目前的限制（沒有狀態歷程、沒有依訂單編號查詢的 API）。 |

## lessons — 教訓（無究責格式）

| 概念 ID | 摘要 |
|---|---|
| `lessons/0001-eval-judge-requires-billing` | prompt_template 型評審指標只能在開啟 billing 的 GCP 專案執行；改成讀同一份 prompt_template 的本機評審後，四個指標都能評分。 |

變更紀錄見 [log.md](log.md)。
