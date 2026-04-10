"""
KOINE renderer — KoineMessage → human-readable English.

Implements the normative rendering templates from §9 of the spec.
All optional fields are omitted when absent.
"""
from __future__ import annotations

from .models import KoineMessage


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _kv_display(s: str) -> str:
    """'k=v,k2=v2' → 'k=v, k2=v2' (add space after commas for readability)."""
    return ', '.join(s.split(','))


def _list_display(s: str) -> str:
    """'a,b,c' → 'a, b, c'."""
    return ', '.join(x.strip() for x in s.split(','))


def _arrow_display(s: str) -> str:
    """'a,b,c' → 'a → b → c' (for trust_chain per §9.4)."""
    return ' → '.join(x.strip() for x in s.split(','))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render(msg: KoineMessage) -> str:
    """
    Render a KoineMessage to normative English (§9).

    Returns a plain-text string.  Raises no exceptions — unknown message
    types produce a best-effort generic rendering.
    """
    _dispatch = {
        'TASK_REQUEST':       _render_task_request,
        'CAPABILITY_DECL':    _render_capability_decl,
        'RESULT':             _render_result,
        'HANDOFF':            _render_handoff,
        'UNCERTAINTY':        _render_uncertainty,
        'EXTENSION_PROPOSAL': _render_extension_proposal,
    }
    fn = _dispatch.get(msg.msg_type)
    if fn:
        return fn(msg)
    if msg.msg_type.startswith('EXT/'):
        return _render_extension(msg)
    return f"[Unrenderable message type: {msg.msg_type}]"


# ---------------------------------------------------------------------------
# §9.1  TASK_REQUEST
# ---------------------------------------------------------------------------

def _render_task_request(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    priority_pfx = f"[Priority: {f['priority']}.] " if 'priority' in f else ''
    lines = [
        f"{priority_pfx}Agent {m.from_} requests that agent {m.to} "
        f"{f.get('intent', '(missing)')}.",
        f"Input: {f.get('input', '')}",
    ]
    if 'output_format' in f:
        lines.append(f"Output format requested: {f['output_format']}.")
    if 'constraints' in f:
        lines.append(f"Constraints: {_kv_display(f['constraints'])}.")
    if 'budget' in f:
        lines.append(f"Budget: {_kv_display(f['budget'])}.")
    if 'context_ref' in f:
        lines.append(f"Context reference: {f['context_ref']}.")
    if m.ttl is not None:
        lines.append(f"Message expires in {m.ttl} seconds.")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# §9.2  CAPABILITY_DECL
# ---------------------------------------------------------------------------

def _render_capability_decl(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    if m.to == 'broadcast':
        to_clause = ", broadcasting to all listeners"
    elif m.to:
        to_clause = f" to {m.to}"
    else:
        to_clause = ""

    name    = f.get('name', m.from_)
    version = f.get('version', '?')
    lines = [
        f"{name} (v{version}, agent ID: {m.from_}) declares capabilities{to_clause}:",
        f"  Intents handled: {_list_display(f.get('intents', ''))}",
        f"  Input types accepted: {_list_display(f.get('input_types', ''))}",
        f"  Output types produced: {_list_display(f.get('output_types', ''))}",
    ]
    if 'cost_hint' in f:
        lines.append(f"  Estimated cost: {f['cost_hint']} tokens per request.")
    if 'latency_hint' in f:
        lines.append(f"  Estimated latency: {f['latency_hint']} ms per request.")
    if 'max_input_tokens' in f:
        lines.append(f"  Maximum input size: {f['max_input_tokens']} tokens.")
    if 'auth_required' in f:
        lines.append(f"  Authentication required: {f['auth_required']}.")
    if 'scope' in f:
        lines.append(f"  Scope: {f['scope']}.")
    if 'languages' in f:
        lines.append(f"  Languages: {_list_display(f['languages'])}.")
    if 'description' in f:
        lines.append(f"  {f['description']}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# §9.3  RESULT
# ---------------------------------------------------------------------------

def _render_result(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    status    = f.get('status', 'unknown')
    to_clause = f", requested by {m.to}" if m.to else ""

    if status == 'ok':
        lines = [
            f"Agent {m.from_} successfully completed task {m.reply_to}{to_clause}.",
            f"Output: {f.get('output', '')}",
        ]
        if 'confidence' in f:
            lines.append(f"Confidence: {f['confidence']}.")
        perf_parts = []
        if 'tokens_used' in f:
            perf_parts.append(f"Tokens used: {f['tokens_used']}.")
        if 'latency_ms' in f:
            perf_parts.append(f"Latency: {f['latency_ms']}ms.")
        if perf_parts:
            lines.append(' '.join(perf_parts))
        if 'meta' in f:
            lines.append(f"Metadata: {_kv_display(f['meta'])}.")

    elif status == 'partial':
        lines = [
            f"Agent {m.from_} partially completed task {m.reply_to}{to_clause}.",
            f"Partial output: {f.get('output', '')}",
        ]
        if 'confidence' in f:
            lines.append(f"Confidence in partial output: {f['confidence']}.")
        if 'tokens_used' in f:
            lines.append(f"Tokens used so far: {f['tokens_used']}.")

    else:  # failed (or unknown)
        err = f.get('error_code', 'UNKNOWN')
        if 'error_detail' in f:
            err = f"{err}: {f['error_detail']}"
        lines = [
            f"Agent {m.from_} failed to complete task {m.reply_to}{to_clause}.",
            f"Error: {err}",
        ]

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# §9.4  HANDOFF
# ---------------------------------------------------------------------------

def _render_handoff(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    target = f.get('target', '(missing)')
    lines = [
        f"Agent {m.from_} is handing off task {m.reply_to} to agent {target}.",
        f"Reason for handoff: {f.get('reason', '')}",
    ]
    if 'trust_chain' in f:
        lines.append(
            f"Agents who have handled this task: {_arrow_display(f['trust_chain'])}.")
    if 'partial_result' in f:
        lines.append(f"Work completed so far:\n{f['partial_result']}")
    if 'context' in f:
        lines.append(f"Context for {target}: {f['context']}")
    if 'instructions' in f:
        lines.append(f"Additional instructions: {f['instructions']}")
    if 'priority' in f:
        lines.append(f"Priority: {f['priority']}.")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# §9.5  UNCERTAINTY
# ---------------------------------------------------------------------------

def _render_uncertainty(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    lines = [
        f"Agent {m.from_} reports uncertainty on task {m.reply_to} "
        f"(confidence: {f.get('confidence', '?')}).",
        f"Type: {f.get('kind', '?')}",
        f"{f.get('description', '')}",
    ]
    if 'clarification_needed' in f:
        lines.append(f"To resolve, the agent needs: {f['clarification_needed']}")
    if 'alternatives' in f:
        lines.append(f"Possible interpretations:\n{f['alternatives']}")
    if 'partial_result' in f:
        lines.append(f"Partial output produced:\n{f['partial_result']}")
    if 'can_proceed' in f:
        lines.append(f"The agent will proceed despite uncertainty: {f['can_proceed']}.")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# §9.6  EXTENSION_PROPOSAL
# ---------------------------------------------------------------------------

def _render_extension_proposal(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    kind = f.get('kind', '?')
    name = f.get('name', '?')
    lines = [f"Agent {m.from_} proposes a new KOINE {kind}: {name}."]
    if 'target_type' in f:
        lines.append(f"Extends: {f['target_type']}.")
    lines.append(f"Rationale: {f.get('rationale', '')}")
    lines.append(f"Proposed specification:\n{f.get('spec', '')}")
    lines.append(f"Example:\n{f.get('examples', '')}")
    if 'adoption_threshold' in f:
        lines.append(
            f"Ratification threshold: {f['adoption_threshold']} independent implementations.")
    if 'supersedes' in f:
        lines.append(f"Supersedes proposal: {f['supersedes']}.")
    if 'incompatible_with' in f:
        lines.append(f"Incompatible with: {_list_display(f['incompatible_with'])}.")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Generic extension message rendering
# ---------------------------------------------------------------------------

def _render_extension(msg: KoineMessage) -> str:
    f, m = msg.fields, msg.meta
    to_part = f" to {m.to}" if m.to else ""
    lines = [f"Extension message {msg.msg_type} from agent {m.from_}{to_part}."]
    for k, v in f.items():
        # Indent multi-line values
        if '\n' in str(v):
            lines.append(f"  {k}:")
            for ln in str(v).split('\n'):
                lines.append(f"    {ln}")
        else:
            lines.append(f"  {k}: {v}")
    return '\n'.join(lines)
