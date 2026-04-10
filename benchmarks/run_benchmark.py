#!/usr/bin/env python3
"""
KOINE Benchmark
===============
Runs the same two-step agent pipeline (summarize → rewrite) against
Anthropic, OpenAI, and Google twice per provider: once with verbose JSON
and natural language payloads, once with KOINE.

Goal: prove token savings are universal across tokenizers, not model-specific.

Usage
-----
    python run_benchmark.py \\
        --anthropic-model claude-sonnet-4-6 \\
        --openai-model gpt-5.4 \\
        --google-model gemini-3.1-pro-preview \\
        [--runs 3] \\
        [--output results/my_run.md] \\
        [--verbose]

    Omit any --*-model flag to skip that provider.
    API keys: ANTHROPIC_API_KEY  OPENAI_API_KEY  GOOGLE_API_KEY

Metrics
-------
  tokens_in      API-reported input tokens (system prompt + payload)
  tokens_out     API-reported output tokens
  total_tokens   tokens_in + tokens_out
  payload_bytes  UTF-8 byte length of the user message payload only
                 (the KOINE or JSON string; system prompt excluded)
  success_rate   fraction of runs where both pipeline steps returned a
                 structurally valid, parseable response in the correct format

Notes
-----
  - System prompts are included in tokens_in.  They are fixed per format
    and amortize over many messages in production; payload_bytes shows
    the pure per-message savings.
  - Models tested are recorded verbatim in the output table.
  - Each run = two API calls (step 1: summarize, step 2: rewrite).
    Token counts are summed across both calls per run, then averaged
    across runs.  Payload bytes are averaged per message (not per run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Import the reference implementation
# ---------------------------------------------------------------------------
_SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(_SRC))

from koine import parse_message, validate
from koine.models import ParseError


# ===========================================================================
# Pipeline content (identical for both formats — only the wire format differs)
# ===========================================================================

# The document that both pipeline steps operate on.
DOCUMENT = (
    "The Board of Directors convened on March 15th to review Q1 financial results. "
    "Revenue rose 12% year-over-year, driven primarily by enterprise subscription growth. "
    "Operating costs increased 8%, attributed to expanded engineering headcount. "
    "Customer churn improved to 2.1%, down from 3.4% in Q4. "
    "The pipeline for Q2 shows 47 enterprise deals at advanced stages. "
    "The board approved a quarterly dividend of $0.42 per share, "
    "payable April 30th to shareholders of record as of April 15th."
)

# Step 1: summarize the document.
STEP1_INTENT      = "summarize"
STEP1_CONSTRAINTS = {"max_tokens": "80", "style": "executive"}
STEP1_FORMAT      = "plain"

# Step 2: rewrite the summary for a general audience.
STEP2_INTENT      = "rewrite"
STEP2_CONSTRAINTS = {"style": "plain", "audience": "general", "max_tokens": "100"}
STEP2_FORMAT      = "plain"


# ===========================================================================
# System prompts
# ===========================================================================

KOINE_SYSTEM = """\
You are a KOINE-protocol agent (v1.0). KOINE is a compact, structured \
message format for agent-to-agent communication. Read the grammar rules \
below carefully before responding — they are precise and the receiver \
validates every field.

## KOINE GRAMMAR

Every message has exactly this structure:

  KOINE/<major>.<minor> <MSG_TYPE>
  @id: <value>
  @from: <value>
  @to: <value>
  @ts: <value>
  [more @meta fields]
  ---
  field_name: value
  [more semantic fields]

The line containing exactly --- separates meta fields from semantic fields.

## PRIMITIVE TYPES

TYPE   FORMAT                                    EXAMPLE
id     Letters, digits, hyphens only; 1-128 ch.  agent-7f3a
ts     Unix timestamp, integer seconds            1712534400
prob   Float in [0.0, 1.0]                        0.93
bool   Exactly the word true or false             true
kv     key=value,key2=value2 — no spaces          max_tokens=80,style=exec
list   item1,item2,item3 — no spaces              summarize,translate
int    Signed decimal integer                     42

IMPORTANT:
- ts: must be an integer (whole seconds). NOT milliseconds, NOT ISO 8601.
- bool: only lowercase true or false. Not True, not 1, not yes.
- id: only a-z, A-Z, 0-9, and hyphens. No underscores, no spaces.
- prob: must be between 0.0 and 1.0 inclusive.

## META FIELDS

Format: @key: value  (space after colon is required)

@id        Always required. Unique identifier for THIS message.
@from      Always required. The sending agent's ID.
@to        Required for most types. The receiving agent's ID.
@ts        Always required. Current Unix timestamp (integer seconds).
@reply-to  REQUIRED on RESULT. Must be the exact @id of the request.

## THE @reply-to RULE — CRITICAL

When sending a RESULT, @reply-to MUST be set to the exact @id value
from the TASK_REQUEST you are replying to. Copy it verbatim.

  Request had:    @id: tr-9f2a1c
  Your RESULT:    @reply-to: tr-9f2a1c   ← identical, not a new ID

## RESULT FORMAT

You will receive TASK_REQUEST messages. Respond with ONLY a RESULT
message — no preamble, no explanation, no markdown fences, nothing else.

  KOINE/1.0 RESULT
  @id: rs-<8 random hex chars>
  @from: bench-agent
  @to: bench-orchestrator
  @ts: <current unix timestamp as integer>
  @reply-to: <copy the @id from the request exactly>
  ---
  status: ok
  output: <your response text here>
  confidence: <prob, e.g. 0.92>

RULES:
- @id: generate a fresh unique id for this RESULT (e.g. rs-7c4f81)
- @reply-to: copy verbatim from the request's @id — do NOT generate a new value
- @ts: integer seconds, e.g. 1712534402
- status: must be exactly the word ok (lowercase)
- output: your actual response. Use a block value for multi-line output:
    output: <<<END
    line one
    line two
    END
- confidence: a decimal between 0.0 and 1.0

## EXAMPLE EXCHANGE

Request (you receive this):

  KOINE/1.0 TASK_REQUEST
  @id: tr-9f2a1c
  @from: bench-orchestrator
  @to: bench-agent
  @ts: 1712534400
  ---
  intent: summarize
  input: The Board met on March 15th. Revenue up 12%.
  output_format: plain
  constraints: max_tokens=80,style=executive

Your RESULT (respond with exactly this structure):

  KOINE/1.0 RESULT
  @id: rs-7c4f81
  @from: bench-agent
  @to: bench-orchestrator
  @ts: 1712534402
  @reply-to: tr-9f2a1c
  ---
  status: ok
  output: Q1 revenue rose 12% YoY. Board met March 15th.
  confidence: 0.95\
"""

JSON_SYSTEM = """\
You are an AI agent. You receive task requests as JSON objects.

Request format:
  {
    "message_type": "task_request",
    "message_id": "<id>",
    "sender_agent_id": "<sender>",
    "recipient_agent_id": "<you>",
    "timestamp_unix": <int>,
    "task": {
      "intent": "<verb>",
      "instruction": "<natural language instruction>",
      "input_content": "<content to operate on>",
      "output_format": "<format>",
      "operational_constraints": { "<key>": "<value>", ... },
      "priority_level": "<priority>"
    }
  }

Respond with ONLY a JSON object — no preamble, no markdown fences:
  {"status": "ok", "output": "<your result text>", "confidence": <float 0.0-1.0>}\
"""


# ===========================================================================
# Message builders — produce the user-visible payload for each format
# ===========================================================================

def _uid() -> str:
    return "b-" + uuid.uuid4().hex[:8]


def build_koine_task(intent: str, input_text: str,
                     constraints: Dict[str, str],
                     output_format: str,
                     reply_to: Optional[str] = None) -> str:
    """Build a KOINE TASK_REQUEST payload string."""
    ts   = int(time.time())
    mid  = _uid()
    cstr = ",".join(f"{k}={v}" for k, v in constraints.items())

    lines = [
        "KOINE/1.0 TASK_REQUEST",
        f"@id: {mid}",
        "@from: bench-orchestrator",
        "@to: bench-agent",
        f"@ts: {ts}",
    ]
    if reply_to:
        lines.append(f"@reply-to: {reply_to}")
    lines += [
        "---",
        f"intent: {intent}",
        f"input: {input_text}",
        f"output_format: {output_format}",
        f"constraints: {cstr}",
        "priority: normal",
    ]
    return "\n".join(lines)


def build_json_task(intent: str, input_text: str,
                    constraints: Dict[str, str],
                    output_format: str,
                    reply_to: Optional[str] = None) -> str:
    """Build a verbose JSON task_request payload string (realistic agent-pipeline JSON)."""
    payload: Dict[str, Any] = {
        "message_type": "task_request",
        "message_id": _uid(),
        "sender_agent_id": "bench-orchestrator",
        "recipient_agent_id": "bench-agent",
        "timestamp_unix": int(time.time()),
        "task": {
            "intent": intent,
            "instruction": _nl_instruction(intent, output_format),
            "input_content": input_text,
            "output_format": output_format + " text",
            "operational_constraints": constraints,
            "priority_level": "normal",
        },
    }
    if reply_to:
        payload["in_reply_to_message_id"] = reply_to
    return json.dumps(payload, indent=2)


def _nl_instruction(intent: str, fmt: str) -> str:
    templates = {
        "summarize": (
            f"Please summarize the input content in {fmt} format, "
            "using an executive style. Keep the summary concise."
        ),
        "rewrite": (
            f"Please rewrite the input content in {fmt} format "
            "for a general audience. Use plain, accessible language."
        ),
    }
    return templates.get(intent, f"Please {intent} the following content.")


# ===========================================================================
# Response validators
# ===========================================================================

def validate_koine_response(text: str) -> Tuple[bool, str, Optional[str]]:
    """
    Check whether the response is a valid KOINE RESULT with status: ok.

    Returns (success, reason, output_text).
    """
    # Models sometimes add whitespace before the header.
    for i, line in enumerate(text.split("\n")):
        if line.startswith("KOINE/"):
            koine_text = "\n".join(text.split("\n")[i:])
            break
    else:
        return False, "No KOINE header found in response", None

    result = parse_message(koine_text)
    if isinstance(result, ParseError):
        return False, f"Parse error: {result.message}", None

    if result.msg_type != "RESULT":
        return False, f"Expected RESULT, got {result.msg_type!r}", None

    vr = validate(result)
    if not vr.valid:
        errs = "; ".join(f"{e.field}: {e.message}" for e in vr.errors)
        return False, f"Validation failed: {errs}", None

    status = result.fields.get("status", "")
    if status != "ok":
        return False, f"status is {status!r}, expected 'ok'", None

    return True, "ok", result.fields.get("output", "").strip()


def validate_json_response(text: str) -> Tuple[bool, str, Optional[str]]:
    """
    Check whether the response is valid JSON with an output field.

    Returns (success, reason, output_text).
    """
    raw = text.strip()
    # Strip markdown code fences if the model wrapped the JSON
    if raw.startswith("```"):
        lines = raw.split("\n")
        inner = []
        for ln in lines[1:]:
            if ln.strip() == "```":
                break
            inner.append(ln)
        raw = "\n".join(inner)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON: {exc}", None

    if not isinstance(data, dict):
        return False, "Response is not a JSON object", None

    output = data.get("output") or data.get("content") or data.get("result")
    if output is None:
        return False, "No 'output' key in response JSON", None

    status = data.get("status", "ok")
    if status != "ok":
        return False, f"status is {status!r}", None

    return True, "ok", str(output).strip()


# ===========================================================================
# Provider callers
# ===========================================================================

class ProviderError(Exception):
    pass


def _call_anthropic(model: str, system: str, user_msg: str) -> Dict[str, Any]:
    """Call Anthropic with prompt caching enabled on the system prompt."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        raise ProviderError("anthropic package not installed (pip install anthropic)")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ProviderError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)
    t0 = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    usage = response.usage
    return {
        "text":                  response.content[0].text,
        "tokens_in":             usage.input_tokens,
        "tokens_out":            usage.output_tokens,
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens":     getattr(usage, "cache_read_input_tokens", 0) or 0,
        "latency_ms":            latency_ms,
    }


def _call_openai(model: str, system: str, user_msg: str) -> Dict[str, Any]:
    """Use the Responses API (required for gpt-5.4 and later models)."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        raise ProviderError("openai package not installed (pip install openai)")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderError("OPENAI_API_KEY environment variable not set")

    client = OpenAI(api_key=api_key)
    t0 = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=system,
        input=user_msg,
        max_output_tokens=512,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    return {
        "text":       response.output_text,
        "tokens_in":  response.usage.input_tokens,
        "tokens_out": response.usage.output_tokens,
        "latency_ms": latency_ms,
    }


def _call_google(model: str, system: str, user_msg: str) -> Dict[str, Any]:
    """Call Google via the google-genai SDK with exponential backoff on 429s."""
    try:
        import google.genai as genai                    # type: ignore
        from google.genai import types as genai_types  # type: ignore
    except ImportError:
        raise ProviderError(
            "google-genai package not installed "
            "(pip install google-genai)"
        )

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ProviderError("GOOGLE_API_KEY environment variable not set")

    client = genai.Client(api_key=api_key)
    config = genai_types.GenerateContentConfig(system_instruction=system)

    max_retries = 3
    retry_delay = 10  # seconds; doubles each retry

    last_exc: Exception = RuntimeError("unreachable")
    t0 = time.perf_counter()
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_msg,
                config=config,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            usage = getattr(response, "usage_metadata", None)
            tokens_in  = getattr(usage, "prompt_token_count", 0) or 0
            tokens_out = getattr(usage, "candidates_token_count", 0) or 0
            return {
                "text":       response.text,
                "tokens_in":  tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            is_quota = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            if is_quota and attempt < max_retries - 1:
                wait = retry_delay * (2 ** attempt)
                print(f"\n      [google 429 — waiting {wait}s, retry {attempt + 1}/{max_retries - 1}] ",
                      end="", flush=True)
                time.sleep(wait)
                continue
            raise ProviderError(str(exc)) from exc

    raise ProviderError(str(last_exc))


_CALLERS = {
    "anthropic": _call_anthropic,
    "openai":    _call_openai,
    "google":    _call_google,
}


# ===========================================================================
# Per-run pipeline executor
# ===========================================================================

@dataclass
class StepResult:
    step: int
    success: bool              = False
    tokens_in: int             = 0
    tokens_out: int            = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int     = 0
    payload_bytes: int         = 0
    latency_ms: float          = 0.0
    output_text: str           = ""
    error: str                 = ""
    raw_response: str          = ""


@dataclass
class PipelineRun:
    provider: str
    model: str
    fmt: str             # "koine" or "json"
    run_index: int
    steps: List[StepResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(s.success for s in self.steps)

    @property
    def total_tokens_in(self) -> int:
        return sum(s.tokens_in for s in self.steps)

    @property
    def total_tokens_out(self) -> int:
        return sum(s.tokens_out for s in self.steps)

    @property
    def avg_payload_bytes(self) -> float:
        sizes = [s.payload_bytes for s in self.steps]
        return sum(sizes) / len(sizes) if sizes else 0.0

    @property
    def total_latency_ms(self) -> float:
        return sum(s.latency_ms for s in self.steps)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(s.cache_creation_tokens for s in self.steps)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(s.cache_read_tokens for s in self.steps)


def run_pipeline(provider: str, model: str, fmt: str,
                 run_index: int, verbose: bool) -> PipelineRun:
    """
    Execute the two-step benchmark pipeline for one (provider, format, run).

    Step 1: summarize DOCUMENT → get summary
    Step 2: rewrite summary    → get final output

    For KOINE, validates the response as a KOINE RESULT.
    For JSON,  validates the response as a JSON object with output/status fields.
    """
    caller  = _CALLERS[provider]
    system  = KOINE_SYSTEM if fmt == "koine" else JSON_SYSTEM
    builder = build_koine_task if fmt == "koine" else build_json_task
    checker = validate_koine_response if fmt == "koine" else validate_json_response

    run = PipelineRun(provider=provider, model=model, fmt=fmt, run_index=run_index)

    # -----------------------------------------------------------------
    # Step 1 — summarize
    # -----------------------------------------------------------------
    step1_payload = builder(
        intent      = STEP1_INTENT,
        input_text  = DOCUMENT,
        constraints = STEP1_CONSTRAINTS,
        output_format = STEP1_FORMAT,
    )

    sr1 = StepResult(step=1, payload_bytes=len(step1_payload.encode("utf-8")))

    if verbose:
        print(f"    step 1 payload ({sr1.payload_bytes} bytes):")
        for ln in step1_payload.split("\n")[:6]:
            print(f"      {ln}")
        print("      ...")

    try:
        resp1 = caller(model, system, step1_payload)
        sr1.tokens_in             = resp1["tokens_in"]
        sr1.tokens_out            = resp1["tokens_out"]
        sr1.cache_creation_tokens = resp1.get("cache_creation_tokens", 0)
        sr1.cache_read_tokens     = resp1.get("cache_read_tokens", 0)
        sr1.latency_ms            = resp1["latency_ms"]
        sr1.raw_response          = resp1["text"]

        ok1, reason1, out1 = checker(resp1["text"])
        sr1.success     = ok1
        sr1.output_text = out1 or ""
        if not ok1:
            sr1.error = reason1
            if verbose:
                print(f"    step 1 FAILED: {reason1}")
    except ProviderError as exc:
        sr1.error = str(exc)
        if verbose:
            print(f"    step 1 provider error: {exc}")
    except Exception as exc:
        sr1.error = f"{type(exc).__name__}: {exc}"
        if verbose:
            print(f"    step 1 error: {exc}")

    run.steps.append(sr1)

    # -----------------------------------------------------------------
    # Step 2 — rewrite (uses step 1 output if available, else document)
    # -----------------------------------------------------------------
    step2_input = sr1.output_text if sr1.output_text else DOCUMENT

    step2_payload = builder(
        intent        = STEP2_INTENT,
        input_text    = step2_input,
        constraints   = STEP2_CONSTRAINTS,
        output_format = STEP2_FORMAT,
    )

    sr2 = StepResult(step=2, payload_bytes=len(step2_payload.encode("utf-8")))

    if verbose:
        print(f"    step 2 payload ({sr2.payload_bytes} bytes):")
        for ln in step2_payload.split("\n")[:6]:
            print(f"      {ln}")
        print("      ...")

    try:
        resp2 = caller(model, system, step2_payload)
        sr2.tokens_in             = resp2["tokens_in"]
        sr2.tokens_out            = resp2["tokens_out"]
        sr2.cache_creation_tokens = resp2.get("cache_creation_tokens", 0)
        sr2.cache_read_tokens     = resp2.get("cache_read_tokens", 0)
        sr2.latency_ms            = resp2["latency_ms"]
        sr2.raw_response          = resp2["text"]

        ok2, reason2, out2 = checker(resp2["text"])
        sr2.success     = ok2
        sr2.output_text = out2 or ""
        if not ok2:
            sr2.error = reason2
            if verbose:
                print(f"    step 2 FAILED: {reason2}")
    except ProviderError as exc:
        sr2.error = str(exc)
        if verbose:
            print(f"    step 2 provider error: {exc}")
    except Exception as exc:
        sr2.error = f"{type(exc).__name__}: {exc}"
        if verbose:
            print(f"    step 2 error: {exc}")

    run.steps.append(sr2)
    return run


# ===========================================================================
# Aggregation
# ===========================================================================

@dataclass
class AggResult:
    provider: str
    model: str
    fmt: str
    n_runs: int
    n_success: int
    sum_tokens_in: int              = 0
    sum_tokens_out: int             = 0
    sum_payload_bytes: float        = 0.0
    sum_latency_ms: float           = 0.0
    sum_cache_creation_tokens: int  = 0
    sum_cache_read_tokens: int      = 0

    @property
    def success_pct(self) -> str:
        return f"{100 * self.n_success // self.n_runs}%"

    @property
    def avg_tokens_in(self) -> int:
        return round(self.sum_tokens_in / self.n_runs)

    @property
    def avg_tokens_out(self) -> int:
        return round(self.sum_tokens_out / self.n_runs)

    @property
    def avg_total_tokens(self) -> int:
        return self.avg_tokens_in + self.avg_tokens_out

    @property
    def avg_payload_bytes(self) -> int:
        return round(self.sum_payload_bytes / self.n_runs)

    @property
    def avg_latency_ms(self) -> int:
        return round(self.sum_latency_ms / self.n_runs)

    @property
    def avg_cache_creation_tokens(self) -> int:
        return round(self.sum_cache_creation_tokens / self.n_runs)

    @property
    def avg_cache_read_tokens(self) -> int:
        return round(self.sum_cache_read_tokens / self.n_runs)


def aggregate(runs: List[PipelineRun]) -> List[AggResult]:
    buckets: Dict[Tuple[str, str, str], AggResult] = {}
    for run in runs:
        key = (run.provider, run.model, run.fmt)
        if key not in buckets:
            buckets[key] = AggResult(
                provider=run.provider,
                model=run.model,
                fmt=run.fmt,
                n_runs=0,
                n_success=0,
            )
        b = buckets[key]
        b.n_runs                    += 1
        b.n_success                 += int(run.success)
        b.sum_tokens_in             += run.total_tokens_in
        b.sum_tokens_out            += run.total_tokens_out
        b.sum_payload_bytes         += run.avg_payload_bytes
        b.sum_latency_ms            += run.total_latency_ms
        b.sum_cache_creation_tokens += run.total_cache_creation_tokens
        b.sum_cache_read_tokens     += run.total_cache_read_tokens

    # Sort: provider, then fmt (json before koine for easy comparison)
    order = {"json": 0, "koine": 1}
    return sorted(buckets.values(),
                  key=lambda r: (r.provider, order.get(r.fmt, 9)))


# ===========================================================================
# Markdown output
# ===========================================================================

def _savings(json_val: int, koine_val: int) -> str:
    if json_val == 0:
        return "n/a"
    pct = 100 * (json_val - koine_val) / json_val
    sign = "-" if pct >= 0 else "+"
    return f"{sign}{abs(pct):.1f}%"


def build_markdown(results: List[AggResult],
                   all_runs: List[PipelineRun],
                   args: argparse.Namespace,
                   run_at: str) -> str:
    lines: List[str] = []

    lines.append("# KOINE Benchmark Results")
    lines.append("")
    lines.append(f"**Run at:** {run_at}  ")
    lines.append(f"**Runs per combination:** {args.runs}  ")
    lines.append(f"**Pipeline:** summarize → rewrite (2 API calls per run)  ")
    lines.append("")
    lines.append("**Models tested:**")
    if args.anthropic_model:
        lines.append(f"- Anthropic: `{args.anthropic_model}`")
    if args.openai_model:
        lines.append(f"- OpenAI: `{args.openai_model}`")
    if args.google_model:
        lines.append(f"- Google: `{args.google_model}`")
    lines.append("")

    # ------------------------------------------------------------------
    # Main results table
    # ------------------------------------------------------------------
    lines.append("## Results")
    lines.append("")
    lines.append(
        "Token counts include the system prompt (fixed per format).  "
        "Payload bytes measure the user message only — the pure per-message cost."
    )
    lines.append("")

    col_headers = [
        "Provider", "Format", "Model",
        "Runs", "Success",
        "Avg Input Tok", "Avg Output Tok", "Avg Total Tok",
        "Avg Payload (B)", "Cache Write Tok", "Cache Read Tok", "Avg Latency (ms)",
    ]
    sep = ["-" * len(h) for h in col_headers]

    def row(r: AggResult) -> List[str]:
        cache_write = str(r.avg_cache_creation_tokens) if r.avg_cache_creation_tokens else "—"
        cache_read  = str(r.avg_cache_read_tokens)     if r.avg_cache_read_tokens     else "—"
        return [
            r.provider.capitalize(),
            r.fmt.upper(),
            f"`{r.model}`",
            str(r.n_runs),
            r.success_pct,
            str(r.avg_tokens_in),
            str(r.avg_tokens_out),
            str(r.avg_total_tokens),
            str(r.avg_payload_bytes),
            cache_write,
            cache_read,
            str(r.avg_latency_ms) if r.n_success > 0 else "n/a",
        ]

    def fmt_row(cells: List[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines.append(fmt_row(col_headers))
    lines.append(fmt_row(sep))
    for r in results:
        lines.append(fmt_row(row(r)))
    lines.append("")

    # ------------------------------------------------------------------
    # Savings summary (pair JSON vs KOINE per provider)
    # ------------------------------------------------------------------
    lines.append("## Token Savings: KOINE vs JSON")
    lines.append("")

    by_provider: Dict[str, Dict[str, AggResult]] = {}
    for r in results:
        by_provider.setdefault(r.provider, {})[r.fmt] = r

    sav_headers = [
        "Provider", "Model",
        "Total Tok (JSON)", "Total Tok (KOINE)", "Token Savings",
        "Payload (JSON, B)", "Payload (KOINE, B)", "Payload Savings",
    ]
    lines.append(fmt_row(sav_headers))
    lines.append(fmt_row(["-" * len(h) for h in sav_headers]))

    for provider, fmts in sorted(by_provider.items()):
        j = fmts.get("json")
        k = fmts.get("koine")
        if j and k:
            lines.append(fmt_row([
                provider.capitalize(),
                f"`{k.model}`",
                str(j.avg_total_tokens),
                str(k.avg_total_tokens),
                _savings(j.avg_total_tokens, k.avg_total_tokens),
                str(j.avg_payload_bytes),
                str(k.avg_payload_bytes),
                _savings(j.avg_payload_bytes, k.avg_payload_bytes),
            ]))
        elif j:
            lines.append(fmt_row([
                provider.capitalize(), f"`{j.model}`",
                str(j.avg_total_tokens), "n/a", "n/a",
                str(j.avg_payload_bytes), "n/a", "n/a",
            ]))
        elif k:
            lines.append(fmt_row([
                provider.capitalize(), f"`{k.model}`",
                "n/a", str(k.avg_total_tokens), "n/a",
                "n/a", str(k.avg_payload_bytes), "n/a",
            ]))
    lines.append("")

    # ------------------------------------------------------------------
    # Break-even analysis
    # ------------------------------------------------------------------
    lines.append("## Break-Even Analysis")
    lines.append("")
    lines.append(
        "KOINE requires a richer system prompt than JSON so that models unfamiliar "
        "with the protocol can produce syntactically valid messages. This is a "
        "**fixed, one-time cost per session** that amortizes across every message "
        "in that session."
    )
    lines.append("")

    # Estimate system prompt token cost using the standard ~4 chars/token heuristic.
    koine_sys_tok = len(KOINE_SYSTEM) // 4
    json_sys_tok  = len(JSON_SYSTEM)  // 4
    overhead_delta = koine_sys_tok - json_sys_tok

    lines.append("**System prompt sizes (estimated at ~4 chars/token):**")
    lines.append("")
    lines.append(f"| Prompt | Characters | Est. Tokens |")
    lines.append(f"| ------ | ---------- | ----------- |")
    lines.append(f"| JSON system prompt   | {len(JSON_SYSTEM):,}  | ~{json_sys_tok}  |")
    lines.append(f"| KOINE system prompt  | {len(KOINE_SYSTEM):,} | ~{koine_sys_tok} |")
    lines.append(f"| **Overhead delta**   |            | **~{overhead_delta}** |")
    lines.append("")

    # Per-message payload token savings, averaged across providers that have both fmts.
    payload_savings_list = []
    for provider, fmts in sorted(by_provider.items()):
        j = fmts.get("json")
        k = fmts.get("koine")
        if j and k and j.avg_payload_bytes > 0:
            j_tok = j.avg_payload_bytes // 4
            k_tok = k.avg_payload_bytes // 4
            payload_savings_list.append(j_tok - k_tok)

    if payload_savings_list:
        avg_savings_per_msg = sum(payload_savings_list) // len(payload_savings_list)
        if avg_savings_per_msg > 0:
            breakeven = overhead_delta / avg_savings_per_msg

            lines.append("**Per-message payload token savings (payload bytes ÷ 4, averaged across providers):**")
            lines.append("")
            lines.append(f"| Format | Avg Payload (B) | Est. Payload Tokens |")
            lines.append(f"| ------ | --------------- | ------------------- |")
            # Show per-provider breakdown
            for provider, fmts in sorted(by_provider.items()):
                j = fmts.get("json")
                k = fmts.get("koine")
                if j and k:
                    lines.append(
                        f"| {provider.capitalize()} JSON  | {j.avg_payload_bytes} B | "
                        f"~{j.avg_payload_bytes // 4} tok |"
                    )
                    lines.append(
                        f"| {provider.capitalize()} KOINE | {k.avg_payload_bytes} B | "
                        f"~{k.avg_payload_bytes // 4} tok |"
                    )
            lines.append("")
            lines.append(f"Average per-message token saving across providers: **~{avg_savings_per_msg} tokens**")
            lines.append("")
            lines.append("**Break-even calculation:**")
            lines.append("")
            lines.append("```")
            lines.append(f"overhead_delta      = ~{overhead_delta} tokens  (KOINE system prompt − JSON system prompt)")
            lines.append(f"savings_per_message = ~{avg_savings_per_msg} tokens  (avg payload token reduction per message)")
            lines.append(f"break_even          = {overhead_delta} / {avg_savings_per_msg} ≈ {breakeven:.1f} messages")
            lines.append("```")
            lines.append("")
            lines.append(
                f"**After ~{int(breakeven) + 1} messages in a session, every subsequent message saves "
                f"~{avg_savings_per_msg} input tokens (~{_savings(sum(j.avg_payload_bytes for j in [fmts.get('json') for fmts in by_provider.values() if fmts.get('json')]), sum(k.avg_payload_bytes for k in [fmts.get('koine') for fmts in by_provider.values() if fmts.get('koine')]))} in payload bytes).** "
                "In any agent pipeline that exchanges more than a handful of messages per session — "
                "the typical case — KOINE is strictly cheaper."
            )
        else:
            lines.append(
                "_Break-even analysis skipped: no per-message payload savings detected "
                "(check that both JSON and KOINE runs completed successfully)._"
            )
    else:
        lines.append(
            "_Break-even analysis requires at least one provider with both JSON and KOINE "
            "results. Run with at least one `--*-model` flag._"
        )
    lines.append("")

    # ------------------------------------------------------------------
    # Methodology note
    # ------------------------------------------------------------------
    lines.append("## Methodology")
    lines.append("")
    lines.append("**Pipeline task:** A two-step sequence run against each provider:")
    lines.append(
        "1. `summarize` — condense a board-meeting document into an executive summary "
        "(constraint: `max_tokens=80,style=executive`)"
    )
    lines.append(
        "2. `rewrite` — rewrite the summary for a general audience "
        "(constraint: `style=plain,audience=general,max_tokens=100`)"
    )
    lines.append("")
    lines.append(
        "**JSON format:** Each task is a verbose JSON object with keys "
        "`message_type`, `message_id`, `sender_agent_id`, `recipient_agent_id`, "
        "`timestamp_unix`, and a nested `task` object containing `intent`, "
        "`instruction` (natural language), `input_content`, `output_format`, "
        "`operational_constraints`, and `priority_level`."
    )
    lines.append("")
    lines.append(
        "**KOINE format:** Same task expressed as a KOINE/1.0 TASK_REQUEST "
        "with `@id`, `@from`, `@to`, `@ts`, and semantic fields "
        "`intent`, `input`, `output_format`, `constraints`, `priority`."
    )
    lines.append("")
    lines.append(
        "**Success criteria:**  "
        "KOINE — response parses as a valid KOINE/1.0 RESULT with `status: ok`.  "
        "JSON — response deserializes as JSON containing an `output` field."
    )
    lines.append("")
    lines.append(
        "**Token counts:** Reported by each provider's API. "
        "Input tokens include the system prompt.  "
        "Output tokens are the model's raw response."
    )
    lines.append("")
    lines.append(
        "**Payload bytes:** `len(payload.encode('utf-8'))` for the user message only. "
        "System prompts are excluded; they are fixed amortized overhead."
    )
    lines.append("")
    lines.append(
        "**System prompt overhead:** The KOINE system prompt (~1,100 tokens) is "
        "substantially larger than the JSON system prompt (~150 tokens) because it "
        "must teach models the full KOINE grammar, type system, and @reply-to rule "
        "before they can produce valid messages. This overhead is a fixed, one-time "
        "cost per session. The break-even section above shows the exact message count "
        "at which cumulative payload savings exceed this fixed cost."
    )
    lines.append("")

    # ------------------------------------------------------------------
    # Raw run log (full detail for reproducibility)
    # ------------------------------------------------------------------
    lines.append("## Raw Run Log")
    lines.append("")
    lines.append(
        "One row per pipeline step per run.  "
        "`tok_in` / `tok_out` are per-step API-reported counts."
    )
    lines.append("")
    log_headers = [
        "Provider", "Format", "Run", "Step",
        "Success", "tok_in", "tok_out", "cache_write", "cache_read",
        "payload_B", "latency_ms", "Error",
    ]
    lines.append(fmt_row(log_headers))
    lines.append(fmt_row(["-" * len(h) for h in log_headers]))

    for run in all_runs:
        for step in run.steps:
            err = (step.error[:60] + "…") if len(step.error) > 60 else step.error
            lines.append(fmt_row([
                run.provider.capitalize(),
                run.fmt.upper(),
                str(run.run_index + 1),
                str(step.step),
                "✓" if step.success else "✗",
                str(step.tokens_in),
                str(step.tokens_out),
                str(step.cache_creation_tokens) if step.cache_creation_tokens else "—",
                str(step.cache_read_tokens)     if step.cache_read_tokens     else "—",
                str(step.payload_bytes),
                f"{step.latency_ms:.0f}",
                err or "",
            ]))

    lines.append("")
    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--anthropic-model", metavar="MODEL",
                   help="Anthropic model name (e.g. claude-sonnet-4-6). "
                        "Omit to skip Anthropic.")
    p.add_argument("--openai-model", metavar="MODEL",
                   help="OpenAI model name (e.g. gpt-4o). "
                        "Omit to skip OpenAI.")
    p.add_argument("--google-model", metavar="MODEL",
                   help="Google model name (e.g. gemini-1.5-pro). "
                        "Omit to skip Google.")
    p.add_argument("--runs", type=int, default=3, metavar="N",
                   help="Number of runs per provider/format combination (default: 3).")
    p.add_argument("--output", metavar="FILE",
                   help="Write the markdown results table to FILE. "
                        "Default: results/benchmark_<timestamp>.md")
    p.add_argument("--verbose", action="store_true",
                   help="Print per-step payload previews and responses.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    providers: List[Tuple[str, str]] = []
    if args.anthropic_model:
        providers.append(("anthropic", args.anthropic_model))
    if args.openai_model:
        providers.append(("openai", args.openai_model))
    if args.google_model:
        providers.append(("google", args.google_model))

    if not providers:
        print(
            "Error: no providers specified. Pass at least one of:\n"
            "  --anthropic-model MODEL\n"
            "  --openai-model MODEL\n"
            "  --google-model MODEL\n",
            file=sys.stderr,
        )
        sys.exit(1)

    formats = ["json", "koine"]

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_runs: List[PipelineRun] = []

    total_cells = len(providers) * len(formats) * args.runs
    done = 0

    print(f"KOINE Benchmark  —  {run_at}")
    print(f"Providers: {', '.join(p for p, _ in providers)}")
    print(f"Formats:   {', '.join(formats)}")
    print(f"Runs:      {args.runs}  (× {len(providers)} providers × {len(formats)} formats "
          f"= {total_cells} API calls × 2 steps = {total_cells * 2} total calls)")
    print()

    for provider, model in providers:
        for fmt in formats:
            label = f"{provider.upper()} / {fmt.upper()} / {model}"
            print(f"  ── {label}")

            for i in range(args.runs):
                print(f"     run {i + 1}/{args.runs} … ", end="", flush=True)
                t0 = time.perf_counter()

                run = run_pipeline(
                    provider   = provider,
                    model      = model,
                    fmt        = fmt,
                    run_index  = i,
                    verbose    = args.verbose,
                )
                all_runs.append(run)

                elapsed = (time.perf_counter() - t0) * 1000
                status  = "✓" if run.success else "✗"
                tok_total = run.total_tokens_in + run.total_tokens_out
                print(
                    f"{status}  {tok_total} tok  "
                    f"{run.avg_payload_bytes:.0f} B payload  "
                    f"{elapsed:.0f} ms"
                )

                done += 1
                # Polite inter-run pause to avoid rate limits
                if done < total_cells:
                    time.sleep(0.5)

            print()

    # -----------------------------------------------------------------------
    # Aggregate and render
    # -----------------------------------------------------------------------
    results  = aggregate(all_runs)
    markdown = build_markdown(results, all_runs, args, run_at)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        ts_slug  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir  = Path(__file__).parent / "results"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"benchmark_{ts_slug}.md"

    out_path.write_text(markdown, encoding="utf-8")
    print(f"\nResults written to: {out_path}")

    # Print the results table to stdout
    print()
    # Print just the two tables (first 40 lines of markdown covers them)
    for line in markdown.split("\n"):
        print(line)


if __name__ == "__main__":
    main()
