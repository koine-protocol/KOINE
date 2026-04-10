"""
KOINE validator — KoineMessage → ValidationResult.

Implements KOINE-strict conformance (§12 items 9–12) plus all per-type
validation rules defined in §4.
"""
from __future__ import annotations

from typing import List

from .models import (
    KoineMessage, ValidationError, ValidationResult,
    VALID_PRIORITIES, VALID_SCOPES, VALID_STATUSES,
    VALID_UNCERTAINTY_KINDS, VALID_EXTENSION_KINDS,
    REPLY_TO_REQUIRED, TO_REQUIRED,
    IMPL_VERSION,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _e(fld: str, msg: str) -> ValidationError:
    return ValidationError(field=fld, message=msg)


def _is_prob(v: str) -> bool:
    try:
        f = float(v)
        return 0.0 <= f <= 1.0
    except (TypeError, ValueError):
        return False


def _is_positive_int(v: str) -> bool:
    try:
        return int(v) > 0
    except (TypeError, ValueError):
        return False


def _is_int(v: str) -> bool:
    try:
        int(v)
        return True
    except (TypeError, ValueError):
        return False


def _parse_kv(v: str) -> dict:
    out = {}
    for pair in v.split(','):
        k, sep, val = pair.partition('=')
        if sep:
            out[k.strip()] = val.strip()
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate(msg: KoineMessage) -> ValidationResult:
    """
    Validate a parsed KoineMessage.

    Returns a ValidationResult with .valid, .errors, and .warnings.
    Warnings do not affect validity.
    """
    errors: List[ValidationError] = []
    warnings: List[str] = []

    # Minor-version forward compat note (§7.3)
    if msg.version[1] > IMPL_VERSION[1]:
        warnings.append(
            f"Message is KOINE/{msg.version[0]}.{msg.version[1]}; "
            f"implementation knows {IMPL_VERSION[0]}.{IMPL_VERSION[1]}. "
            "Unknown fields preserved per §7.3."
        )

    mt = msg.msg_type

    # ------------------------------------------------------------------
    # Universal meta checks
    # ------------------------------------------------------------------

    if mt in TO_REQUIRED and msg.meta.to is None:
        errors.append(_e('@to', f'Required for {mt}'))

    if mt in REPLY_TO_REQUIRED and msg.meta.reply_to is None:
        errors.append(_e('@reply-to', f'Required for {mt}'))

    # Flag unparseable @did / @rep (parse failures produce None in parser)
    # We detect this by checking if the raw value was present but parsing failed.
    # The parser stores None on failure; we check the raw_meta list for presence.
    raw_meta_keys = {k for k, _ in msg.raw_meta}
    if 'did' in raw_meta_keys and msg.meta.did is None:
        errors.append(_e('@did', 'Value does not match did-sig format: <did-uri> sig:<base64url>'))
    if 'rep' in raw_meta_keys and msg.meta.rep is None:
        errors.append(_e('@rep', 'Value does not match rep-value format: <float> [src:<did-uri>]'))

    # ------------------------------------------------------------------
    # Per-type semantic validation
    # ------------------------------------------------------------------

    _VALIDATORS = {
        'TASK_REQUEST':       _validate_task_request,
        'CAPABILITY_DECL':    _validate_capability_decl,
        'RESULT':             _validate_result,
        'HANDOFF':            _validate_handoff,
        'UNCERTAINTY':        _validate_uncertainty,
        'EXTENSION_PROPOSAL': _validate_extension_proposal,
    }

    if mt in _VALIDATORS:
        _VALIDATORS[mt](msg, errors, warnings)
    elif mt.startswith('EXT/'):
        warnings.append(
            f"Extension message type {mt!r}; semantic field validation skipped. "
            "All fields preserved (§6.3)."
        )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# Per-type validators
# ---------------------------------------------------------------------------

def _validate_task_request(msg: KoineMessage,
                            errors: List[ValidationError],
                            warnings: List[str]) -> None:
    f = msg.fields
    if not f.get('intent', '').strip():
        errors.append(_e('intent', 'Required and must not be empty'))
    if not f.get('input', '').strip():
        errors.append(_e('input', 'Required and must not be empty'))
    if 'priority' in f and f['priority'] not in VALID_PRIORITIES:
        errors.append(_e('priority',
            f"Must be one of {sorted(VALID_PRIORITIES)}; got {f['priority']!r}"))
    if 'budget' in f:
        for k, v in _parse_kv(f['budget']).items():
            try:
                if float(v) <= 0:
                    errors.append(_e('budget',
                        f"Value for '{k}' must be positive; got {v!r}"))
            except ValueError:
                errors.append(_e('budget',
                    f"Value for '{k}' is not numeric: {v!r}"))


def _validate_capability_decl(msg: KoineMessage,
                               errors: List[ValidationError],
                               warnings: List[str]) -> None:
    f = msg.fields
    for req in ('name', 'version', 'intents', 'input_types', 'output_types'):
        if not f.get(req, '').strip():
            errors.append(_e(req, 'Required'))
    # intents must have at least one non-empty entry
    intents = [x.strip() for x in f.get('intents', '').split(',') if x.strip()]
    if not intents:
        errors.append(_e('intents', 'At least one intent is required'))
    for int_field in ('cost_hint', 'latency_hint', 'max_input_tokens'):
        if int_field in f and not _is_positive_int(f[int_field]):
            errors.append(_e(int_field,
                f"Must be a positive integer; got {f[int_field]!r}"))
    if 'scope' in f and f['scope'] not in VALID_SCOPES:
        errors.append(_e('scope',
            f"Must be one of {sorted(VALID_SCOPES)}; got {f['scope']!r}"))
    if 'auth_required' in f and f['auth_required'] not in ('true', 'false'):
        errors.append(_e('auth_required',
            f"Must be 'true' or 'false'; got {f['auth_required']!r}"))


def _validate_result(msg: KoineMessage,
                     errors: List[ValidationError],
                     warnings: List[str]) -> None:
    f = msg.fields
    status = f.get('status', '')
    if status not in VALID_STATUSES:
        errors.append(_e('status',
            f"Must be one of {sorted(VALID_STATUSES)}; got {status!r}"))
        return

    if status in ('ok', 'partial') and not f.get('output', '').strip():
        errors.append(_e('output', f"Required when status is {status!r}"))
    if status == 'failed' and not f.get('error_code', '').strip():
        errors.append(_e('error_code', "Required when status is 'failed'"))

    if 'confidence' in f and not _is_prob(f['confidence']):
        errors.append(_e('confidence',
            f"Must be a float in [0.0, 1.0]; got {f['confidence']!r}"))
    for int_field in ('tokens_used', 'latency_ms'):
        if int_field in f and not _is_int(f[int_field]):
            errors.append(_e(int_field,
                f"Must be an integer; got {f[int_field]!r}"))


def _validate_handoff(msg: KoineMessage,
                      errors: List[ValidationError],
                      warnings: List[str]) -> None:
    f = msg.fields
    if not f.get('reason', '').strip():
        errors.append(_e('reason', 'Required'))
    target = f.get('target', '').strip()
    if not target:
        errors.append(_e('target', 'Required'))
    elif target == msg.meta.from_:
        errors.append(_e('target', 'Must differ from @from (no self-handoff)'))
    if 'priority' in f and f['priority'] not in VALID_PRIORITIES:
        errors.append(_e('priority',
            f"Must be one of {sorted(VALID_PRIORITIES)}; got {f['priority']!r}"))
    # Loop detection (§4.4 / §12 item 12)
    if 'trust_chain' in f:
        chain = [x.strip() for x in f['trust_chain'].split(',')]
        if msg.meta.from_ in chain:
            warnings.append(
                f"Routing loop detected: @from={msg.meta.from_!r} "
                f"appears in trust_chain {chain!r}"
            )


def _validate_uncertainty(msg: KoineMessage,
                          errors: List[ValidationError],
                          warnings: List[str]) -> None:
    f = msg.fields
    kind = f.get('kind', '')
    if kind not in VALID_UNCERTAINTY_KINDS:
        errors.append(_e('kind',
            f"Must be one of {sorted(VALID_UNCERTAINTY_KINDS)}; got {kind!r}"))
    if not f.get('description', '').strip():
        errors.append(_e('description', 'Required'))
    confidence = f.get('confidence', '')
    if not confidence:
        errors.append(_e('confidence', 'Required'))
    elif not _is_prob(confidence):
        errors.append(_e('confidence',
            f"Must be a float in [0.0, 1.0]; got {confidence!r}"))
    if 'can_proceed' in f and f['can_proceed'] not in ('true', 'false'):
        errors.append(_e('can_proceed',
            f"Must be 'true' or 'false'; got {f['can_proceed']!r}"))


def _validate_extension_proposal(msg: KoineMessage,
                                  errors: List[ValidationError],
                                  warnings: List[str]) -> None:
    f = msg.fields
    if not f.get('name', '').strip():
        errors.append(_e('name', 'Required'))
    kind = f.get('kind', '')
    if kind not in VALID_EXTENSION_KINDS:
        errors.append(_e('kind',
            f"Must be one of {sorted(VALID_EXTENSION_KINDS)}; got {kind!r}"))
    if kind == 'field' and not f.get('target_type', '').strip():
        errors.append(_e('target_type', "Required when kind is 'field'"))
    for req in ('rationale', 'spec', 'examples'):
        if not f.get(req, '').strip():
            errors.append(_e(req, 'Required'))
    if 'adoption_threshold' in f and not _is_positive_int(f['adoption_threshold']):
        errors.append(_e('adoption_threshold',
            f"Must be a positive integer; got {f['adoption_threshold']!r}"))
