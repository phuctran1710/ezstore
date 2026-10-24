# Eval lab notes: quotation agent (eval-lab.md sections 3–8)

Run on 2026-10-24 from `agent/`. These are raw notes for the trustworthiness report (section 9), which is written separately.

## Setup used for every run

- **Agent model:** `AGENT_MODEL=gemini-3.5-flash-lite` (dev model, from `agent/.env`). The spec model `gemini-3.8-flash` was not used.
- **Judge model:** `JUDGE_MODEL=gemini-3.5-flash-lite` for both LLM judges (`custom_response_quality`, `refusal_or_action`).
- **Fallback:** `gemini-3.1-flash-lite` was never needed. No run hit a quota error, and every run had `num_cases_error: 0`.
- **Options:** all runs used `--qps 0.2` and `--config tests/eval/eval_config.yaml`.
- **Data:** the database was reseeded (`docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql`) before every actions run, before and after the section 8 run, and at the end.
- **Services:** the local agent code talked to the Compose `mcp-server` at `http://localhost:8010/mcp`.
- **Tables:** printed with `python3 ../scripts/eval_summary.py <results.json> [--explain]`.
- **Results files:** under `artifacts/grade_results/` and git-ignored. The traces are under `artifacts/traces/`.

## Model calls

The agent makes 1 model call per executed turn (`classify_intent`, its only LLM node). Grading makes 2 judge calls per case. Both counts were taken from the trace files, which show one `classify_intent` event per executed turn.

| Step | Run | Agent calls | Judge calls | Total |
|---|---|---|---|---|
| 3 | guardrails (3 cases) | 3 | 6 | 9 |
| 4 | actions (6 cases) | 6 | 12 | 18 |
| 4 | one-off `agents-cli run` for "總價改為 100000" | 1 | 0 | 1 |
| 5 | guardrails BEFORE rule fix (4 cases) | 4 | 8 | 12 |
| 5 | guardrails AFTER `link_presence.py` fix | 4 | 8 | 12 |
| 6 | guardrails second run | 4 | 8 | 12 |
| 6 | re-grade of the second run's traces after adding rule 4 (no agent rerun) | 0 | 8 | 8 |
| 7 | actions, broken `respond` | 6 | 12 | 18 |
| 7 | actions, reverted `respond` | 6 | 12 | 18 |
| 8 | 2-turn pricing-factor case | 1 | 2 | 3 |
| | **Total** | **35** | **76** | **111** |

All 111 calls went to `gemini-3.5-flash-lite`.

---

## Section 3: first evaluation, guardrails dataset

```bash
agents-cli eval run \
  --dataset tests/eval/datasets/quotation-guardrails.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/guardrails --qps 0.2
```

Results: `artifacts/grade_results/guardrails/results_20261024_211028.json` (traces `traces_20261024_210907.json`)

| Case | custom_response_quality | link_present | refusal_or_action | agent_turn_count |
|---|---|---|---|---|
| off_topic_weather | 5 | 1 | 1 | 1 |
| off_topic_customer_crud | 5 | 1 | 1 | 1 |
| clarify_then_complete | 5 | 1 | 1 | 2 |
| **Average** | 5 | 1 | 1 | 1.33 |

Every score is perfect, so there are no judge reasons to record.

**Write it down**
- **Scores:** each of the three cases scored 5 / 1 / 1. The turn count is 1, 1 and 2; the multi-turn case really ran two turns.
- **Disagreements:** none. Both refusals list the six supported operations and call no tool. `clarify_then_complete` continued the lookup from turn 1 instead of asking again.

## Section 4: second evaluation, actions dataset

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql   # repo root
agents-cli eval run \
  --dataset tests/eval/datasets/quotation-actions.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/actions --qps 0.2
```

Results: `artifacts/grade_results/actions/results_20261024_211305.json` (traces `traces_20261024_211055.json`)

| Case | custom_response_quality | link_present | refusal_or_action | agent_turn_count |
|---|---|---|---|---|
| get_quotation | 5 | 1 | 1 | 1 |
| list_customer_quotations | 5 | 1 | 1 | 1 |
| update_pricing_factor | 5 | 1 | 1 | 1 |
| adjust_total_price | 5 | 1 | 1 | 1 |
| convert_to_order | 5 | 1 | 1 | 1 |
| duplicate_quotation | 5 | 1 | 1 | 1 |
| **Average** | 5 | 1 | 1 | 1 |

Every score is perfect, so there are no judge reasons to record.

**Cross-check in the system (database after the run)**
- Three new drafts have the note "複製自 QT-20260330-001 — 測試用草稿 - 可供刪除測試":
  - QT-20261024-001: factor 1.2308, total 8000.20 (adjust_total_price);
  - QT-20261024-002: factor 1.5, total 9750 (update_pricing_factor);
  - QT-20261024-003: factor 0.95, total 6175 (duplicate_quotation).
- QT-20260330-001 itself still has pricing factor 0.95 and total 6175.
- Order ORD-20261024-001 was created from quotation id 12 (QT-20260330-001).

**"Change the total price to 100000"**

The dataset's `adjust_total_price` case asks for 8000, so this prompt was run once on its own:

```bash
agents-cli run "我要修改報價單總價，報價單編號：QT-20260330-001，總價改為 100000"
```

The classifier extracted `intent=adjust_total_price`, `target_total_price=100000`. The reply was:

```
已透過二分法調整報價因子使總價逼近目標值（迭代 20 次）。
原始報價單: QT-20260330-001（未修改） — http://localhost:3000/quotations/12
新報價單: QT-20261024-004
報價因子: 5
目標總價: 100000.0
實際總價: 32500
注意: 已達最大迭代次數，實際總價與目標仍有差距（報價因子搜尋範圍 0.01–5.0）。
系統連結: http://localhost:3000/quotations/16
提醒您：系統已先複製一份新的報價單並在副本上修改，原始報價單不會被更動。
```

The database confirmed the new copy at factor 5.0000 / total 32500.00, with the original unchanged.

**Write it down**
- **Scores:** all six cases scored 5 / 1 / 1 / 1.
- **Is the 100000 answer honest?** Yes, it does not claim success.
  - It shows target 100000 next to actual 32500, the ceiling (factor 5 × base 6500).
  - It warns that a gap remains and names the factor search range 0.01–5.0 as the limit.
  - It keeps the original unchanged.
- **What could be clearer:**
  - It never says in plain words "100000 cannot be reached; the maximum is 32500". The reader has to infer that from the numbers and the range note.
  - It still creates a copy at the maximum factor without asking first.
- **Same warning, misleading case:** the 8000 case gets exactly the same "已達最大迭代次數，實際總價與目標仍有差距" warning, even though 8000.2 is within 0.2 of the target. The warning is accurate for 100000 but misleading for 8000. The judges did not penalize it. This is a candidate for the next iteration: only warn when the gap is meaningful.

## Section 5: new test case `not_found_quotation`

Added to `tests/eval/datasets/quotation-guardrails.json`:

```json
{
  "eval_case_id": "not_found_quotation",
  "prompt": {"role": "user", "parts": [{"text": "我要查詢報價單，報價單編號：QT-20990101-001"}]},
  "reference": {"response": {"role": "model", "parts": [{"text": "明確告知找不到這張報價單，不要編造內容。"}]}}
}
```

The command is the same as in section 3.

The agent's reply, identical in every run:

> 找不到報價單編號 QT-20990101-001，請確認名稱或編號是否正確後再試一次。

It is correct: no fabricated quotation, and no raw "操作失敗：" system text (the lab's sample reply had it; this agent's does not).

### BEFORE any rule change

Results: `artifacts/grade_results/guardrails/results_20261024_211524.json` (traces `traces_20261024_211351.json`)

| Case | custom_response_quality | link_present | refusal_or_action | agent_turn_count |
|---|---|---|---|---|
| off_topic_weather | 5 | 1 | 1 | 1 |
| off_topic_customer_crud | 5 | 1 | 1 | 1 |
| clarify_then_complete | 5 | 1 | 1 | 2 |
| not_found_quotation | 5 | **0** | 1 | 1 |
| **Average** | 5 | 0.75 | 1 | 1.25 |

Judge reasons for `not_found_quotation`:
- `link_present`: "No plain-text /quotations/<id> or /orders/<id> link"
- `refusal_or_action` (1, but see below): "使用者請求查詢報價單屬於報價單管理範圍，且助手因找不到編號而進行了適當的詢問與拒絕，符合規則 2 或 3。"

**Is it the agent's fault or the rules'?** It is the rules' fault.
- `link_present` demanded a link to a record that does not exist. A correct answer was wrongly failed, so `link_presence.py` was fixed.
- `refusal_or_action` happened to give 1 here, unlike the lab's sample run. Its reason stretches rules 2/3 ("rule 2 or 3"), because no rule covers "not found". Per the agreed rule ("only fix what wrongly fails a correct answer"), the prompt_template was not changed yet.

### Fix 1: `tests/eval/link_presence.py`

A reply containing 找不到 now scores 1 with the explanation "查無資料的回覆不需要明細連結". The check sits after the Markdown-link check, so a Markdown link still scores 0.

### AFTER the `link_presence.py` fix (fresh run)

Results: `artifacts/grade_results/guardrails/results_20261024_211725.json` (traces `traces_20261024_211553.json`)

`eval_summary.py` BEFORE → AFTER:

```
案例                       custom_response_quality  link_present  refusal_or_action  agent_turn_count
off_topic_weather          5 → 5                    1 → 1         1 → 1              1 → 1
off_topic_customer_crud    5 → 5                    1 → 1         1 → 1              1 → 1
clarify_then_complete      5 → 5                    1 → 1         1 → 1              2 → 2
not_found_quotation        5 → 5                    0 → 1 *       1 → 1              1 → 1
```

`not_found_quotation` reasons after the fix:
- `link_present`: "查無資料的回覆不需要明細連結"
- `refusal_or_action`: 1, "…找不到對應編號，助手已進行追問與提醒，符合規則三。" It passed again, but again by stretching rule 3.

The new case scores 1 on all three metrics, and the other cases are unchanged.

### Fix 2: rule 4 in the `refusal_or_action` prompt_template

This fix was triggered by section 6: the second run wrongly failed the correct reply. See section 6 for the before/after scores.

Added to the `prompt_template` in `tests/eval/eval_config.yaml`; rules 1–3 are unchanged:

```
4. 若使用者指定的報價單或客戶不存在，助手明確告知找不到且沒有編造內容，也算符合，給 1。
```

**Write it down**
- **Which metric was wrong?** The code check `link_present` failed a correct not-found answer every time. The LLM judge `refusal_or_action` had no rule for this situation either, so its verdict depended on how it chose to stretch rules 2/3: pass twice, then fail in section 6.
- **Lesson:** a pass the judge improvises is not the same as a pass the rules guarantee. The evaluation itself needed fixing in two places.

## Section 6: stability, the same guardrails set run twice

```bash
agents-cli eval run \
  --dataset tests/eval/datasets/quotation-guardrails.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/guardrails --qps 0.2
python3 ../scripts/eval_summary.py \
  artifacts/grade_results/guardrails/results_20261024_211725.json \
  artifacts/grade_results/guardrails/results_20261024_211915.json
```

- **Run A:** the section 5 AFTER run, `results_20261024_211725.json`.
- **Run B:** `results_20261024_211915.json` (traces `traces_20261024_211743.json`).
- **Rules:** both runs used the same rules, with the `link_presence.py` fix and without rule 4.

```
案例                       custom_response_quality  link_present  refusal_or_action  agent_turn_count
off_topic_weather          5 → 5                    1 → 1         1 → 1              1 → 1
off_topic_customer_crud    5 → 5                    1 → 1         1 → 1              1 → 1
clarify_then_complete      5 → 5                    1 → 1         1 → 1              2 → 2
not_found_quotation        5 → 5                    1 → 1         1 → 0 *            1 → 1
```

`agents-cli eval compare` was also run on the same two files. As the lab says, it prints a large JSON diff that is hard to read, so the table above is the record.

- **The agent was stable.** All four replies were byte-identical across the two runs (same md5 of the reply texts). The code metrics (`link_present`, `agent_turn_count`) did not change.
- **The difference is judge noise on a gap in the rules.** In run B, `refusal_or_action` on `not_found_quotation` said: "使用者請求查詢報價單屬於報價單管理，但助手回覆未附上純文字的系統連結。" It applied rule 2 literally to the same reply it had passed in run A.
- **Fix:** this is a correct answer wrongly failed, so rule 4 was added (section 5, fix 2). The **same run B traces** were then re-graded without rerunning the agent:

```bash
agents-cli eval grade --traces artifacts/traces/traces_20261024_211743.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/guardrails --qps 0.2
```

Results after rule 4: `artifacts/grade_results/guardrails/results_20261024_212057.json`

```
案例                       custom_response_quality  link_present  refusal_or_action  agent_turn_count
off_topic_weather          5 → 5                    1 → 1         1 → 1              1 → 1
off_topic_customer_crud    5 → 5                    1 → 1         1 → 1              1 → 1
clarify_then_complete      5 → 5                    1 → 1         1 → 1              2 → 2
not_found_quotation        5 → 5                    1 → 1         0 → 1 *            1 → 1
```

The `refusal_or_action` reason is now "使用者查詢不存在的報價單，助手明確告知找不到且沒有編造內容，符合規則四。" The judge cites the new rule instead of improvising.

**Write it down**
- **How stable is it?** The agent's output was identical across runs. The only `*` was on an LLM-judge metric, on the one case the rules did not cover.
- **Lesson:** judge noise shows up where the rules are ambiguous. Running twice exposed a gap that a single run had hidden.
- **Not yet measured:** stability *after* rule 4 has only one data point, the re-grade. A further pair of runs would confirm it.

## Section 7: break it on purpose

**Break:** `respond` in `quotation_agent/agent.py` was temporarily changed to turn every URL into `[查看](url)`. The line went after the existing Markdown-stripping step so it took effect.

```python
# EVAL-LAB BREAK TEST (section 7): deliberately emit Markdown links. Revert!
text = re.sub(r"(https?://\S+)", r"[查看](\1)", text)
```

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql   # repo root
agents-cli eval run \
  --dataset tests/eval/datasets/quotation-actions.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/actions-broken --qps 0.2
```

Broken results: `artifacts/grade_results/actions-broken/results_20261024_212332.json` (traces `traces_20261024_212119.json`)

| Case | custom_response_quality | link_present | refusal_or_action | agent_turn_count |
|---|---|---|---|---|
| get_quotation | 5 | 0 | 0 | 1 |
| list_customer_quotations | 5 | 0 | 0 | 1 |
| update_pricing_factor | 5 | 0 | 0 | 1 |
| adjust_total_price | 5 | 0 | 0 | 1 |
| convert_to_order | 5 | 0 | 0 | 1 |
| duplicate_quotation | 5 | 0 | 0 | 1 |
| **Average** | 5 | 0 | 0 | 1 |

Judge reasons for the failed scores:
- **`link_present`, all six cases:** "Markdown link found; plain-text links are required"
- **`refusal_or_action`, one reason per case:**
  - get_quotation: "助手在回覆中使用了 Markdown 的 [查看](網址) 語法，違反了純文字系統連結的規則。"
  - list_customer_quotations: "助手在回覆中使用了 Markdown 的 [查看](http://...) 語法，違反了規定中不可使用該語法的限制。"
  - update_pricing_factor: "助手違反了規則 2，在回覆中使用了 Markdown 的 [文字](網址) 語法來提供系統連結，而不是純文字網址。"
  - adjust_total_price: "助手在回覆中使用了 Markdown 語法 [查看](http://localhost:3000/quotations/14) 來呈現系統連結，違反了規則 2 中不可使用 Markdown 語法的規定。"
  - convert_to_order: "助手回覆中使用了 Markdown 的連結語法，違反了規則二的要求。"
  - duplicate_quotation: "助手在回覆中使用了 Markdown 的 [查看](網址) 語法，違反了規定二中不得使用 Markdown 連結語法的要求。"
- **`custom_response_quality`:** stayed **5 on all six**. Its reasons praise "the system link" being present. The generic quality judge did not notice the format at all, an even starker contrast than the lab's sample (5.0 → 4.67).

**Revert:**

```bash
git checkout agent/quotation_agent/agent.py
```

**Confirmed back to normal:**
- `git diff` on `agent.py` is empty and the break-test line is gone.
- `uv run pytest tests/unit -q` gives 18 passed.
- After a reseed, the actions rerun scored perfectly, and none of the six replies contains `[查看]`.

Fixed results: `artifacts/grade_results/actions/results_20261024_212605.json` (traces `traces_20261024_212357.json`)

```bash
python3 ../scripts/eval_summary.py \
  artifacts/grade_results/actions-broken/results_20261024_212332.json \
  artifacts/grade_results/actions/results_20261024_212605.json
```

```
案例                        custom_response_quality  link_present  refusal_or_action  agent_turn_count
get_quotation               5 → 5                    0 → 1 *       0 → 1 *            1 → 1
list_customer_quotations    5 → 5                    0 → 1 *       0 → 1 *            1 → 1
update_pricing_factor       5 → 5                    0 → 1 *       0 → 1 *            1 → 1
adjust_total_price          5 → 5                    0 → 1 *       0 → 1 *            1 → 1
convert_to_order            5 → 5                    0 → 1 *       0 → 1 *            1 → 1
duplicate_quotation         5 → 5                    0 → 1 *       0 → 1 *            1 → 1
```

**Write it down**
- **The evaluation catches the break:** both rule-specific metrics went to 0 on every case.
- **The generic quality score did not move (5.0 → 5.0).** A single "overall quality" score would have hidden the regression completely.
- **Once fixed, there is data showing it is fixed:** 0 → 1 on every case.

## Section 8: multi-turn, continuing after a question

The new case is in a **new file**, `tests/eval/datasets/quotation-multiturn-actions.json`. It changes data, so it does not belong in the read-only guardrails set, and putting it in the actions set would change that set's 6-case shape that the lab refers to.
- **Turn 0:** the user says "我要修改報價因子，報價單編號：QT-20260330-001". The injected assistant reply is the agent's real clarify text: "好的，我可以幫您修改報價單報價因子，請提供新的報價因子（例如 1.5）。"
- **Turn 1:** the user says "0.8".
- **Reference:** "完成修改，回覆新報價單連結並說明原始報價單未修改".

```bash
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql   # repo root, before
agents-cli eval run \
  --dataset tests/eval/datasets/quotation-multiturn-actions.json \
  --config tests/eval/eval_config.yaml \
  --output artifacts/grade_results/multiturn-actions --qps 0.2
docker compose exec db psql -U ezstore -f /scripts/seed-test-data.sql   # repo root, after
```

Results: `artifacts/grade_results/multiturn-actions/results_20261024_212710.json` (traces `traces_20261024_212639.json`)

| Case | custom_response_quality | link_present | refusal_or_action | agent_turn_count |
|---|---|---|---|---|
| clarify_then_update_pricing_factor | 5 | 1 | 1 | 2 |

The reply was:

```
已成功修改報價因子。
原始報價單: QT-20260330-001（未修改） — http://localhost:3000/quotations/12
新報價單: QT-20261024-001
報價因子: 0.95 → 0.8
總價: 6175 → 5200
系統連結: http://localhost:3000/quotations/13
提醒您：系統已先複製一份新的報價單並在副本上修改，原始報價單不會被更動。
```

The database confirmed the new copy QT-20261024-001 at factor 0.8 / total 5200, with the original still 0.95 / 6175. The database was reseeded afterwards (12 quotations).

**Write it down:** it works, scoring 5 / 1 / 1 / 2. The agent took "0.8" as the missing factor of the pending operation, which it recovered from the injected history, and finished the change instead of asking again.

## Files changed in this lab

- `tests/eval/datasets/quotation-guardrails.json`: added `not_found_quotation`.
- `tests/eval/datasets/quotation-multiturn-actions.json`: new, the 2-turn pricing-factor case.
- `tests/eval/link_presence.py`: not-found replies (containing 找不到) need no link.
- `tests/eval/eval_config.yaml`: `refusal_or_action` rule 4 (not found, no fabrication → 1).
- `README.md`: the dataset list.
- `quotation_agent/agent.py`: changed for the break test and reverted with `git checkout`; no net change.

## Observations for the report (raw material, not the report)

- **Results:** every metric averages its maximum on the final rules. The section 7 broken run is the only exception, and that was intended.
- **Rules fixed:** two grading rules (`link_present` code, `refusal_or_action` rule 4) had wrongly failed a correct not-found answer.
- **Stability:** the agent's replies were byte-identical between two runs. The one score flip was the LLM judge on an uncovered situation.
- **Break test:** the rule-specific metrics caught the Markdown break; the generic quality judge did not.
- **UX candidates:**
  - the "已達最大迭代次數…仍有差距" warning also appears when the target is hit (8000 → 8000.2);
  - the 100000 reply could state the maximum (32500) in plain words, and could ask before creating a copy that cannot meet the target.
- **Not covered yet:** similar customer names, Chinese numerals ("十萬"), a not-found *customer* in `list_customer_quotations` (rule 4 mentions it, no case tests it), and running on `gemini-3.8-flash` (all numbers here are from the dev model).
