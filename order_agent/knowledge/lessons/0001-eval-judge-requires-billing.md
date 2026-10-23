---
type: lesson
title: 教訓 0001：refusal_or_action 評審需要開啟 billing 的 Vertex AI
summary: prompt_template 型評審指標只能在開啟 billing 的 GCP 專案執行；改成讀同一份 prompt_template 的本機評審後，四個指標都能評分。
date: 2026-10-23
sources:
  - id: agent-readme
    path: agent/README.md
  - id: eval-config
    path: agent/tests/eval/eval_config.yaml
  - id: refusal-judge
    path: agent/tests/eval/refusal_judge.py
  - id: response-quality
    path: agent/tests/eval/response_quality.py
updated: 2026-10-24
---

# 教訓 0001：refusal_or_action 評審需要開啟 billing 的 Vertex AI

本文採無究責（blameless）格式：記錄系統與流程發生了什麼、為什麼，不追究個人。

## 摘要
quotation_agent 的評估（`agents-cli eval`）有四個指標。其中 `refusal_or_action` 依規格以 `prompt_template` 定義，而 agents-cli 會把這類指標送到 Vertex AI eval service 評分；這個服務只在開啟 billing 的 GCP 專案上執行[^agent-readme]。在不開 billing 的前提下，我們改用本機評審，四個指標都能評分[^eval-config]。

## 影響
- `refusal_or_action` 一度完全無法評分（每個案例都是 error），其他三個指標正常。
- agents-cli 仍會印出摘要並存檔，失敗的指標只是被排除在平均之外，乍看像是成功。
- `scripts/grading/grade_agent.py` 使用自己的評分設定，其中 `refusal_or_action` 仍只能走 Vertex AI，沒有 billing 時無法評到這一項[^agent-readme]。

## 經過（2026-10-23）
1. 只有 AI Studio API key 時，評分步驟直接失敗：agents-cli 的評分程式一定會建立 Google Cloud Storage client，需要 gcloud 的 Application Default Credentials，即使所有指標都在本機執行。
2. 依講師筆記設定佔位專案 `GOOGLE_CLOUD_PROJECT=local-only` 並登入 gcloud 後，三個本機指標可以評分，`refusal_or_action` 回傳 403 `SERVICE_DISABLED`（專案不存在）。agents-cli 1.9.0 與 1.10.0 結果相同。
3. 改用真實專案並啟用 Vertex AI API 後，回傳 403「This API method requires billing to be enabled」[^agent-readme]。決定不開 billing。

## 根本原因
agents-cli 依指標的定義方式決定在哪裡評分：只有 `prompt_template` 的指標交給 Vertex AI eval service（需要 GCP 專案與 billing），有 `custom_function_file` 的指標在本機執行[^agent-readme]。規格要求以 `prompt_template` 定義 `refusal_or_action`，但沒有註明這需要開啟 billing 的 GCP 專案。

## 處理方式
- **本機評審、規則不變**：`refusal_or_action` 加上 `custom_function_file: refusal_judge.py`。`refusal_judge.py` 在評分時讀取 `eval_config.yaml` 中同一份 `prompt_template`，用 AI Studio API key 呼叫 Gemini，給出相同的 0/1 分數[^refusal-judge]。修改 prompt_template 會改變評分結果（反轉規則 1 時 `off_topic_weather` 由 1 變 0，還原後回到 1）[^agent-readme]。
- **保留原本的定義**：Vertex 版的定義以註解形式留在 `eval_config.yaml`，有 billing 時刪掉 `custom_function_file` 那一行即可切回[^eval-config]。
- **獨立的評審模型**：兩個 LLM 評審改用 `JUDGE_MODEL`（未設定時用 `AGENT_MODEL`），讓評分不佔用 Agent 模型每天 20 次的免費配額[^response-quality]。
- **降低送出速率**：agents-cli 預設每秒送出 15 個評分請求，會碰到免費方案每分鐘 15 次的上限（429），因此以 `--qps 0.2` 執行[^agent-readme]。

## 學到的事
- 評估工具的「指標定義方式」也決定了基礎設施需求；採用前先用一個案例試跑評分。
- 讀結果要看每個指標的 `num_cases_error`，不要只看平均。
- 外部筆記中的變通方法要在自己的環境重現後再採用。

## 相關
- 本知識庫目前沒有與評估相關的決策（decisions）或系統（systems）概念；order_agent 的評估沿用上述本機評審、`JUDGE_MODEL` 與 `--qps 0.2`（見 `agent2-spec-prompt.md` 2.7）。
- 完整說明：`agent/README.md` 的「Evaluation」章節[^agent-readme]。

[^agent-readme]: `agent/README.md`：「Running the eval」與「Evaluation: `refusal_or_action` runs as a local judge」章節，包含 403 錯誤訊息、驗證方式與 `--qps 0.2` 的原因。
[^eval-config]: `agent/tests/eval/eval_config.yaml`：四個指標、`refusal_or_action` 的 `custom_function_file` 與 `prompt_template`，以及註解掉的 Vertex 版定義。
[^refusal-judge]: `agent/tests/eval/refusal_judge.py`：在評分時讀取 prompt_template 並呼叫 `JUDGE_MODEL` 的本機評審。
[^response-quality]: `agent/tests/eval/response_quality.py`：`custom_response_quality` 評審，同樣使用 `JUDGE_MODEL`。
