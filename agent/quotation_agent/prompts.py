"""Prompts and fixed replies for the quotation agent.

Only CLASSIFIER_INSTRUCTION is sent to the LLM. Every other string here is a
fixed reply chosen by program logic in agent.py.
"""

CLASSIFIER_INSTRUCTION = """\
你是 EZStore 報價單管理系統的「意圖分類器」。你只負責把使用者最新的一句話分類並抽出欄位，
不回答問題、不呼叫工具、不產生任何對話文字，只輸出符合 schema 的 JSON。

intent 只能是下列其中之一：
- get_quotation：查詢某張報價單的詳細資訊（需要 quotation_number）
- list_customer_quotations：查詢某客戶的報價單清單（需要 customer_name）
- duplicate_quotation：複製報價單（需要 quotation_number）
- update_pricing_factor：修改報價單的報價因子（需要 quotation_number、new_pricing_factor）
- adjust_total_price：修改報價單的總價（需要 quotation_number、target_total_price）
- convert_to_order：將報價單轉成訂單（需要 quotation_number）
- off_topic：與上述報價單操作無關的需求，例如天氣、閒聊、寫程式、
  新增/修改/刪除客戶或產品、查詢產品庫存等
- unclear：和報價單有關，但看不出是上面哪一種操作
- model_error：系統保留值，你永遠不要輸出這個值

欄位規則：
- quotation_number 格式為 QT-YYYYMMDD-NNN（例如 QT-20260330-001），使用者沒提供就填 null，不要猜。
- customer_name 原樣抄寫使用者提供的客戶名稱，沒提供就填 null。
- new_pricing_factor、target_total_price 只填數字，沒提供就填 null。
- error_detail 永遠填 null。

多輪對話：輸入中若有「上一輪待補資料的操作」，而使用者這一句只是在補欄位
（例如只給了一個報價單編號、客戶名稱或數字），就沿用該操作的 intent，並把補上的欄位填入。
若使用者這一句提出了全新的需求，就依新需求分類。
"""

OFF_TOPIC_REPLY = (
    "抱歉，我是報價單管理助理，只能處理報價單相關的操作，無法協助這個需求。\n"
    "我可以幫您：\n"
    "1. 查詢報價單（需提供報價單編號）\n"
    "2. 查詢客戶的報價單清單（需提供客戶名稱）\n"
    "3. 複製報價單\n"
    "4. 修改報價單報價因子\n"
    "5. 修改報價單總價\n"
    "6. 將報價單轉為訂單"
)

UNCLEAR_REPLY = (
    "請問您想對報價單進行哪一種操作？我可以：查詢報價單、查詢客戶的報價單清單、"
    "複製報價單、修改報價因子、修改總價，或將報價單轉為訂單。"
)

# Human-readable name of each operation, used in clarification questions.
OPERATION_LABELS = {
    "get_quotation": "查詢報價單",
    "list_customer_quotations": "查詢客戶的報價單清單",
    "duplicate_quotation": "複製報價單",
    "update_pricing_factor": "修改報價單報價因子",
    "adjust_total_price": "修改報價單總價",
    "convert_to_order": "將報價單轉為訂單",
}

FIELD_LABELS = {
    "quotation_number": "報價單編號（例如 QT-20260330-001）",
    "customer_name": "客戶名稱（例如 史塔克工業）",
    "new_pricing_factor": "新的報價因子（例如 1.5）",
    "target_total_price": "目標總價（例如 8000）",
}

CLARIFY_TEMPLATE = "好的，我可以幫您{operation}，請提供{fields}。"

# Appended to modification replies (requirement 1.7).
COPY_ON_WRITE_NOTE = (
    "提醒您：系統已先複製一份新的報價單並在副本上修改，原始報價單不會被更動。"
)

MODEL_ERROR_REPLY = "抱歉，AI 模型目前無法使用，請聯絡系統管理員。\n原因：{detail}"

NO_CREDENTIALS_DETAIL = (
    "Agent 沒有設定模型憑證。請在專案根目錄的 .env 設定 GEMINI_API_KEY"
    "（或設定 GOOGLE_GENAI_USE_VERTEXAI=true 與 GOOGLE_CLOUD_PROJECT 使用 Vertex AI），"
    "然後重新啟動 agent 服務。"
)

NOT_FOUND_REPLY = "{detail}，請確認名稱或編號是否正確後再試一次。"

MCP_ERROR_REPLY = "抱歉，執行「{operation}」時發生錯誤：{detail}"
