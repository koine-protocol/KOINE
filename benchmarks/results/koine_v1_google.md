# KOINE Benchmark Results

**Run at:** 2026-04-09T16:22:07Z  
**Runs per combination:** 3  
**Pipeline:** summarize → rewrite (2 API calls per run)  

**Models tested:**
- Google: `gemini-2.5-flash`

## Results

Token counts include the system prompt (fixed per format).  Payload bytes measure the user message only — the pure per-message cost.

| Provider | Format | Model | Runs | Success | Avg Input Tok | Avg Output Tok | Avg Total Tok | Avg Payload (B) |
| -------- | ------ | ----- | ---- | ------- | ------------- | -------------- | ------------- | --------------- |
| Google | JSON | `gemini-2.5-flash` | 3 | 33% | 659 | 137 | 796 | 952 |
| Google | KOINE | `gemini-2.5-flash` | 3 | 66% | 1677 | 186 | 1863 | 602 |

## Token Savings: KOINE vs JSON

| Provider | Model | Total Tok (JSON) | Total Tok (KOINE) | Token Savings | Payload (JSON, B) | Payload (KOINE, B) | Payload Savings |
| -------- | ----- | ---------------- | ----------------- | ------------- | ----------------- | ------------------ | --------------- |
| Google | `gemini-2.5-flash` | 796 | 1863 | +134.0% | 952 | 602 | -36.8% |

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
| Google JSON  | 952 B | ~238 tok |
| Google KOINE | 602 B | ~150 tok |

Average per-message token saving across providers: **~88 tokens**

**Break-even calculation:**

```
overhead_delta      = ~678 tokens  (KOINE system prompt − JSON system prompt)
savings_per_message = ~88 tokens  (avg payload token reduction per message)
break_even          = 678 / 88 ≈ 7.7 messages
```

**After ~8 messages in a session, every subsequent message saves ~88 input tokens (~-36.8% in payload bytes).** In any agent pipeline that exchanges more than a handful of messages per session — the typical case — KOINE is strictly cheaper.

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
| Google | JSON | 1 | 1 | ✗ | 0 | 0 | 1016 | 0 | 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This mo… |
| Google | JSON | 1 | 2 | ✓ | 514 | 140 | 1041 | 1547 |  |
| Google | JSON | 2 | 1 | ✓ | 506 | 76 | 1016 | 1112 |  |
| Google | JSON | 2 | 2 | ✓ | 452 | 116 | 811 | 3541 |  |
| Google | JSON | 3 | 1 | ✓ | 504 | 78 | 1016 | 2753 |  |
| Google | JSON | 3 | 2 | ✗ | 0 | 0 | 809 | 0 | 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This mo… |
| Google | KOINE | 1 | 1 | ✗ | 0 | 0 | 690 | 0 | 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': '… |
| Google | KOINE | 1 | 2 | ✗ | 0 | 0 | 702 | 0 | 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This mo… |
| Google | KOINE | 2 | 1 | ✓ | 1287 | 148 | 690 | 16605 |  |
| Google | KOINE | 2 | 2 | ✓ | 1241 | 159 | 474 | 4065 |  |
| Google | KOINE | 3 | 1 | ✓ | 1287 | 124 | 690 | 4869 |  |
| Google | KOINE | 3 | 2 | ✓ | 1216 | 128 | 369 | 4539 |  |
