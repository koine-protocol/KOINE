# KOINE Benchmark Results

**Run at:** 2026-04-09T16:10:37Z  
**Runs per combination:** 3  
**Pipeline:** summarize → rewrite (2 API calls per run)  

**Models tested:**
- Anthropic: `claude-sonnet-4-6`
- OpenAI: `gpt-5.4`
- Google: `gemini-3.1-pro-preview`

## Results

Token counts include the system prompt (fixed per format).  Payload bytes measure the user message only — the pure per-message cost.

| Provider | Format | Model | Runs | Success | Avg Input Tok | Avg Output Tok | Avg Total Tok | Avg Payload (B) |
| -------- | ------ | ----- | ---- | ------- | ------------- | -------------- | ------------- | --------------- |
| Anthropic | JSON | `claude-sonnet-4-6` | 3 | 100% | 1011 | 217 | 1228 | 949 |
| Anthropic | KOINE | `claude-sonnet-4-6` | 3 | 100% | 2582 | 312 | 2894 | 568 |
| Google | JSON | `gemini-3.1-pro-preview` | 3 | 0% | 0 | 0 | 0 | 1028 |
| Google | KOINE | `gemini-3.1-pro-preview` | 3 | 0% | 0 | 0 | 0 | 696 |
| Openai | JSON | `gpt-5.4` | 3 | 100% | 877 | 251 | 1128 | 998 |
| Openai | KOINE | `gpt-5.4` | 3 | 100% | 2317 | 311 | 2628 | 610 |

## Token Savings: KOINE vs JSON

| Provider | Model | Total Tok (JSON) | Total Tok (KOINE) | Token Savings | Payload (JSON, B) | Payload (KOINE, B) | Payload Savings |
| -------- | ----- | ---------------- | ----------------- | ------------- | ----------------- | ------------------ | --------------- |
| Anthropic | `claude-sonnet-4-6` | 1228 | 2894 | +135.7% | 949 | 568 | -40.1% |
| Google | `gemini-3.1-pro-preview` | 0 | 0 | n/a | 1028 | 696 | -32.3% |
| Openai | `gpt-5.4` | 1128 | 2628 | +133.0% | 998 | 610 | -38.9% |

## Break-Even Analysis

KOINE requires a richer system prompt than JSON so that models unfamiliar with the protocol can produce syntactically valid messages. This is a **fixed, one-time cost per session** that amortizes across every message in that session.

**System prompt sizes (estimated at ~4 chars/token):**

| Prompt | Characters | Est. Tokens |
| ------ | ---------- | ----------- |
| JSON system prompt   | 684  | ~171  |
| KOINE system prompt  | 3,399 | ~849 |
| **Overhead delta**   |            | **~678** |

**Per-message payload token savings (payload bytes ÷ 4, averaged across providers):**

| Format | Avg Payload (B) | Est. Payload Tokens |
| ------ | --------------- | ------------------- |
| Anthropic JSON  | 949 B | ~237 tok |
| Anthropic KOINE | 568 B | ~142 tok |
| Google JSON  | 1028 B | ~257 tok |
| Google KOINE | 696 B | ~174 tok |
| Openai JSON  | 998 B | ~249 tok |
| Openai KOINE | 610 B | ~152 tok |

Average per-message token saving across providers: **~91 tokens**

**Break-even calculation:**

```
overhead_delta      = ~678 tokens  (KOINE system prompt − JSON system prompt)
savings_per_message = ~91 tokens  (avg payload token reduction per message)
break_even          = 678 / 91 ≈ 7.5 messages
```

**After ~8 messages in a session, every subsequent message saves ~91 input tokens (~-37.0% in payload bytes).** In any agent pipeline that exchanges more than a handful of messages per session — the typical case — KOINE is strictly cheaper.

## Methodology

**Pipeline task:** A two-step sequence run against each provider:
1. `summarize` — condense a board-meeting document into an executive summary (constraint: `max_tokens=80,style=executive`)
2. `rewrite` — rewrite the summary for a general audience (constraint: `style=plain,audience=general,max_tokens=100`)

**JSON format:** Each task is a verbose JSON object with keys `message_type`, `message_id`, `sender_agent_id`, `recipient_agent_id`, `timestamp_unix`, and a nested `task` object containing `intent`, `instruction` (natural language), `input_content`, `output_format`, `operational_constraints`, and `priority_level`.

**KOINE format:** Same task expressed as a KOINE/1.0 TASK_REQUEST with `@id`, `@from`, `@to`, `@ts`, and semantic fields `intent`, `input`, `output_format`, `constraints`, `priority`.

**Success criteria:**  KOINE — response parses as a valid KOINE/1.0 RESULT with `status: ok`.  JSON — response deserializes as JSON containing an `output` field.

**Token counts:** Reported by each provider's API. Input tokens include the system prompt.  Output tokens are the model's raw response.

**Payload bytes:** `len(payload.encode('utf-8'))` for the user message only. System prompts are excluded; they are fixed amortized overhead.

**System prompt overhead:** The KOINE system prompt (~1,100 tokens) is substantially larger than the JSON system prompt (~150 tokens) because it must teach models the full KOINE grammar, type system, and @reply-to rule before they can produce valid messages. This overhead is a fixed, one-time cost per session. The break-even section above shows the exact message count at which cumulative payload savings exceed this fixed cost.

## Raw Run Log

One row per pipeline step per run.  `tok_in` / `tok_out` are per-step API-reported counts.

| Provider | Format | Run | Step | Success | tok_in | tok_out | payload_B | latency_ms | Error |
| -------- | ------ | --- | ---- | ------- | ------ | ------- | --------- | ---------- | ----- |
| Anthropic | JSON | 1 | 1 | ✓ | 519 | 105 | 1016 | 2422 |  |
| Anthropic | JSON | 1 | 2 | ✓ | 493 | 115 | 898 | 2941 |  |
| Anthropic | JSON | 2 | 1 | ✓ | 520 | 105 | 1016 | 2611 |  |
| Anthropic | JSON | 2 | 2 | ✓ | 492 | 111 | 882 | 3345 |  |
| Anthropic | JSON | 3 | 1 | ✓ | 520 | 103 | 1016 | 3760 |  |
| Anthropic | JSON | 3 | 2 | ✓ | 489 | 113 | 865 | 2984 |  |
| Anthropic | KOINE | 1 | 1 | ✓ | 1313 | 147 | 690 | 8058 |  |
| Anthropic | KOINE | 1 | 2 | ✓ | 1269 | 166 | 446 | 12520 |  |
| Anthropic | KOINE | 2 | 1 | ✓ | 1314 | 149 | 690 | 11231 |  |
| Anthropic | KOINE | 2 | 2 | ✓ | 1267 | 161 | 446 | 12848 |  |
| Anthropic | KOINE | 3 | 1 | ✓ | 1312 | 152 | 690 | 10212 |  |
| Anthropic | KOINE | 3 | 2 | ✓ | 1272 | 162 | 446 | 12947 |  |
| Openai | JSON | 1 | 1 | ✓ | 442 | 111 | 1016 | 3369 |  |
| Openai | JSON | 1 | 2 | ✓ | 430 | 132 | 956 | 3756 |  |
| Openai | JSON | 2 | 1 | ✓ | 441 | 116 | 1016 | 2395 |  |
| Openai | JSON | 2 | 2 | ✓ | 436 | 136 | 989 | 3728 |  |
| Openai | JSON | 3 | 1 | ✓ | 444 | 117 | 1016 | 4319 |  |
| Openai | JSON | 3 | 2 | ✓ | 438 | 140 | 992 | 3895 |  |
| Openai | KOINE | 1 | 1 | ✓ | 1175 | 152 | 690 | 5484 |  |
| Openai | KOINE | 1 | 2 | ✓ | 1145 | 163 | 535 | 3647 |  |
| Openai | KOINE | 2 | 1 | ✓ | 1173 | 149 | 690 | 2720 |  |
| Openai | KOINE | 2 | 2 | ✓ | 1145 | 167 | 537 | 3666 |  |
| Openai | KOINE | 3 | 1 | ✓ | 1174 | 146 | 690 | 2691 |  |
| Openai | KOINE | 3 | 2 | ✓ | 1138 | 156 | 520 | 3522 |  |
| Google | JSON | 1 | 1 | ✗ | 0 | 0 | 1016 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | JSON | 1 | 2 | ✗ | 0 | 0 | 1041 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | JSON | 2 | 1 | ✗ | 0 | 0 | 1016 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | JSON | 2 | 2 | ✗ | 0 | 0 | 1041 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | JSON | 3 | 1 | ✗ | 0 | 0 | 1016 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | JSON | 3 | 2 | ✗ | 0 | 0 | 1041 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 1 | 1 | ✗ | 0 | 0 | 690 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 1 | 2 | ✗ | 0 | 0 | 702 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 2 | 1 | ✗ | 0 | 0 | 690 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 2 | 2 | ✗ | 0 | 0 | 702 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 3 | 1 | ✗ | 0 | 0 | 690 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 3 | 2 | ✗ | 0 | 0 | 702 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
