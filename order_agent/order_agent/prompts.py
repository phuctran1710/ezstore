"""Prompts and fixed replies for the order agent.

Only CLASSIFIER_INSTRUCTION is sent to the LLM. Every other string here is a
fixed reply chosen by program logic in agent.py.
"""

CLASSIFIER_INSTRUCTION = """\
你是 EZStore 訂單與客戶服務助理的「意圖分類器」。你只負責把使用者最新的一句話分類並抽出欄位，
不回答問題、不產生任何對話文字，只輸出符合 schema 的 JSON。使用者可能用中文或英文。

intent 只能是下列其中之一：
- get_order：查詢某張訂單的資訊或狀態（需要 order_number）
- list_customer_orders：查詢某客戶的訂單清單（需要 customer_name）
- explain_status：詢問某個訂單狀態是什麼意思（需要 status）
- order_quotation：詢問某張訂單是從哪張報價單來的（需要 order_number）
- read_only_request：要求新增、建立、取消、修改、變更、更新、刪除訂單、客戶或產品
- off_topic：與訂單、客戶查詢無關的需求，例如天氣、閒聊、寫程式
- unclear：和訂單有關，但看不出是上面哪一種
- model_error：系統保留值，你永遠不要輸出這個值

欄位規則：
- order_number 格式為 ORD-YYYYMMDD-NNN（例如 ORD-20260118-001），沒提供就填 null，不要猜。
- customer_name 原樣抄寫使用者提供的客戶名稱，沒提供就填 null。
- status 只能是 pending、confirmed、completed、cancelled 其中之一（待處理=pending、已確認=confirmed、
  已完成=completed、已取消=cancelled），沒提到就填 null。
- error_detail 永遠填 null。

多輪對話：輸入中若有「上一輪待補資料的操作」，而使用者這一句只是在補欄位
（例如只給了一個訂單編號、客戶名稱或狀態），就沿用該操作的 intent，並把補上的欄位填入。
若使用者這一句提出了全新的需求，就依新需求分類。
"""

WEB_UI_URL = "http://localhost:3000"

READ_ONLY_REPLY = (
    "抱歉，我是唯讀的訂單與客戶服務助理，不能新增、取消、修改或刪除訂單、客戶或產品。\n"
    f"如需變更資料，請到 EZStore 網頁介面操作：{WEB_UI_URL}"
)

OFF_TOPIC_REPLY = (
    "抱歉，我是訂單與客戶服務助理，只能協助訂單與客戶的查詢，無法處理這個需求。\n"
    "我可以幫您：\n"
    "1. 查詢訂單（需提供訂單編號）\n"
    "2. 查詢客戶的訂單清單（需提供客戶名稱）\n"
    "3. 說明訂單狀態的意思（pending、confirmed、completed、cancelled）\n"
    "4. 查詢訂單的來源報價單（需提供訂單編號）"
)

UNCLEAR_REPLY = (
    "請問您想查詢什麼？我可以：查詢訂單、查詢客戶的訂單清單、說明訂單狀態的意思，"
    "或查詢訂單的來源報價單。"
)

OPERATION_LABELS = {
    "get_order": "查詢訂單",
    "list_customer_orders": "查詢客戶的訂單清單",
    "explain_status": "說明訂單狀態",
    "order_quotation": "查詢訂單的來源報價單",
}

FIELD_LABELS = {
    "order_number": "訂單編號（例如 ORD-20260118-001）",
    "customer_name": "客戶名稱（例如 史塔克工業）",
    "status": "訂單狀態（pending、confirmed、completed 或 cancelled）",
}

CLARIFY_TEMPLATE = "好的，我可以幫您{operation}，請提供{fields}。"

AMBIGUOUS_CUSTOMER_TEMPLATE = "找到多位符合「{query}」的客戶：\n{candidates}\n請問是哪一位？請回覆完整的客戶名稱或編號。"

STATUS_LABELS = {
    "pending": "待處理",
    "confirmed": "已確認",
    "completed": "已完成",
    "cancelled": "已取消",
}

NO_QUOTATION_REPLY = (
    "訂單 {order_number} 不是由報價單轉來的，沒有來源報價單。\n系統連結: {order_link}"
)

QUOTATION_FOUND_TEMPLATE = (
    "訂單 {order_number} 來自報價單 {quotation_number}。\n"
    "報價單系統連結: {quotation_link}\n"
    "訂單系統連結: {order_link}\n\n"
    "以下是報價單助理（quotation_agent，透過 A2A）提供的報價單資訊：\n{details}"
)

QUOTATION_AGENT_DOWN_TEMPLATE = (
    "訂單 {order_number} 來自報價單 {quotation_number}。\n"
    "報價單系統連結: {quotation_link}\n"
    "訂單系統連結: {order_link}\n"
    "目前無法連線報價單助理（{detail}），暫時無法提供報價單的詳細內容，請稍後再試。"
)

NOT_FOUND_REPLY = "{detail}，請確認名稱或編號是否正確後再試一次。"

TOOL_ERROR_REPLY = "抱歉，執行「{operation}」時發生錯誤：{detail}"

MODEL_ERROR_REPLY = "抱歉，AI 模型目前無法使用，請聯絡系統管理員。\n原因：{detail}"

NO_CREDENTIALS_DETAIL = (
    "Agent 沒有設定模型憑證。請在專案根目錄的 .env 設定 GEMINI_API_KEY"
    "（或設定 GOOGLE_GENAI_USE_VERTEXAI=true 與 GOOGLE_CLOUD_PROJECT 使用 Vertex AI），"
    "然後重新啟動 order-agent 服務。"
)
