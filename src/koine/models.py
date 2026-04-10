"""
KOINE data model — dataclasses for parsed messages and results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants from the spec
# ---------------------------------------------------------------------------

IMPL_VERSION = (1, 0)

CORE_MSG_TYPES = frozenset({
    "TASK_REQUEST", "CAPABILITY_DECL", "RESULT",
    "HANDOFF", "UNCERTAINTY", "EXTENSION_PROPOSAL",
})

VALID_PRIORITIES         = frozenset({"low", "normal", "high", "critical"})
VALID_SCOPES             = frozenset({"public", "private", "trusted"})
VALID_STATUSES           = frozenset({"ok", "partial", "failed"})
VALID_UNCERTAINTY_KINDS  = frozenset({
    "ambiguous_intent", "missing_input", "input_ambiguous", "out_of_scope",
    "low_confidence", "resource_limit", "routing_loop", "conflicting_constraints",
})
VALID_EXTENSION_KINDS    = frozenset({"message_type", "field"})

# Message types that require @to and @reply-to
TO_REQUIRED       = frozenset({"TASK_REQUEST", "RESULT", "HANDOFF", "UNCERTAINTY"})
REPLY_TO_REQUIRED = frozenset({"RESULT", "HANDOFF", "UNCERTAINTY"})

# Known semantic fields per message type
KNOWN_FIELDS: Dict[str, frozenset] = {
    "TASK_REQUEST": frozenset({
        "intent", "input", "output_format", "constraints",
        "priority", "context_ref", "budget",
    }),
    "CAPABILITY_DECL": frozenset({
        "name", "version", "intents", "input_types", "output_types",
        "cost_hint", "latency_hint", "constraints_accepted", "auth_required",
        "scope", "max_input_tokens", "languages", "description",
    }),
    "RESULT": frozenset({
        "status", "output", "confidence", "tokens_used",
        "latency_ms", "error_code", "error_detail", "meta",
    }),
    "HANDOFF": frozenset({
        "reason", "target", "context", "partial_result",
        "trust_chain", "priority", "instructions",
    }),
    "UNCERTAINTY": frozenset({
        "kind", "description", "confidence", "clarification_needed",
        "partial_result", "alternatives", "can_proceed",
    }),
    "EXTENSION_PROPOSAL": frozenset({
        "name", "kind", "target_type", "rationale",
        "spec", "examples", "adoption_threshold", "supersedes", "incompatible_with",
    }),
}


# ---------------------------------------------------------------------------
# Parsed sub-types for identity fields
# ---------------------------------------------------------------------------

@dataclass
class ParsedDid:
    """Parsed @did field: a W3C DID URI plus a detached base64url signature."""
    uri: str
    signature: str   # base64url, no padding


@dataclass
class ParsedRep:
    """Parsed @rep field: a probability score plus an optional authority DID."""
    score: float
    src: Optional[str] = None   # DID URI of the issuing authority


# ---------------------------------------------------------------------------
# Core message model
# ---------------------------------------------------------------------------

@dataclass
class MetaFields:
    """Parsed @-prefixed meta fields."""
    id: str
    from_: str           # 'from' is a Python keyword
    ts: int
    to: Optional[str]       = None
    reply_to: Optional[str] = None
    ttl: Optional[int]      = None
    trace: Optional[List[str]] = None
    did: Optional[ParsedDid]   = None
    rep: Optional[ParsedRep]   = None
    unknown: Dict[str, str]    = field(default_factory=dict)


@dataclass
class KoineMessage:
    """A fully parsed KOINE message."""
    version: Tuple[int, int]    # (major, minor)
    msg_type: str               # e.g. "TASK_REQUEST" or "EXT/FEEDBACK"
    meta: MetaFields
    fields: Dict[str, Any]      # known semantic fields (str values, possibly multi-line)
    unknown_fields: Dict[str, Any] = field(default_factory=dict)   # preserved unknown fields
    raw_meta: List[Tuple[str, str]] = field(default_factory=list)  # (key, raw_str) in doc order


# ---------------------------------------------------------------------------
# Error / result types
# ---------------------------------------------------------------------------

@dataclass
class ParseError:
    """Returned instead of KoineMessage when parsing fails."""
    message: str
    line: Optional[int] = None


@dataclass
class ValidationError:
    field: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str]          = field(default_factory=list)
