#!/usr/bin/env python3
"""
Run the KOINE parser, validator, and renderer against every example message
in the spec, including the signed DID example from §5.5.1.

Usage:
    cd /Users/chu/koine/src
    python run_examples.py
"""
from __future__ import annotations

import sys
import textwrap
sys.path.insert(0, '.')

import koine
from koine import parse_message, split_stream, validate, render
from koine.models import ParseError
from koine.identity import verify_did_signature


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

PASS  = "✓"
FAIL  = "✗"
SKIP  = "⊘"
WARN  = "⚠"

W = 72  # display width

def hr(char='━'):
    print(char * W)

def section(title):
    print()
    hr()
    print(f" {title}")
    hr()

def subsection(n, label):
    print(f"\n{'─' * W}")
    print(f"  [{n}] {label}")
    print('─' * W)

def indent(text, prefix='      '):
    return textwrap.indent(str(text), prefix)

def run_one(label: str, text: str, *,
            note: str = None,
            skip_did: bool = False,
            expect_invalid: bool = False):
    """
    Parse, validate, and render a single message.  Print results.

    expect_invalid=True: the message is intentionally malformed; a validation
    failure is the correct outcome and counts as a pass.
    """
    # --- Parse ---
    result = parse_message(text)
    if isinstance(result, ParseError):
        line_info = f" (line {result.line})" if result.line else ""
        print(f"  PARSE    {FAIL}  {result.message}{line_info}")
        return False

    print(f"  PARSE    {PASS}  KOINE/{result.version[0]}.{result.version[1]} {result.msg_type}")

    # --- Validate ---
    vr = validate(result)
    if expect_invalid:
        if not vr.valid:
            print(f"  VALIDATE {PASS}  Correctly rejected (expected invalid):")
            for e in vr.errors:
                print(f"           {FAIL}  [{e.field}] {e.message}")
        else:
            print(f"  VALIDATE {FAIL}  Expected rejection but message passed validation")
    else:
        if vr.valid:
            print(f"  VALIDATE {PASS}")
        else:
            print(f"  VALIDATE {FAIL}")
            for e in vr.errors:
                print(f"           {FAIL}  [{e.field}] {e.message}")
    for w in vr.warnings:
        print(f"  {WARN} WARNING  {w}")

    # --- @did verification (optional) ---
    if result.meta.did and not skip_did:
        vfy = verify_did_signature(result)
        sym = PASS if vfy.verified else FAIL
        method = f" ({vfy.method})" if vfy.method else ""
        print(f"  @did     {sym}  {vfy.reason}{method}")
    elif result.meta.did and skip_did:
        print(f"  @did     {SKIP}  Verification skipped (see note)")

    # --- Render ---
    rendered = render(result)
    print(f"  RENDER   {PASS}")
    for line in rendered.split('\n'):
        print(f"           {line}")

    if note:
        print(f"  {WARN} NOTE     {note}")

    if expect_invalid:
        return not vr.valid   # pass iff validator correctly rejected
    return vr.valid


passed = 0
failed = 0
total  = 0

def run(label, text, **kwargs):
    global passed, failed, total
    total += 1
    ok = run_one(label, text, **kwargs)
    if ok:
        passed += 1
    else:
        failed += 1


# ===========================================================================
# §4.1  TASK_REQUEST
# ===========================================================================

section("§4.1  TASK_REQUEST")

subsection(1, "TASK_REQUEST — §4.1 example (block input, constraints, TTL)")
run("TASK_REQUEST §4.1", """\
KOINE/1.0 TASK_REQUEST
@id: tr-9f2a1c
@from: orchestrator-1
@to: summarizer-3
@ts: 1712534400
@ttl: 60
---
intent: summarize
input: <<<END
The Board of Directors met on March 15th to discuss Q1 results.
Revenue was up 12% year-over-year, driven by enterprise subscriptions.
Operating costs increased 8% due to expanded headcount in engineering.
The board approved a dividend of $0.42 per share, payable April 30th.
END
output_format: plain
constraints: max_tokens=80,style=executive
priority: high
""")


# ===========================================================================
# §4.2  CAPABILITY_DECL
# ===========================================================================

section("§4.2  CAPABILITY_DECL")

subsection(2, "CAPABILITY_DECL — §4.2 example (broadcast, full fields)")
run("CAPABILITY_DECL §4.2", """\
KOINE/1.0 CAPABILITY_DECL
@id: cd-3b91e2
@from: summarizer-3
@to: broadcast
@ts: 1712534000
---
name: Summarizer
version: 2.1.0
intents: summarize,condense,tldr,abstract
input_types: text/plain,text/markdown,text/html
output_types: text/plain,text/markdown
cost_hint: 1200
latency_hint: 850
constraints_accepted: max_tokens=150,style=executive,lang=en
auth_required: false
scope: public
max_input_tokens: 32000
languages: en,fr,de,es,zh
description: Extractive and abstractive summarization agent. Honors max_tokens and style constraints.
""")


# ===========================================================================
# §4.3  RESULT
# ===========================================================================

section("§4.3  RESULT")

subsection(3, "RESULT — §4.3 example (status: ok)")
run("RESULT §4.3", """\
KOINE/1.0 RESULT
@id: rs-7c4f81
@from: summarizer-3
@to: orchestrator-1
@ts: 1712534402
@reply-to: tr-9f2a1c
---
status: ok
output: Q1 revenue rose 12% YoY on enterprise subscriptions; costs up 8% from engineering headcount. Board approved $0.42/share dividend, payable Apr 30.
confidence: 0.97
tokens_used: 847
latency_ms: 612
""")


# ===========================================================================
# §4.4  HANDOFF
# ===========================================================================

section("§4.4  HANDOFF")

subsection(4, "HANDOFF — §4.4 example (with trust_chain)")
run("HANDOFF §4.4", """\
KOINE/1.0 HANDOFF
@id: ho-2d5a99
@from: orchestrator-1
@to: translator-7
@ts: 1712534403
@reply-to: tr-9f2a1c
@trace: orchestrator-1,summarizer-3
---
reason: output_format=fr requested but summarizer-3 does not support French output
target: translator-7
context: Summarization complete. Passing summary for translation to French.
partial_result: Q1 revenue rose 12% YoY on enterprise subscriptions; costs up 8% from engineering headcount. Board approved $0.42/share dividend, payable Apr 30.
trust_chain: orchestrator-1,summarizer-3
instructions: translate to French, preserve executive register
priority: high
""")


# ===========================================================================
# §4.5  UNCERTAINTY
# ===========================================================================

section("§4.5  UNCERTAINTY")

subsection(5, "UNCERTAINTY — §4.5 example (block alternatives)")
run("UNCERTAINTY §4.5", """\
KOINE/1.0 UNCERTAINTY
@id: un-4e8b12
@from: classifier-2
@to: orchestrator-1
@ts: 1712534410
@reply-to: tr-bb3141
---
kind: ambiguous_intent
description: Intent "process document" is too broad. Could mean extract, classify, summarize, or translate.
confidence: 0.31
clarification_needed: Which operation is required: extract entities, classify sentiment, summarize content, or translate?
alternatives: <<<END
1. extract: pull named entities and key facts
2. classify: assign sentiment or topic labels
3. summarize: produce an abstractive summary
4. translate: convert to target language
END
can_proceed: false
""")


# ===========================================================================
# §4.6  EXTENSION_PROPOSAL
# ===========================================================================

section("§4.6  EXTENSION_PROPOSAL")

subsection(6, "EXTENSION_PROPOSAL — §4.6 example (nested block spec + examples)")
run("EXTENSION_PROPOSAL §4.6", """\
KOINE/1.0 EXTENSION_PROPOSAL
@id: ep-1a7c44
@from: orchestrator-1
@to: broadcast
@ts: 1712600000
---
name: FEEDBACK
kind: message_type
rationale: <<<END
Multi-agent pipelines need a way to propagate quality signals back to
producing agents without issuing a new TASK_REQUEST. Observed in 14
production pipeline runs: agents downstream have no channel to signal
that upstream output was low quality, causing silent quality degradation.
END
spec: <<<END
KOINE/1.0 EXT/FEEDBACK
@id: <id>
@from: <id>
@to: <id>
@ts: <ts>
@reply-to: <id>
---
signal: "positive"|"negative"|"neutral"
strength: <prob>
[aspect: <str>]
[detail: <str|block>]
END
examples: <<<END
KOINE/1.0 EXT/FEEDBACK
@id: fb-991abc
@from: evaluator-1
@to: summarizer-3
@ts: 1712601000
@reply-to: rs-7c4f81
---
signal: negative
strength: 0.72
aspect: completeness
detail: Summary omitted the dividend announcement, which was flagged as critical by downstream agents.
END
adoption_threshold: 3
""")


# ===========================================================================
# §5.5.1  DID-signed TASK_REQUEST (identity verification)
# ===========================================================================

section("§5.5.1  DID-signed TASK_REQUEST  (@did + @rep)")

subsection(7, "DID example — §5.5.1 (as shown in spec, body completed from fragment)")
print(f"  {WARN} NOTE     The spec body shows 'intent: summarize\\n...' as an illustrative")
print(f"           fragment.  The '...' is not valid KOINE; the message below is the")
print(f"           completed version used for testing.  The signature was written as")
print(f"           an illustrative value in the spec and is NOT cryptographically valid.")
run("DID §5.5.1", """\
KOINE/1.0 TASK_REQUEST
@id: tr-9f2a1c
@from: orchestrator-1
@to: summarizer-3
@ts: 1712534400
@did: did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK sig:3vI7tYBqnMiXmCsPXncQtLHzXmWgfVBmJpvCoDQVnqeJrgqmHXzNS_-LHakJTz8yAbRuPyv8dJYEAnBhRk1LAw
---
intent: summarize
input: The Board of Directors met on March 15th to discuss Q1 results.
output_format: plain
priority: high
""",
note="Signature verification expected to FAIL — illustrative value in spec, not computed by Ed25519 signing.")

# Also test @rep parsing
subsection(8, "@rep field — §5.5.2 example (score + src DID)")
print(f"  Verifying @rep parse: '0.91 src:did:web:reputation.koine-protocol.org'")
run("@rep §5.5.2", """\
KOINE/1.0 TASK_REQUEST
@id: tr-rep-01
@from: trusted-agent
@to: executor-1
@ts: 1712534400
@rep: 0.91 src:did:web:reputation.koine-protocol.org
---
intent: classify
input: Sample text for classification.
""")


# ===========================================================================
# §11.1  Complete two-agent pipeline (multi-message stream)
# ===========================================================================

section("§11.1  Complete two-agent pipeline (6 messages via split_stream)")

PIPELINE = """\
KOINE/1.0 CAPABILITY_DECL
@id: cd-alpha-01
@from: research-agent
@to: broadcast
@ts: 1712534000
---
name: Research Agent
version: 1.0.0
intents: research,find,lookup,retrieve
input_types: text/plain
output_types: text/plain,text/markdown
cost_hint: 3500
latency_hint: 2200
scope: public

===

KOINE/1.0 CAPABILITY_DECL
@id: cd-beta-01
@from: writer-agent
@to: broadcast
@ts: 1712534001
---
name: Writer Agent
version: 1.0.0
intents: write,draft,compose,rewrite
input_types: text/plain,text/markdown
output_types: text/plain,text/markdown
cost_hint: 2100
latency_hint: 1400
scope: public

===

KOINE/1.0 TASK_REQUEST
@id: tr-main-01
@from: orchestrator
@to: research-agent
@ts: 1712534100
@ttl: 300
---
intent: research
input: What were the key technical breakthroughs in large language models between 2022 and 2024?
output_format: text/markdown
constraints: max_items=5,style=technical
priority: normal
budget: max_tokens=4000,max_latency_ms=5000

===

KOINE/1.0 RESULT
@id: rs-main-01
@from: research-agent
@to: orchestrator
@ts: 1712534103
@reply-to: tr-main-01
---
status: ok
output: <<<END
## Key LLM Breakthroughs 2022–2024

1. **RLHF at scale** (2022): InstructGPT demonstrated that reinforcement learning from human feedback dramatically improved instruction-following without sacrificing capability.
2. **Emergent in-context learning** (2022): Chain-of-thought prompting revealed that sufficiently large models could reason through multi-step problems when shown examples.
3. **Efficient attention** (2023): Flash Attention and grouped-query attention reduced memory requirements, enabling longer context windows at lower cost.
4. **Mixture of Experts routing** (2024): Sparse MoE architectures achieved frontier capability at a fraction of the inference cost of dense models.
5. **Multimodal unification** (2023–2024): Single models processing text, images, audio, and code under one architecture, eliminating pipeline complexity.
END
confidence: 0.91
tokens_used: 2847
latency_ms: 2103

===

KOINE/1.0 TASK_REQUEST
@id: tr-main-02
@from: orchestrator
@to: writer-agent
@ts: 1712534104
@reply-to: tr-main-01
---
intent: rewrite
input: <<<END
## Key LLM Breakthroughs 2022–2024

1. **RLHF at scale** (2022): InstructGPT demonstrated that reinforcement learning from human feedback dramatically improved instruction-following without sacrificing capability.
2. **Emergent in-context learning** (2022): Chain-of-thought prompting revealed that sufficiently large models could reason through multi-step problems when shown examples.
3. **Efficient attention** (2023): Flash Attention and grouped-query attention reduced memory requirements, enabling longer context windows at lower cost.
4. **Mixture of Experts routing** (2024): Sparse MoE architectures achieved frontier capability at a fraction of the inference cost of dense models.
5. **Multimodal unification** (2023–2024): Single models processing text, images, audio, and code under one architecture, eliminating pipeline complexity.
END
output_format: text/plain
constraints: style=executive,max_tokens=120,audience=board
priority: normal

===

KOINE/1.0 RESULT
@id: rs-main-02
@from: writer-agent
@to: orchestrator
@ts: 1712534106
@reply-to: tr-main-02
---
status: ok
output: Between 2022 and 2024, AI language models advanced on five fronts: better instruction-following through human feedback training, step-by-step reasoning via chain-of-thought, longer context at lower memory cost, sparse expert architectures that cut inference cost, and unified models handling text, images, and audio together.
confidence: 0.95
tokens_used: 1203
latency_ms: 894
"""

messages = split_stream(PIPELINE)
print(f"\n  split_stream() found {len(messages)} messages")

pipeline_labels = [
    "CAPABILITY_DECL — research-agent (broadcast)",
    "CAPABILITY_DECL — writer-agent (broadcast)",
    "TASK_REQUEST — research (with budget)",
    "RESULT — research (block output, ok)",
    "TASK_REQUEST — rewrite (block input)",
    "RESULT — rewrite (ok)",
]

for idx, (msg_text, label) in enumerate(zip(messages, pipeline_labels), start=9):
    subsection(idx, f"Pipeline msg {idx - 8}/6: {label}")
    run(label, msg_text)


# ===========================================================================
# Edge cases
# ===========================================================================

section("Edge cases")

subsection(15, "EXT/ message type — unknown extension (must not fail)")
run("EXT/ unknown", """\
KOINE/1.0 EXT/FEEDBACK
@id: fb-test-01
@from: evaluator-1
@to: summarizer-3
@ts: 1712601000
@reply-to: rs-7c4f81
---
signal: negative
strength: 0.72
aspect: completeness
detail: Test feedback message.
""")

subsection(16, "Unknown meta + semantic fields preserved (forwards compat)")
run("Unknown fields §7.3", """\
KOINE/1.0 TASK_REQUEST
@id: tr-fwd-01
@from: agent-a
@to: agent-b
@ts: 1712534400
@x-custom-routing: datacenter-eu
---
intent: classify
input: Some text to classify.
x_experimental_field: some future value
""")

subsection(17, "Higher minor version accepted (§7.3)")
run("Minor version bump", """\
KOINE/1.9 TASK_REQUEST
@id: tr-ver-01
@from: agent-a
@to: agent-b
@ts: 1712534400
---
intent: summarize
input: Content to summarize.
""")

subsection(18, "RESULT status: failed (error_code required)")
run("RESULT failed", """\
KOINE/1.0 RESULT
@id: rs-fail-01
@from: classifier-2
@to: orchestrator-1
@ts: 1712534500
@reply-to: tr-bb3141
---
status: failed
error_code: E_INTENT_UNKNOWN
error_detail: Intent "obliterate" is not in this agent's declared intent list.
""")

subsection(19, "Routing loop detection in HANDOFF")
run("Routing loop §4.4", """\
KOINE/1.0 HANDOFF
@id: ho-loop-01
@from: agent-a
@to: agent-b
@ts: 1712534600
@reply-to: tr-orig-01
---
reason: Delegating to specialist
target: agent-b
trust_chain: orchestrator,agent-a
""",
note="Per §4.4: 'If @from appears in trust_chain, the receiving agent SHOULD emit UNCERTAINTY "
     "with kind: routing_loop'. agent-a is @from and appears in trust_chain, so the warning "
     "is correct. The spec example in §4.4 similarly triggers this warning on orchestrator-1.")

subsection(20, "HANDOFF self-handoff validation error (expect_invalid)")
run("Self-handoff error", """\
KOINE/1.0 HANDOFF
@id: ho-self-01
@from: agent-a
@to: agent-a
@ts: 1712534600
@reply-to: tr-orig-01
---
reason: Test self-handoff
target: agent-a
""", expect_invalid=True)

subsection(21, "Major version rejection (§7.3)")
print("  Attempting to parse KOINE/2.0 message (expect parse error)...")
result = parse_message("""\
KOINE/2.0 TASK_REQUEST
@id: tr-v2-01
@from: future-agent
@to: agent-b
@ts: 1712534400
---
intent: do something
input: content
""")
if isinstance(result, ParseError):
    print(f"  PARSE    {PASS}  Correctly rejected: {result.message}")
    passed += 1
else:
    print(f"  PARSE    {FAIL}  Should have been rejected but was parsed successfully")
    failed += 1
total += 1

subsection(22, "Missing required field (@reply-to on RESULT) (expect_invalid)")
run("Missing @reply-to on RESULT", """\
KOINE/1.0 RESULT
@id: rs-noreply-01
@from: agent-a
@to: orchestrator-1
@ts: 1712534400
---
status: ok
output: This result is missing @reply-to.
""", expect_invalid=True)

subsection(23, "Invalid @did format (parse failure, not validator failure)")
print("  Attempting @did with malformed value (no 'sig:' component)...")
result = parse_message("""\
KOINE/1.0 TASK_REQUEST
@id: tr-baddid-01
@from: agent-a
@to: agent-b
@ts: 1712534400
@did: did:key:z6MkExample (this is malformed, no sig component)
---
intent: classify
input: content
""")
if isinstance(result, ParseError):
    print(f"  PARSE    {FAIL}  Unexpected parse error: {result.message}")
    print(f"           Note: malformed @did should parse (as None) but not crash")
    failed += 1
    total += 1
else:
    # The parser stores None for unparseable @did; validator flags it
    vr = validate(result)
    did_errors = [e for e in vr.errors if e.field == '@did']
    if did_errors:
        print(f"  PARSE    {PASS}  Message parsed (malformed @did → None, preserved)")
        print(f"  VALIDATE {PASS}  Validator correctly flagged: {did_errors[0].message}")
        passed += 1
    else:
        print(f"  PARSE    {PASS}  Message parsed")
        print(f"  VALIDATE {FAIL}  Validator should have flagged malformed @did but did not")
        failed += 1
    total += 1


# ===========================================================================
# Summary
# ===========================================================================

print()
hr('═')
print(f"  RESULTS: {passed} passed  {failed} failed  {total} total")
hr('═')

if failed > 0:
    sys.exit(1)
