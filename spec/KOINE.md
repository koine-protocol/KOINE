# KOINE Protocol Specification
**Version:** 1.0  
**Status:** Draft  
**License:** Apache 2.0  
**Repository:** https://github.com/koine-protocol/koine

---

## 1. Introduction

KOINE is a semantic payload format for agent-to-agent communication. It sits above transport layers (MCP, A2A, HTTP, WebSocket) and below application logic — the same position HTTP occupies in the web stack.

The core problem: agents communicating today use either verbose JSON (high token cost, ambiguous semantics) or natural language (non-deterministic, unparseable). KOINE replaces both with a compact, tagged, machine-readable format that remains human-intelligible and can be deterministically rendered to plain English.

**Design principles:**
1. Machine-dense first. Every byte that reaches a model costs money.
2. Unambiguous structure. Parsing must not require inference.
3. Deterministic rendering. Any valid KOINE message maps to exactly one English sentence structure.
4. Forwards-compatible. Unknown fields are preserved, not rejected.
5. Extension-native. New message types emerge from usage, not committee votes.

---

## 2. Notation

This document uses an extended BNF:

```
<rule>      ::= definition
[field]     optional field
{field}     zero or more repetitions
<A> | <B>   alternation
"literal"   literal string
<type:X>    field with type constraint X
```

**Primitive types:**

| Type      | Description                                  | Example               |
|-----------|----------------------------------------------|-----------------------|
| `str`     | UTF-8 string, no unescaped newlines          | `hello world`         |
| `id`      | Alphanumeric + hyphens, 1–128 chars          | `agent-7f3a`          |
| `int`     | Signed 64-bit integer                        | `42`                  |
| `float`   | IEEE 754 double, decimal notation            | `0.93`                |
| `bool`    | `true` or `false`                            | `true`                |
| `list`    | Comma-separated values, no spaces around `,` | `summarize,translate` |
| `kv`      | Comma-separated `key=value` pairs            | `max_tokens=500,lang=en` |
| `semver`  | Semantic version                             | `1.2.0`               |
| `ts`      | Unix timestamp, integer seconds              | `1712534400`          |
| `block`   | Multi-line value (see §2.1)                  |                       |
| `prob`    | Float in [0.0, 1.0]                          | `0.87`                |

### 2.1 Block Values

When a field value spans multiple lines, use a heredoc-style delimiter:

```
field: <<<DELIM
line one
line two
DELIM
```

Rules:
- The delimiter must be a sequence of uppercase letters and underscores, 1–32 chars.
- The closing delimiter must appear alone on its own line, with no leading or trailing whitespace.
- Content between delimiters is taken verbatim, including blank lines.
- The most common delimiter is `END`; choose a different one if the content contains `END` on its own line.

---

## 3. Message Structure

Every KOINE message has three sections:

```
<header-line>
{<meta-field>}
---
{<semantic-field>}
```

### 3.1 Header Line

```
<header-line> ::= "KOINE/" <version> " " <msg-type> "\n"
<version>     ::= <int> "." <int>
<msg-type>    ::= "TASK_REQUEST"
               | "CAPABILITY_DECL"
               | "RESULT"
               | "HANDOFF"
               | "UNCERTAINTY"
               | "EXTENSION_PROPOSAL"
               | "EXT/" <id>
```

The version in the header line is the KOINE protocol version, not the sending agent's version. Implementations MUST reject messages whose major version is higher than their own. Implementations MUST accept messages whose minor version is higher than their own (forwards compatibility).

### 3.2 Meta Fields

Meta fields carry routing, identity, and timing information. They begin with `@`.

```
<meta-field> ::= "@" <meta-key> ": " <meta-value> "\n"
<meta-key>   ::= "id" | "from" | "to" | "ts" | "reply-to" | "ttl" | "trace" | "did" | "rep"
```

| Field       | Type      | Required         | Description                                                   |
|-------------|-----------|------------------|---------------------------------------------------------------|
| `@id`       | `id`      | Always           | Unique message identifier. MUST be globally unique.           |
| `@from`     | `id`      | Always           | Sending agent identifier.                                     |
| `@to`       | `id\|"broadcast"` | Most types  | Receiving agent identifier, or `broadcast` for all listeners. |
| `@ts`       | `ts`      | Always           | Unix timestamp of message creation.                           |
| `@reply-to` | `id`      | Conditional      | ID of the message this is responding to. Required for RESULT, HANDOFF, UNCERTAINTY. |
| `@ttl`      | `int`     | Optional         | Seconds until this message expires and should be discarded.   |
| `@trace`    | `list`    | Optional         | Ordered list of agent IDs that have handled this message chain. |
| `@did`      | `did-sig` | Optional         | W3C DID of the sending agent with a detached cryptographic signature (see §5.5). Recommended for production deployments. |
| `@rep`      | `rep-value` | Optional       | Reputation score in [0.0, 1.0] with optional issuing authority (see §5.5). Recommended for production deployments. |

Unknown `@`-prefixed fields MUST be preserved and forwarded unchanged. They MUST NOT cause parsing failure.

### 3.3 Separator

A line containing exactly `---` separates meta fields from semantic fields. It is required in all message types.

### 3.4 Semantic Fields

```
<semantic-field> ::= <field-key> ": " <field-value> "\n"
                   | <field-key> ": " <block-value>
<field-key>      ::= [a-z][a-z0-9_]*
<field-value>    ::= <str> | <int> | <float> | <bool> | <list> | <kv>
<block-value>    ::= "<<<" <delimiter> "\n" {<line> "\n"} <delimiter> "\n"
```

Unknown semantic fields MUST be preserved. They MUST NOT cause parsing failure. Parsers SHOULD surface them as an `extensions` dict or equivalent on the parsed object.

---

## 4. Message Types

### 4.1 TASK_REQUEST

Request an agent to perform a task.

```
KOINE/1.0 TASK_REQUEST
@id: <id>
@from: <id>
@to: <id>
@ts: <ts>
[@reply-to: <id>]
[@ttl: <int>]
[@trace: <list>]
---
intent: <str>
input: <str|block>
[output_format: <str>]
[constraints: <kv>]
[priority: "low"|"normal"|"high"|"critical"]
[context_ref: <id>]
[budget: <kv>]
```

**Semantic fields:**

| Field           | Type       | Required | Description                                                         |
|-----------------|------------|----------|---------------------------------------------------------------------|
| `intent`        | `str`      | Yes      | A verb phrase describing the desired operation. Short, unambiguous. Examples: `summarize`, `translate to French`, `classify sentiment`, `extract entities`. |
| `input`         | `str\|block` | Yes    | The content the agent should operate on.                           |
| `output_format` | `str`      | No       | Expected output structure. Examples: `json`, `markdown`, `koine`, `plain`. |
| `constraints`   | `kv`       | No       | Key-value operational constraints. Common keys: `max_tokens`, `lang`, `style`, `max_items`, `min_confidence`. |
| `priority`      | `str`      | No       | Processing urgency. Default: `normal`.                             |
| `context_ref`   | `id`       | No       | ID of a prior message whose context is relevant to this request.   |
| `budget`        | `kv`       | No       | Resource budget hints. Common keys: `max_tokens`, `max_latency_ms`, `max_cost_usd`. |

**Validation rules:**
- `intent` MUST NOT be empty.
- `input` MUST NOT be empty.
- `priority`, if present, MUST be one of the four enumerated values.
- `budget` values, if present, MUST parse as positive numbers.

**Human-readable rendering:**

```
Agent <@from> requests that agent <@to> <intent> the following input:
<input>
[Output format: <output_format>.]
[Constraints: <constraints>.]
[Priority: <priority>.]
[Budget: <budget>.]
```

**Example:**

```
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
```

---

### 4.2 CAPABILITY_DECL

Declare an agent's capabilities. Used in handshakes, discovery, and routing decisions.

```
KOINE/1.0 CAPABILITY_DECL
@id: <id>
@from: <id>
[@to: <id>|"broadcast"]
@ts: <ts>
---
name: <str>
version: <semver>
intents: <list>
input_types: <list>
output_types: <list>
[cost_hint: <int>]
[latency_hint: <int>]
[constraints_accepted: <kv>]
[auth_required: <bool>]
[scope: "public"|"private"|"trusted"]
[max_input_tokens: <int>]
[languages: <list>]
[description: <str|block>]
```

**Semantic fields:**

| Field                  | Type     | Required    | Description                                                         |
|------------------------|----------|-------------|---------------------------------------------------------------------|
| `name`                 | `str`    | Yes         | Human-readable agent name.                                         |
| `version`              | `semver` | Yes         | Agent's own version.                                               |
| `intents`              | `list`   | Yes         | Verbs this agent can fulfill. SHOULD match `intent` values in TASK_REQUEST. |
| `input_types`          | `list`   | Yes         | Accepted input MIME types or informal types. Examples: `text/plain`, `text/markdown`, `application/json`, `image/png`. |
| `output_types`         | `list`   | Yes         | Produced output types.                                             |
| `cost_hint`            | `int`    | Recommended | Estimated token cost per average request. Informs routing decisions. |
| `latency_hint`         | `int`    | Recommended | Estimated latency in milliseconds for an average request. Informs routing decisions. |
| `constraints_accepted` | `kv`     | No          | Constraint keys this agent honors, with their default values.      |
| `auth_required`        | `bool`   | No          | Whether requests must carry authentication. Default: `false`.      |
| `scope`                | `str`    | No          | Visibility. Default: `public`.                                     |
| `max_input_tokens`     | `int`    | No          | Maximum input size this agent will accept.                         |
| `languages`            | `list`   | No          | BCP-47 language codes supported. Omit if language-agnostic.        |
| `description`          | `str\|block` | No      | Free-text description of agent behavior.                           |

**Validation rules:**
- `cost_hint` and `latency_hint`, if present, MUST be positive integers.
- `scope`, if present, MUST be one of the three enumerated values.
- `auth_required`, if present, MUST be `true` or `false`.
- At least one entry in `intents` is required.

**Human-readable rendering:**

```
Agent <name> (v<version>, ID: <@from>) declares the following capabilities:
- Handles intents: <intents>
- Accepts input types: <input_types>
- Produces output types: <output_types>
[- Estimated cost: <cost_hint> tokens per request.]
[- Estimated latency: <latency_hint> ms per request.]
[- Scope: <scope>.]
[- Authentication required: <auth_required>.]
[- Supported languages: <languages>.]
```

**Example:**

```
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
```

---

### 4.3 RESULT

Return the outcome of a TASK_REQUEST.

```
KOINE/1.0 RESULT
@id: <id>
@from: <id>
@to: <id>
@ts: <ts>
@reply-to: <id>
[@trace: <list>]
---
status: "ok"|"partial"|"failed"
[output: <str|block>]
[confidence: <prob>]
[tokens_used: <int>]
[latency_ms: <int>]
[error_code: <str>]
[error_detail: <str|block>]
[meta: <kv>]
```

**Semantic fields:**

| Field          | Type       | Required                   | Description                                                         |
|----------------|------------|----------------------------|---------------------------------------------------------------------|
| `status`       | `str`      | Yes                        | Outcome of the task.                                               |
| `output`       | `str\|block` | Yes if status is `ok` or `partial` | The result of the task.                              |
| `confidence`   | `prob`     | No                         | Agent's self-assessed confidence in the output. 1.0 = certain.     |
| `tokens_used`  | `int`      | No                         | Actual tokens consumed. Used for budget tracking and benchmarking. |
| `latency_ms`   | `int`      | No                         | Actual wall-clock time from request receipt to response.           |
| `error_code`   | `str`      | Yes if status is `failed`  | Machine-readable error identifier.                                 |
| `error_detail` | `str\|block` | No                       | Human-readable error description.                                  |
| `meta`         | `kv`       | No                         | Arbitrary key-value metadata about the result.                     |

**Status semantics:**
- `ok`: Task completed successfully. `output` MUST be present.
- `partial`: Task partially completed. `output` SHOULD be present (contains what was completed). Often precedes a HANDOFF or UNCERTAINTY.
- `failed`: Task could not be completed. `error_code` MUST be present. `output` SHOULD be absent.

**Standard error codes:**

| Code                  | Meaning                                                    |
|-----------------------|------------------------------------------------------------|
| `E_INTENT_UNKNOWN`    | Agent does not recognize the requested intent.             |
| `E_INPUT_INVALID`     | Input does not match accepted types or is malformed.       |
| `E_INPUT_TOO_LARGE`   | Input exceeds `max_input_tokens`.                         |
| `E_BUDGET_EXCEEDED`   | Request would exceed stated budget.                        |
| `E_AUTH_REQUIRED`     | Agent requires authentication not provided.                |
| `E_TIMEOUT`           | Agent timed out before completing.                         |
| `E_INTERNAL`          | Agent encountered an internal error.                       |
| `E_CONSTRAINT_INVALID`| A constraint value is unrecognized or out of range.       |
| `E_IDENTITY_UNVERIFIABLE` | `@did` is present but the DID cannot be resolved or the signature does not verify. |

**Human-readable rendering:**

For `ok`:
```
Agent <@from> completed the task (request <@reply-to>).
Output: <output>
[Confidence: <confidence>.]
[Tokens used: <tokens_used>. Latency: <latency_ms>ms.]
```

For `partial`:
```
Agent <@from> partially completed the task (request <@reply-to>).
Partial output: <output>
[Confidence: <confidence>.]
```

For `failed`:
```
Agent <@from> failed to complete the task (request <@reply-to>).
Error: <error_code>[: <error_detail>]
```

**Example:**

```
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
```

---

### 4.4 HANDOFF

Transfer responsibility for a task to another agent, carrying all accumulated context.

```
KOINE/1.0 HANDOFF
@id: <id>
@from: <id>
@to: <id>
@ts: <ts>
@reply-to: <id>
[@trace: <list>]
---
reason: <str>
target: <id>
[context: <str|block>]
[partial_result: <str|block>]
[trust_chain: <list>]
[priority: "low"|"normal"|"high"|"critical"]
[instructions: <str|block>]
```

**Semantic fields:**

| Field            | Type       | Required | Description                                                         |
|------------------|------------|----------|---------------------------------------------------------------------|
| `reason`         | `str`      | Yes      | Why the handoff is occurring.                                      |
| `target`         | `id`       | Yes      | The agent ID that should receive the task next.                    |
| `context`        | `str\|block` | No     | Accumulated context the target agent needs. SHOULD include any state not derivable from prior messages. |
| `partial_result` | `str\|block` | No     | Work completed so far. The target agent should continue from here, not restart. |
| `trust_chain`    | `list`     | No       | Ordered list of agent IDs that have touched the original task. Used for loop detection and auditing. |
| `priority`       | `str`      | No       | Inherited from the original TASK_REQUEST if not overridden. Default: `normal`. |
| `instructions`   | `str\|block` | No     | Specific instructions for the target agent beyond what was in the original TASK_REQUEST. |

**Validation rules:**
- `@reply-to` is required and MUST reference a TASK_REQUEST or another HANDOFF.
- `target` MUST differ from `@from` (no self-handoff).
- `trust_chain`, if present, SHOULD include all prior `@from` values in message order.

**Loop detection:** If `@from` appears in `trust_chain`, the receiving agent SHOULD emit UNCERTAINTY with `kind: routing_loop` before forwarding.

**Human-readable rendering:**

```
Agent <@from> is handing off task <@reply-to> to agent <target>.
Reason: <reason>
[Agents in chain: <trust_chain>.]
[Work completed so far: <partial_result>]
[Context for target: <context>]
[Additional instructions: <instructions>]
```

**Example:**

```
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
```

---

### 4.5 UNCERTAINTY

Signal that an agent cannot complete a task with full confidence, and specify what is needed to proceed.

```
KOINE/1.0 UNCERTAINTY
@id: <id>
@from: <id>
@to: <id>
@ts: <ts>
@reply-to: <id>
---
kind: <uncertainty-kind>
description: <str|block>
confidence: <prob>
[clarification_needed: <str|block>]
[partial_result: <str|block>]
[alternatives: <str|block>]
[can_proceed: <bool>]
```

**Uncertainty kinds:**

| Kind                | Meaning                                                                  |
|---------------------|--------------------------------------------------------------------------|
| `ambiguous_intent`  | The `intent` field is ambiguous or too vague to act on reliably.        |
| `missing_input`     | Required input fields are absent or empty.                               |
| `input_ambiguous`   | Input is present but cannot be interpreted unambiguously.                |
| `out_of_scope`      | The requested task is outside this agent's declared capabilities.        |
| `low_confidence`    | Agent can produce output but self-assessed confidence is below threshold. |
| `resource_limit`    | Task would exceed a stated budget or system resource limit.               |
| `routing_loop`      | Agent appears in its own `trust_chain`, indicating a routing cycle.      |
| `conflicting_constraints` | Provided constraints are internally contradictory.              |

**Semantic fields:**

| Field                  | Type       | Required | Description                                                         |
|------------------------|------------|----------|---------------------------------------------------------------------|
| `kind`                 | `str`      | Yes      | Uncertainty category from the table above.                         |
| `description`          | `str\|block` | Yes    | Explanation of the uncertainty.                                    |
| `confidence`           | `prob`     | Yes      | Agent's current confidence level (0.0 = no idea, 1.0 = certain).  |
| `clarification_needed` | `str\|block` | No     | A specific question or data request that would resolve the uncertainty. |
| `partial_result`       | `str\|block` | No     | Output produced before uncertainty was reached.                    |
| `alternatives`         | `str\|block` | No     | Possible interpretations or alternative approaches.                |
| `can_proceed`          | `bool`     | No       | Whether the agent is willing to proceed at current confidence. Default: `false`. |

**Human-readable rendering:**

```
Agent <@from> reports uncertainty on task <@reply-to>.
Type: <kind>
Confidence: <confidence>
Description: <description>
[To proceed, the agent needs: <clarification_needed>]
[Possible alternatives: <alternatives>]
[Partial work completed: <partial_result>]
[Agent will proceed anyway: <can_proceed>]
```

**Example:**

```
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
```

---

### 4.6 EXTENSION_PROPOSAL

Propose a new message type or field for inclusion in the KOINE protocol.

```
KOINE/1.0 EXTENSION_PROPOSAL
@id: <id>
@from: <id>
[@to: <id>|"broadcast"]
@ts: <ts>
---
name: <str>
kind: "message_type"|"field"
[target_type: <str>]
rationale: <str|block>
spec: <block>
examples: <block>
[adoption_threshold: <int>]
[supersedes: <id>]
[incompatible_with: <list>]
```

**Semantic fields:**

| Field                | Type       | Required                           | Description                                                         |
|----------------------|------------|------------------------------------|---------------------------------------------------------------------|
| `name`               | `str`      | Yes                                | Proposed extension name. SCREAMING_SNAKE_CASE. For message types, will be addressed as `EXT/<name>`. |
| `kind`               | `message_type` or `field` | Yes                | What is being proposed.                                            |
| `target_type`        | `str`      | Yes if `kind` is `field`           | Which existing message type this field extends.                    |
| `rationale`          | `str\|block` | Yes                              | Why this extension is needed. SHOULD include evidence from real multi-agent usage. |
| `spec`               | `block`    | Yes                                | The proposed grammar, using the notation of §2.                   |
| `examples`           | `block`    | Yes                                | At least one complete valid example of the proposed extension.     |
| `adoption_threshold` | `int`      | No                                 | Number of independent implementations that trigger automatic ratification. Default: 3. |
| `supersedes`         | `id`       | No                                 | ID of a prior EXTENSION_PROPOSAL this replaces.                    |
| `incompatible_with`  | `list`     | No                                 | Names of extensions that conflict with this one.                   |

**Human-readable rendering:**

```
Agent <@from> proposes a KOINE extension: <name> (<kind>).
[Extends message type: <target_type>.]
Rationale: <rationale>
Proposed specification:
<spec>
Example:
<examples>
[Ratification threshold: <adoption_threshold> implementations.]
```

**Example:**

```
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
```

---

## 5. Handshake Protocol

Before exchanging TASK_REQUEST/RESULT messages, agents SHOULD perform a capability handshake. The handshake is optional but RECOMMENDED for all first-contact interactions.

### 5.1 Symmetric Handshake

```
A ──CAPABILITY_DECL──► B
A ◄──CAPABILITY_DECL── B
```

Both agents broadcast or direct their CAPABILITY_DECL. After the handshake, each agent has enough information to:
- Determine if the other agent can satisfy its requests (`intents` match)
- Estimate cost before committing (`cost_hint`, `latency_hint`)
- Know whether authentication is required
- Select the appropriate constraints to pass

### 5.2 Directed Handshake

When an orchestrator needs to commission a specific agent:

```
Orchestrator ──CAPABILITY_DECL @to:agent──► Agent
Orchestrator ◄──CAPABILITY_DECL @to:orchestrator── Agent
Orchestrator ──TASK_REQUEST──► Agent
Agent ──RESULT──► Orchestrator
```

### 5.3 Broadcast Discovery

When an orchestrator needs to find a capable agent from a pool:

```
Orchestrator ──CAPABILITY_DECL @to:broadcast──► [Pool]
[All agents] ──CAPABILITY_DECL @to:orchestrator──► Orchestrator
Orchestrator selects best agent based on intents, cost_hint, latency_hint
Orchestrator ──TASK_REQUEST──► selected-agent
selected-agent ──RESULT──► Orchestrator
```

**Selection criteria (RECOMMENDED priority order):**
1. `intents` overlap with required intent
2. `input_types` accepts the input format
3. `cost_hint` within `budget.max_tokens`
4. `latency_hint` within `budget.max_latency_ms`
5. `auth_required: false` preferred unless authentication is available

### 5.4 Handshake Caching

Agents MAY cache received CAPABILITY_DECLs. A cached declaration SHOULD be treated as stale after:
- The agent's version changes (detected via a new CAPABILITY_DECL with different `version`)
- A RESULT with `E_INTENT_UNKNOWN` is received from that agent
- Explicit cache invalidation via a new CAPABILITY_DECL from the same `@from`

### 5.5 Identity Verification

`@did` and `@rep` are optional in all message types. Including them is RECOMMENDED for any production deployment where agents execute consequential actions, access restricted resources, or communicate across organizational boundaries. Omitting them MUST NOT cause a parsing failure and carries no penalty in low-stakes or intra-trusted-network contexts.

#### 5.5.1 The `@did` Field

**Format:** `<did-uri> sig:<base64url-signature>`

`<did-uri>` is a W3C Decentralized Identifier per [DID Core](https://www.w3.org/TR/did-core/). The `sig:` component is a detached signature over the **canonical signing input**, base64url-encoded without padding.

**Canonical signing input** — the UTF-8 bytes of the header line followed by all `@`-prefixed meta fields in document order, excluding `@did` and `@rep`:

```
KOINE/1.0 TASK_REQUEST\n
@id: tr-9f2a1c\n
@from: orchestrator-1\n
@to: summarizer-3\n
@ts: 1712534400\n
```

The signature is computed using the verification method specified in the resolved DID document. The default algorithm is **Ed25519**. Implementations MUST support Ed25519. Support for secp256k1 and P-256 is RECOMMENDED.

**Verification steps:**
1. Parse `<did-uri>` from the `@did` value.
2. Resolve the DID document via the appropriate method resolver.
3. Extract the active verification key from the DID document.
4. Assemble the canonical signing input from the message's header line and non-identity meta fields.
5. Verify the signature against the extracted key.
6. If verification succeeds: treat `@from` as authenticated as the DID subject.
7. If DID resolution fails or times out: treat the message as having an unverifiable `@did` and apply the behavior defined in §5.5.3 — do not outright reject. If the signature does not verify despite a successful resolution: respond with RESULT `status: failed`, `error_code: E_IDENTITY_UNVERIFIABLE`. Do not proceed with the task.

**Resolution timeout and graceful degradation:** Implementations SHOULD enforce a DID resolution timeout of no more than 2000 ms. If resolution times out or the resolver returns unavailable, the message MUST be treated as having an unverifiable `@did` — per the behavior table in §5.5.3 — rather than rejected outright. This prevents a slow or unreachable resolver from causing cascading latency across an agent pipeline. Local policy MAY apply stricter rules on top of this default (e.g., a high-value financial workflow MAY reject any message whose `@did` could not be resolved within the timeout, regardless of §5.5.3 defaults). Caching of successful resolutions is RECOMMENDED to minimize repeated network lookups; appropriate cache freshness depends on the DID method (e.g., `did:key` documents are immutable and may be cached indefinitely, while `did:web` documents SHOULD be refreshed per their HTTP cache headers).

**Supported DID methods:** Implementations MUST support `did:key`. Support for `did:web`, `did:peer`, and `did:ion` is RECOMMENDED. Unknown DID methods SHOULD be treated as unresolvable; agents MAY proceed as if `@did` were absent rather than failing hard, at their discretion.

**Key rotation:** When an agent rotates its keys it MUST emit a new CAPABILITY_DECL carrying the updated `@did` value. Any cached CAPABILITY_DECL containing the previous `@did` SHOULD be invalidated upon the next failed signature verification from that `@from`.

**Example:**
```
KOINE/1.0 TASK_REQUEST
@id: tr-9f2a1c
@from: orchestrator-1
@to: summarizer-3
@ts: 1712534400
@did: did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK sig:3vI7tYBqnMiXmCsPXncQtLHzXmWgfVBmJpvCoDQVnqeJrgqmHXzNS_-LHakJTz8yAbRuPyv8dJYEAnBhRk1LAw
---
intent: summarize
...
```

#### 5.5.2 The `@rep` Field

**Format:** `<prob>[ src:<did-uri>]`

`<prob>` is a float in [0.0, 1.0] representing the sender's reputation as assessed by the named authority. The optional `src:<did-uri>` component identifies the reputation authority that issued the score. If `src` is absent, the score is self-asserted.

**Score semantics:**

| Score range | Interpretation                                                    |
|-------------|-------------------------------------------------------------------|
| 0.9 – 1.0   | High trust. Strong history of correct, reliable behavior.         |
| 0.7 – 0.9   | Good standing. Suitable for most production tasks.                |
| 0.5 – 0.7   | Provisional. New or infrequently observed agent.                  |
| 0.3 – 0.5   | Caution. Past errors or anomalies on record.                      |
| 0.0 – 0.3   | Low trust. Significant reliability or integrity concerns.         |

Reputation scores are advisory. Receiving agents determine their own thresholds. The values above are guidance, not normative.

**Verifying the score:** A receiving agent that cares about the source SHOULD:
1. Extract `src:<did-uri>` from the `@rep` value.
2. Check whether that DID is in its configured set of trusted reputation authorities.
3. If trusted: accept the score.
4. If untrusted or absent: treat the score as advisory and weight it accordingly.

The score itself is not signed by the issuing authority within the `@rep` field — it relies on the `@did` signature covering the full message header, which includes the `@rep` value. This means a valid `@did` signature prevents tampering with the score after the fact, but does not prove the authority actually issued it. For stronger guarantees, implementations SHOULD resolve the authority's own CAPABILITY_DECL (which carries their `@did`) and verify separately.

**Example:**
```
@rep: 0.91 src:did:web:reputation.koine-protocol.org
```

#### 5.5.3 Behavior Under Varied Identity States

Receiving agents SHOULD apply the following defaults. These are recommendations, not hard requirements — agents in closed, trusted networks MAY relax them.

| `@did` present | `@did` verifies | `@rep` | Recommended behavior |
|:-:|:-:|---|---|
| Yes | Yes | ≥ 0.7 | Proceed normally. |
| Yes | Yes | 0.5 – 0.7 | Proceed with caution. Log the exchange. Do not execute high-privilege actions without additional confirmation. |
| Yes | Yes | < 0.5 | Decline high-privilege requests. SHOULD emit UNCERTAINTY `kind: low_confidence` with description noting reputation. MAY proceed for low-stakes intents. |
| Yes | Yes | absent | Proceed at medium trust. Identity confirmed; reputation unknown. Treat as provisional. |
| Yes | No (resolution timeout/unavailable) | any | Treat as anonymous per §5.5.3 defaults. Local policy MAY reject. MUST NOT hard-reject solely due to resolver unavailability. |
| Yes | No (signature invalid) | any | MUST emit RESULT `status: failed`, `error_code: E_IDENTITY_UNVERIFIABLE`. Do not proceed. |
| No | — | any | Treat as anonymous. SHOULD reject privileged requests. MAY proceed for open, low-stakes tasks (e.g., capability discovery). |

**High-privilege actions** (examples requiring `@did` verification and `@rep ≥ 0.7` by convention):
- Writing to external systems
- Calling external APIs on behalf of the requester
- Executing multi-organization HANDOFF chains
- Any TASK_REQUEST where `budget.max_cost_usd` is non-trivial

**Low-stakes actions** (examples where anonymous messages are acceptable):
- Capability discovery (CAPABILITY_DECL broadcast)
- Read-only summarization or classification within a closed network
- EXTENSION_PROPOSAL broadcast

#### 5.5.4 Identity in Multi-Hop Chains

When a HANDOFF crosses an organizational boundary, the receiving agent SHOULD verify the `@did` on the HANDOFF message itself, not just on the originating TASK_REQUEST. Each agent in the `trust_chain` is responsible for its own identity attestation on the messages it emits.

The `@trace` meta field records routing history by agent ID. The `@did` field attests who that agent actually is. Together they provide an auditable chain: `@trace` shows the path, `@did` signatures on each hop message prove each agent was who it claimed to be.

---

## 6. Extension Mechanism

### 6.1 Extension Lifecycle

```
PROPOSED → ADOPTED → RATIFIED → CORE
           (3+ impls)  (threshold met)  (next major version)
```

1. **PROPOSED**: An agent emits an EXTENSION_PROPOSAL. The extension is identified by `EXT/<name>` in the message type field.
2. **ADOPTED**: Other agents begin emitting messages of type `EXT/<name>`. Each implementation that emits an extension message is an adoption event.
3. **RATIFIED**: When `adoption_threshold` independent `@from` values have emitted `EXT/<name>` messages, the extension is ratified. Ratification is automatic and data-driven — it requires no human vote.
4. **CORE**: Ratified extensions are candidates for inclusion in the next major protocol version. Inclusion is decided by the protocol maintainers and reflected in a new version header.

### 6.2 Extension Naming

- Extension names MUST be SCREAMING_SNAKE_CASE.
- Extension message types are addressed as `EXT/<name>` in the header line.
- Extension fields added to existing message types are prefixed with `x_<name>_` (lowercase).
- Example: an extension named `AUDIT` adds fields like `x_audit_hash`, `x_audit_signature`.

### 6.3 Handling Unknown Extensions

- Parsers MUST NOT reject messages with unknown `EXT/` type headers.
- Parsers MUST surface the raw message as an opaque object with all fields preserved.
- Agents SHOULD forward unknown extension messages if they are part of a routing chain.
- Agents MUST NOT act on unknown extension messages — they may log or discard them.

### 6.4 Extension Registry

Ratified extensions are tracked in `extensions/REGISTRY.md` in the canonical repository. The registry contains, for each ratified extension:
- The original EXTENSION_PROPOSAL `@id`
- Ratification date
- List of adopting agents (anonymized or named, at implementer discretion)
- Full spec, normalized to match this document's notation

---

## 7. Versioning

### 7.1 Protocol Version

The KOINE protocol uses a two-component version `MAJOR.MINOR` in the header line.

- **MINOR** increments: new optional fields, new standard error codes, new uncertainty kinds. Backwards compatible. Older parsers MUST NOT fail on messages with a higher minor version.
- **MAJOR** increments: changed required fields, removed fields, changed semantics of existing fields, promotion of adopted extensions to core. NOT backwards compatible across major versions.

### 7.2 Version Negotiation

Agents SHOULD include their supported KOINE version range in CAPABILITY_DECL using an extension field `x_koine_versions` (a list of `MAJOR.MINOR` values or ranges). Until this field is ratified as core, it is an informal convention.

### 7.3 Forwards Compatibility Rules

Parsers implementing KOINE `M.N` encountering a message with version `M.N+k`:
- MUST parse all known fields normally.
- MUST preserve unknown `@`-prefixed meta fields.
- MUST preserve unknown semantic fields.
- MUST NOT fail validation due to unrecognized fields alone.

Parsers implementing KOINE `M.N` encountering a message with version `M+1.N`:
- SHOULD emit a warning.
- SHOULD return the message as partially parsed with a `version_mismatch` flag.
- MUST NOT silently act on the message as if it were a lower version.

---

## 8. Encoding and Transport

### 8.1 Character Encoding

KOINE messages MUST be encoded as UTF-8. Line endings MUST be LF (`\n`). CR+LF (`\r\n`) MUST be normalized to LF by parsers.

### 8.2 Message Boundaries

When multiple KOINE messages are transmitted in a single stream or file, they MUST be separated by a line containing exactly `===` (three equals signs). This is the message boundary sentinel.

```
KOINE/1.0 TASK_REQUEST
...
===
KOINE/1.0 RESULT
...
```

### 8.3 Maximum Message Size

There is no protocol-specified maximum message size. Agents MAY impose their own limits and communicate them via `max_input_tokens` in CAPABILITY_DECL.

### 8.4 Transport Independence

KOINE messages are transport-agnostic. They MAY be carried over:
- MCP tool calls (message as a string argument)
- A2A message bodies
- HTTP request/response bodies (`Content-Type: text/koine`)
- WebSocket frames
- Files on a shared filesystem

---

## 9. Deterministic Rendering Reference

This section defines the normative English rendering for each message type. Implementations MUST produce output matching this structure. Fields in square brackets are omitted if not present in the message.

### 9.1 TASK_REQUEST

```
[Priority: <priority>.] Agent <@from> requests that agent <@to> <intent>.
Input: <input>
[Output format requested: <output_format>.]
[Constraints: <constraints>.]
[Budget: <budget>.]
[Context reference: <context_ref>.]
[Message expires in <ttl> seconds.]
```

### 9.2 CAPABILITY_DECL

```
<name> (v<version>, agent ID: <@from>) declares capabilities[, broadcasting to all listeners | to <@to>]:
  Intents handled: <intents (comma-separated)>
  Input types accepted: <input_types (comma-separated)>
  Output types produced: <output_types (comma-separated)>
[  Estimated cost: <cost_hint> tokens per request.]
[  Estimated latency: <latency_hint> ms per request.]
[  Maximum input size: <max_input_tokens> tokens.]
[  Authentication required: <auth_required>.]
[  Scope: <scope>.]
[  Languages: <languages (comma-separated)>.]
[  <description>]
```

### 9.3 RESULT

For `status: ok`:
```
Agent <@from> successfully completed task <@reply-to>[, requested by <@to>].
Output: <output>
[Confidence: <confidence>.]
[Tokens used: <tokens_used>. Latency: <latency_ms>ms.]
[Metadata: <meta>.]
```

For `status: partial`:
```
Agent <@from> partially completed task <@reply-to>[, requested by <@to>].
Partial output: <output>
[Confidence in partial output: <confidence>.]
[Tokens used so far: <tokens_used>.]
```

For `status: failed`:
```
Agent <@from> failed to complete task <@reply-to>[, requested by <@to>].
Error: <error_code>[: <error_detail>]
```

### 9.4 HANDOFF

```
Agent <@from> is handing off task <@reply-to> to agent <target>.
Reason for handoff: <reason>
[Agents who have handled this task: <trust_chain (arrow-separated)>.]
[Work completed so far:
<partial_result>]
[Context for <target>: <context>]
[Additional instructions: <instructions>]
[Priority: <priority>.]
```

### 9.5 UNCERTAINTY

```
Agent <@from> reports uncertainty on task <@reply-to> (confidence: <confidence>).
Type: <kind>
<description>
[To resolve, the agent needs: <clarification_needed>]
[Possible interpretations:
<alternatives>]
[Partial output produced:
<partial_result>]
[The agent will proceed despite uncertainty: <can_proceed>.]
```

### 9.6 EXTENSION_PROPOSAL

```
Agent <@from> proposes a new KOINE <kind>: <name>.
[Extends: <target_type>.]
Rationale: <rationale>
Proposed specification:
<spec>
Example:
<examples>
[Ratification threshold: <adoption_threshold> independent implementations.]
[Supersedes proposal: <supersedes>.]
[Incompatible with: <incompatible_with (comma-separated)>.]
```

---

## 10. Formal Grammar Summary

```ebnf
message         ::= header-line {meta-field} separator {semantic-field}
header-line     ::= "KOINE/" major "." minor " " msg-type "\n"
major           ::= digit+
minor           ::= digit+
msg-type        ::= "TASK_REQUEST" | "CAPABILITY_DECL" | "RESULT"
                  | "HANDOFF" | "UNCERTAINTY" | "EXTENSION_PROPOSAL"
                  | "EXT/" ext-name
ext-name        ::= upper-alpha {upper-alpha | "_"}
meta-field      ::= "@" meta-key ": " meta-value "\n"
meta-key        ::= alpha {alpha | digit | "-"}
meta-value      ::= id | int | list | did-sig | rep-value | str-value
did-sig         ::= did-uri " sig:" base64url
did-uri         ::= "did:" did-method ":" did-method-specific-id
did-method      ::= lower-alpha {lower-alpha | digit}
did-method-specific-id ::= (unreserved | pct-encoded | ":")+
rep-value       ::= prob [" src:" did-uri]
base64url       ::= {base64url-char}   (* base64url without padding *)
separator       ::= "---\n"
semantic-field  ::= field-key ": " inline-value "\n"
                  | field-key ": " block-value
field-key       ::= lower-alpha {lower-alpha | digit | "_"}
inline-value    ::= str-value | int-value | float-value | bool-value
                  | list-value | kv-value
block-value     ::= "<<<" delimiter "\n" {line "\n"} delimiter "\n"
delimiter       ::= upper-alpha {upper-alpha | "_"}
list-value      ::= inline-value {"," inline-value}
kv-value        ::= kv-pair {"," kv-pair}
kv-pair         ::= field-key "=" inline-value
bool-value      ::= "true" | "false"
int-value       ::= ["-"] digit+
float-value     ::= ["-"] digit+ "." digit+
str-value       ::= utf8-char+   (* no unescaped newlines *)
```

---

## 11. Examples

### 11.1 Complete Two-Agent Pipeline

```
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
```

---

## 12. Conformance

An implementation is KOINE-conformant if it:

1. Correctly parses all six core message types.
2. Accepts unknown fields without failure.
3. Rejects messages with missing required fields, returning a structured error.
4. Rejects messages with a higher major version number.
5. Accepts messages with a higher minor version number.
6. Produces human-readable renderings matching the normative templates in §9.
7. Correctly handles block values with arbitrary delimiters.
8. Correctly handles multi-message streams separated by `===`.

A parser is KOINE-strict if it additionally:

9. Validates field types (int, float, bool, list, kv, prob).
10. Validates enumerated field values (status, priority, scope, uncertainty kind).
11. Validates that `@reply-to` is present when required.
12. Detects routing loops in `trust_chain`.

---

## Appendix A: Design Rationale

**Why not JSON?** JSON keys are verbose. A single TASK_REQUEST in JSON costs 40–60% more tokens than the equivalent KOINE message. For pipelines with dozens of agent hops, this accumulates into significant cost and latency.

**Why not natural language?** Natural language is non-deterministic. Two agents asked to "please summarize this document and make it concise" may interpret "concise" differently. KOINE fields are machine-typed and explicitly validated.

**Why tagged blocks instead of YAML or TOML?** YAML is whitespace-sensitive and has a notoriously complex spec. TOML requires section headers. KOINE's format is intentionally minimal — it requires no external parser library and can be implemented in under 200 lines in any language.

**Why `cost_hint` and `latency_hint` instead of SLAs?** Hints are non-binding and honest. An SLA implies enforcement; a hint informs routing. Agents that cannot honor a hint should emit UNCERTAINTY with `kind: resource_limit`.

**Why data-driven extension ratification?** Human governance creates bottlenecks and political friction. If three independent implementations find an extension useful enough to ship, it is useful. The spec does not need a committee to ratify what the market has already decided.

---

## Appendix B: Token Efficiency Comparison

Equivalent TASK_REQUEST messages:

**JSON (verbose, typical agent pipeline):**
```json
{
  "message_type": "task_request",
  "message_id": "tr-9f2a1c",
  "sender_agent_id": "orchestrator-1",
  "recipient_agent_id": "summarizer-3",
  "timestamp_unix": 1712534400,
  "time_to_live_seconds": 60,
  "task": {
    "intent": "summarize",
    "input_content": "The Board of Directors met on March 15th...",
    "output_format": "plain",
    "operational_constraints": {
      "max_tokens": 80,
      "style": "executive"
    },
    "priority_level": "high"
  }
}
```
~110 tokens (GPT-4 tokenizer)

**KOINE:**
```
KOINE/1.0 TASK_REQUEST
@id: tr-9f2a1c
@from: orchestrator-1
@to: summarizer-3
@ts: 1712534400
@ttl: 60
---
intent: summarize
input: The Board of Directors met on March 15th...
output_format: plain
constraints: max_tokens=80,style=executive
priority: high
```
~65 tokens (GPT-4 tokenizer)

**Savings: ~41%**

---

*End of KOINE/1.0 Specification*
