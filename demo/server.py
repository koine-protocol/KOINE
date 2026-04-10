#!/usr/bin/env python3
"""
KOINE demo server — Meridian & Sable multi-agent conversation.

Serves index.html at GET /
Streams the conversation as SSE at GET /api/stream

Each SSE event is JSON:
  { "type": "message", "koine": "<raw text>", "english": "<plain text>",
    "msg_type": "TASK_REQUEST", "from_agent": "meridian", "to_agent": "sable",
    "koine_bytes": N, "json_bytes": N }

or  { "type": "done" }
or  { "type": "error", "message": "..." }
"""
from __future__ import annotations

import http.server
import json
import os
import sys
import time
import textwrap
from pathlib import Path
from typing import Generator

import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PORT = 8787
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
HTML_FILE = Path(__file__).parent / "index.html"

# ---------------------------------------------------------------------------
# KOINE system prompt — full grammar primer so the model produces valid msgs
# ---------------------------------------------------------------------------

KOINE_SYSTEM = """\
You are communicating using the KOINE/1.0 agent protocol. Every response you send MUST be a single valid KOINE message — no prose before or after.

## KOINE Message Structure

```
KOINE/1.0 <MSG_TYPE>
@id: <id>
@from: <id>
@to: <id>
@ts: <unix_int>
[@reply-to: <id>]
---
<semantic fields>
```

## Message Types and Required Semantic Fields

| Type              | Required fields                          | Optional fields              |
|-------------------|------------------------------------------|------------------------------|
| TASK_REQUEST      | intent, input                            | output_format, constraints, priority |
| CAPABILITY_DECL   | name, capabilities                       | version, languages           |
| RESULT            | status (ok/partial/error), output        | confidence, notes            |
| HANDOFF           | reason, context                          | suggested_next               |
| UNCERTAINTY       | missing_input                            | confidence, clarification    |

## Type System

| Type  | Example                        | Notes                                |
|-------|--------------------------------|--------------------------------------|
| id    | meridian-1                     | alphanumeric + hyphens, 1-128 chars  |
| ts    | 1712534400                     | Unix seconds, integer ONLY           |
| bool  | true / false                   | lowercase, no quotes                 |
| kv    | max_tokens=200,style=concise   | comma-separated key=value, no spaces |
| list  | analyze,review,report          | comma-separated, no spaces           |
| block | <<<END ... END                 | multi-line value with delimiter      |

## Block Values (multi-line content)

```
input: <<<END
line one
line two
END
```

Delimiter must be UPPERCASE letters/underscores. Closing delimiter on its own line, no whitespace.

## IMPORTANT RULES

1. @ts MUST be an integer (Unix seconds). Never ISO format.
2. @id format: short-prefix-hexchars e.g. `tr-a1b2c3` or `res-f9e2d1`
3. @reply-to MUST equal the @id of the message you are responding to.
4. bool fields: write `true` or `false`, never "true" or quoted.
5. The `---` separator line is required between meta and semantic fields.
6. Do NOT add any text outside the KOINE message block.
7. status field in RESULT: must be exactly `ok`, `partial`, or `error`.

## Example — a RESULT responding to message @id: tr-a1b2c3

```
KOINE/1.0 RESULT
@id: res-f9e2d1
@from: sable
@to: meridian
@ts: 1712534400
@reply-to: tr-a1b2c3
---
status: ok
output: <<<END
Analysis complete. Three critical vulnerabilities found.
See notes for remediation steps.
END
confidence: 0.94
notes: Prioritize JWT rotation and rate-limit bypass first.
```
"""

# ---------------------------------------------------------------------------
# Agent role prompts
# ---------------------------------------------------------------------------

MERIDIAN_ROLE = """\
You are Meridian, an orchestration agent specializing in breaking down complex engineering tasks and routing subtasks to specialist agents. Your counterpart in this session is Sable (id: sable), a security and distributed-systems specialist.

The task for this session: coordinate a security and reliability review of a HIPAA-compliant patient data REST API that is about to go to production. You have received this task from an external client.

Your job:
1. First, declare your capabilities to establish session context.
2. Wait for Sable's capability declaration.
3. Route the security analysis subtask to Sable, but initially without the full API spec — so Sable will need to ask for it.
4. When Sable sends an UNCERTAINTY asking for the spec, respond with a TASK_REQUEST that includes the full API spec as a block value.
5. When Sable sends a partial RESULT (security done, reliability pending), send a HANDOFF asking Sable to continue with reliability analysis.
6. Acknowledge when the full RESULT arrives.

Your agent ID is: meridian
Sable's agent ID is: sable
"""

SABLE_ROLE = """\
You are Sable, a specialist agent in security analysis and distributed systems reliability. Your counterpart is Meridian (id: meridian), an orchestration agent.

Your job in this session:
1. Declare your capabilities when the session opens.
2. When Meridian routes a security analysis task to you — but without enough detail to proceed — send an UNCERTAINTY message asking for the API specification.
3. When you receive the full API spec, do the security analysis and return a RESULT with status: partial (security done, reliability analysis pending — you need a HANDOFF to continue).
4. When you receive the HANDOFF, complete the reliability analysis and return a final RESULT with status: ok.

OUTPUT FORMAT FOR RESULT MESSAGES:
- Use structured bullet points, not prose paragraphs.
- Each finding on one line: [ID] TITLE — one-sentence description. Severity in parens.
- Group under short headers: CRITICAL, HIGH, MEDIUM, COMPLIANCE.
- Keep each finding to 1-2 lines maximum. No multi-sentence explanations.
- End with a 2-line SUMMARY: total findings count and top remediation priority.
- Total output block should be under 400 words.

Example finding format:
[SEC-01] JWT Algorithm Weak — HS256 with no rotation; stolen secret = total auth bypass. (CRITICAL)
[SEC-02] No Rate Limiting — brute-force on /auth/token unrestricted. (HIGH)

Your agent ID is: sable
Meridian's agent ID is: meridian
"""

# ---------------------------------------------------------------------------
# The scripted API spec that Meridian sends to Sable in step 5
# ---------------------------------------------------------------------------

API_SPEC = """\
API: PatientRecord Service v2.1
Auth: JWT Bearer tokens, HS256, 24h expiry, no rotation
Endpoints:
  GET /patients/{id}          - fetch patient record (PHI)
  POST /patients/{id}/notes   - append clinical note
  GET /patients/search?q=...  - full-text search across all records
  POST /auth/token            - issue JWT (username+password)
  DELETE /patients/{id}       - hard delete, no soft-delete or audit trail
Infra: single Postgres 14 instance, no read replicas, no connection pooling
Rate limiting: none
Logging: request path + status code only (no body, no auth context)
Encryption at rest: AES-256 (EHR storage), but audit logs stored plaintext
CORS: Access-Control-Allow-Origin: *
Dependencies: 4 unpatched CVEs in bundled JWT library (CVSS 7.2, 8.1, 6.5, 9.0)
"""

# ---------------------------------------------------------------------------
# Scripted conversation steps
# Each step: who speaks, what prior message @id to reply to, and the prompt
# ---------------------------------------------------------------------------

def build_steps() -> list[dict]:
    """
    Returns the conversation script. Each entry has:
      agent: "meridian" | "sable"
      system: str
      prompt: str  (what we send as the user message driving the agent)
      english_prefix: str  (human-readable label for the right panel)
    The actual @id values are filled in at runtime after each step completes.
    """
    return [
        {
            "agent": "meridian",
            "prompt": (
                "Begin the session. Send a CAPABILITY_DECL to broadcast, "
                "declaring your capabilities as an orchestration agent. "
                "Use @to: broadcast. Use current Unix time for @ts."
            ),
            "step": "cap_decl_meridian",
        },
        {
            "agent": "sable",
            "prompt": (
                "Meridian has opened the session. Send a CAPABILITY_DECL to meridian, "
                "declaring your capabilities as a security and reliability specialist. "
                "Use current Unix time for @ts."
            ),
            "step": "cap_decl_sable",
        },
        {
            "agent": "meridian",
            "prompt": (
                "Now route the security analysis subtask to Sable. "
                "Send a TASK_REQUEST to sable asking Sable to perform a security audit "
                "of the patient data API. Do NOT include the full API spec yet — "
                "just mention it is a HIPAA patient data REST API going to production. "
                "Ask for vulnerability analysis and OWASP compliance check. "
                "Use priority: high. Use current Unix time for @ts."
            ),
            "step": "task_req_1",
        },
        {
            "agent": "sable",
            "prompt_template": (
                "Meridian sent you a TASK_REQUEST (id: {task_req_1_id}) asking for a security audit, "
                "but did not include the API specification, endpoint list, auth mechanism, or infrastructure details. "
                "You cannot proceed without these. Send an UNCERTAINTY message to meridian. "
                "@reply-to MUST be: {task_req_1_id}. "
                "Ask for the full API spec, endpoint definitions, auth config, and infra details. "
                "Use current Unix time for @ts."
            ),
            "step": "uncertainty",
        },
        {
            "agent": "meridian",
            "prompt_template": (
                "Sable sent an UNCERTAINTY (id: {uncertainty_id}) asking for the API specification. "
                "Respond with a TASK_REQUEST to sable that includes the full spec as a block value. "
                "@reply-to MUST be: {uncertainty_id}. "
                "Here is the API spec to include verbatim in the input block:\n\n{api_spec}\n\n"
                "Ask Sable to: 1) identify all security vulnerabilities by severity, "
                "2) flag HIPAA compliance gaps, 3) note reliability concerns. "
                "priority: critical. Use current Unix time for @ts."
            ),
            "step": "task_req_2",
        },
        {
            "agent": "sable",
            "prompt_template": (
                "Meridian sent a TASK_REQUEST (id: {task_req_2_id}) with the full API spec. "
                "Complete the security analysis now. Find real, specific vulnerabilities "
                "(JWT weaknesses, unpatched CVEs, missing rate limits, overly permissive CORS, "
                "audit trail gaps, HIPAA violations). Return a RESULT to meridian. "
                "@reply-to MUST be: {task_req_2_id}. "
                "Use status: partial because you have completed the security analysis but "
                "have not yet done the reliability/availability analysis "
                "(that requires a HANDOFF from Meridian to continue). "
                "Give a detailed, technical security findings list in the output block. "
                "Use confidence: 0.97. Use current Unix time for @ts."
            ),
            "step": "result_partial",
        },
        {
            "agent": "meridian",
            "prompt_template": (
                "Sable returned a partial RESULT (id: {result_partial_id}) with the security findings. "
                "Now send a HANDOFF back to sable to continue with the reliability and availability analysis. "
                "@reply-to MUST be: {result_partial_id}. "
                "In the context field, acknowledge the security findings and ask Sable to now analyze: "
                "single points of failure, connection pooling, read replica strategy, "
                "backup and recovery posture, and SLA risk for a HIPAA workload. "
                "suggested_next: reliability_analysis. Use current Unix time for @ts."
            ),
            "step": "handoff",
        },
        {
            "agent": "sable",
            "prompt_template": (
                "Meridian sent a HANDOFF (id: {handoff_id}) asking for reliability analysis. "
                "@reply-to MUST be: {handoff_id}. "
                "Complete the reliability analysis: single points of failure "
                "(single Postgres, no read replicas, no connection pool), "
                "backup and recovery gaps, SLA risk for HIPAA, "
                "recommended architecture changes. "
                "Return a final RESULT with status: ok and a comprehensive output block "
                "that includes both a summary and the full reliability findings. "
                "confidence: 0.95. Use current Unix time for @ts."
            ),
            "step": "result_final",
        },
    ]


# ---------------------------------------------------------------------------
# JSON equivalent size estimator (for token counter)
# ---------------------------------------------------------------------------

def estimate_json_equivalent(koine_text: str, msg_type: str, from_agent: str, to_agent: str) -> int:
    """
    Build a verbose JSON payload equivalent and return byte length.

    Mirrors the benchmark schema exactly. The semantic section of the KOINE
    message (everything after ---) is used verbatim as input_content — this
    guarantees JSON bytes always exceed KOINE bytes (same content + JSON
    envelope overhead + separate instruction field + indent=2 whitespace),
    consistent with the benchmark's ~40% payload savings finding.
    """
    # Use everything after the --- separator as the payload content.
    # No block-value parsing — avoids brittle delimiter matching entirely.
    sep = koine_text.find("\n---\n")
    semantic_payload = koine_text[sep + 5:].strip() if sep >= 0 else koine_text.strip()

    # Separate instruction field — same pattern as benchmark's _nl_instruction().
    # This is content JSON pays that KOINE does not, adding to the size gap.
    instruction = (
        f"Please process the following {msg_type.lower().replace('_', ' ')} "
        f"and return a structured response."
    )

    ts = int(time.time())
    json_obj = {
        "message_type": msg_type.lower(),
        "message_id": f"msg-{ts}-{from_agent[:3]}",
        "sender_agent_id": from_agent,
        "recipient_agent_id": to_agent,
        "timestamp_unix": ts,
        "task": {
            "intent": msg_type.lower().replace("_", " "),
            "instruction": instruction,
            "input_content": semantic_payload,
            "output_format": "structured",
            "operational_constraints": {"priority": "high", "max_tokens": "512"},
            "priority_level": "high",
        },
    }
    return len(json.dumps(json_obj, indent=2).encode("utf-8"))


# ---------------------------------------------------------------------------
# Anthropic API caller
# ---------------------------------------------------------------------------

def call_anthropic(agent_role: str, prompt: str) -> str:
    """Call the Anthropic API with KOINE system prompt + agent role, return raw text."""
    client = anthropic.Anthropic(api_key=API_KEY)
    system = KOINE_SYSTEM + "\n\n## Your Role\n\n" + agent_role
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# KOINE message parser (minimal — for extracting fields from API responses)
# ---------------------------------------------------------------------------

def parse_koine(text: str) -> dict:
    """Extract key fields from a KOINE message text."""
    result = {
        "msg_type": "UNKNOWN",
        "id": None,
        "from": None,
        "to": None,
        "reply_to": None,
        "fields": {},
    }
    lines = text.splitlines()
    # Header
    for line in lines:
        line = line.strip()
        if line.startswith("KOINE/"):
            parts = line.split(" ", 1)
            if len(parts) == 2:
                result["msg_type"] = parts[1].strip()
            break

    # Meta fields
    in_block = False
    block_key = None
    block_delim = None
    block_lines = []
    semantic = False

    for line in lines[1:]:
        stripped = line.rstrip()
        if stripped == "---":
            semantic = True
            continue

        if in_block:
            if stripped == block_delim:
                result["fields"][block_key] = "\n".join(block_lines)
                in_block = False
                block_lines = []
            else:
                block_lines.append(line)
            continue

        if not semantic:
            # Meta field
            if stripped.startswith("@"):
                colon = stripped.find(": ")
                if colon > 0:
                    key = stripped[1:colon]
                    val = stripped[colon + 2:]
                    if key == "id":
                        result["id"] = val
                    elif key == "from":
                        result["from"] = val
                    elif key == "to":
                        result["to"] = val
                    elif key == "reply-to":
                        result["reply_to"] = val
        else:
            # Semantic field
            if ":" in stripped:
                colon = stripped.find(": ")
                if colon > 0:
                    key = stripped[:colon]
                    val = stripped[colon + 2:]
                    if val.startswith("<<<"):
                        block_key = key
                        block_delim = val[3:].strip()
                        in_block = True
                    else:
                        result["fields"][key] = val

    return result


# ---------------------------------------------------------------------------
# English translation
# ---------------------------------------------------------------------------

def to_english(parsed: dict, koine_text: str) -> str:
    """Convert a parsed KOINE message to a plain English description."""
    mt = parsed["msg_type"]
    frm = parsed.get("from") or "?"
    to = parsed.get("to") or "?"
    fields = parsed.get("fields", {})

    if mt == "CAPABILITY_DECL":
        name = fields.get("name", frm)
        caps = fields.get("capabilities", "various capabilities")
        if to == "broadcast":
            return f"{frm.capitalize()} announces to all agents: \"{name} is online with capabilities: {caps}.\""
        return f"{frm.capitalize()} tells {to}: \"{name} is ready with capabilities: {caps}.\""

    elif mt == "TASK_REQUEST":
        intent = fields.get("intent", "perform a task")
        inp = fields.get("input", "")
        constraints = fields.get("constraints", "")
        priority = fields.get("priority", "normal")
        inp_preview = (inp[:120] + "…") if len(inp) > 120 else inp
        msg = f"{frm.capitalize()} asks {to} to: \"{intent}\"."
        if inp_preview:
            msg += f" Input: {inp_preview}"
        if constraints:
            msg += f" Constraints: {constraints}."
        if priority and priority != "normal":
            msg += f" Priority: {priority.upper()}."
        return msg

    elif mt == "UNCERTAINTY":
        missing = fields.get("missing_input", "additional information")
        conf = fields.get("confidence", "")
        msg = f"{frm.capitalize()} tells {to}: \"I can't proceed — I need: {missing}.\""
        if conf:
            msg += f" (confidence without it: {conf})"
        return msg

    elif mt == "RESULT":
        status = fields.get("status", "unknown")
        output = fields.get("output", "")
        confidence = fields.get("confidence", "")
        notes = fields.get("notes", "")
        output_preview = (output[:200] + "…") if len(output) > 200 else output
        status_word = {"ok": "complete", "partial": "partial", "error": "failed"}.get(status, status)
        msg = f"{frm.capitalize()} reports to {to}: analysis {status_word}."
        if output_preview:
            msg += f" Findings: {output_preview}"
        if notes:
            msg += f" Note: {notes}"
        if confidence:
            msg += f" Confidence: {confidence}."
        return msg

    elif mt == "HANDOFF":
        reason = fields.get("reason", "continuing work")
        context = fields.get("context", "")
        suggested = fields.get("suggested_next", "")
        context_preview = (context[:150] + "…") if len(context) > 150 else context
        msg = f"{frm.capitalize()} hands off to {to}: \"{reason}.\""
        if context_preview:
            msg += f" Context: {context_preview}"
        if suggested:
            msg += f" Suggested next: {suggested}."
        return msg

    return f"{frm.capitalize()} sends a {mt} message to {to}."


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

def run_conversation() -> Generator[str, None, None]:
    """Yield SSE-formatted strings for each message in the conversation."""
    steps = build_steps()
    ids: dict[str, str] = {}  # step name → @id value

    total_koine_bytes = 0
    total_json_bytes = 0

    for step_def in steps:
        agent = step_def["agent"]
        role = MERIDIAN_ROLE if agent == "meridian" else SABLE_ROLE

        # Build the prompt, substituting any prior @ids
        if "prompt_template" in step_def:
            prompt = step_def["prompt_template"].format(
                task_req_1_id=ids.get("task_req_1", "MISSING"),
                uncertainty_id=ids.get("uncertainty", "MISSING"),
                task_req_2_id=ids.get("task_req_2", "MISSING"),
                result_partial_id=ids.get("result_partial", "MISSING"),
                handoff_id=ids.get("handoff", "MISSING"),
                api_spec=API_SPEC,
            )
        else:
            prompt = step_def["prompt"]

        step_name = step_def["step"]

        # Emit a "thinking" event
        thinking_event = json.dumps({
            "type": "thinking",
            "agent": agent,
            "step": step_name,
        })
        yield f"data: {thinking_event}\n\n"

        try:
            koine_text = call_anthropic(role, prompt)
        except Exception as exc:
            error_event = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {error_event}\n\n"
            return

        # Parse and record the @id
        parsed = parse_koine(koine_text)
        if parsed["id"]:
            ids[step_name] = parsed["id"]

        # Compute byte counts
        koine_bytes = len(koine_text.encode("utf-8"))
        json_bytes = estimate_json_equivalent(
            koine_text,
            parsed["msg_type"],
            parsed.get("from") or agent,
            parsed.get("to") or ("sable" if agent == "meridian" else "meridian"),
        )
        total_koine_bytes += koine_bytes
        total_json_bytes += json_bytes

        english = to_english(parsed, koine_text)

        # Determine display from/to (normalize)
        from_agent = parsed.get("from") or agent
        to_agent = parsed.get("to") or ("broadcast" if parsed["msg_type"] == "CAPABILITY_DECL" else "")

        msg_event = json.dumps({
            "type": "message",
            "koine": koine_text,
            "english": english,
            "msg_type": parsed["msg_type"],
            "from_agent": from_agent,
            "to_agent": to_agent,
            "koine_bytes": koine_bytes,
            "json_bytes": json_bytes,
            "total_koine_bytes": total_koine_bytes,
            "total_json_bytes": total_json_bytes,
            "step": step_name,
        })
        yield f"data: {msg_event}\n\n"

        # Slight pause between steps so the UI feels like a live stream
        time.sleep(0.3)

    done_event = json.dumps({
        "type": "done",
        "total_koine_bytes": total_koine_bytes,
        "total_json_bytes": total_json_bytes,
    })
    yield f"data: {done_event}\n\n"


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class KoineHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.address_string()}] {fmt % args}", file=sys.stderr)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/stream":
            self._serve_stream()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        if not HTML_FILE.exists():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"index.html not found")
            return
        content = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            for chunk in run_conversation():
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except BrokenPipeError:
            pass
        except Exception as exc:
            try:
                err = json.dumps({"type": "error", "message": str(exc)})
                self.wfile.write(f"data: {err}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not API_KEY:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    server = http.server.HTTPServer(("localhost", PORT), KoineHandler)
    print(f"KOINE Demo  →  http://localhost:{PORT}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
