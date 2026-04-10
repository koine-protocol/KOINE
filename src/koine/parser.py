"""
KOINE parser — text → KoineMessage or ParseError.

Implements the grammar from §3 and §10 of the spec.  Forwards-compatible:
unknown meta and semantic fields are preserved, not rejected.
"""
from __future__ import annotations

import re
from typing import List, Tuple, Union

from .models import (
    CORE_MSG_TYPES, IMPL_VERSION, KNOWN_FIELDS,
    KoineMessage, MetaFields, ParsedDid, ParsedRep, ParseError,
)

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_HEADER_RE    = re.compile(r'^KOINE/(\d+)\.(\d+) (.+)$')
_META_RE      = re.compile(r'^@([\w-]+): (.+)$')
_FIELD_RE     = re.compile(r'^([a-z][a-z0-9_]*): (.+)$')
_BLOCK_RE     = re.compile(r'^<<<([A-Z_]{1,32})$')

# §5.5.1: did-uri sig:base64url  (base64url = [A-Za-z0-9\-_] without padding)
_DID_SIG_RE   = re.compile(r'^(did:[a-z][a-z0-9]*:[^\s]+) sig:([A-Za-z0-9\-_]+)$')

# §5.5.2: <float>[ src:<did-uri>]
_REP_RE       = re.compile(r'^([0-9]+(?:\.[0-9]+)?)(?:\s+src:(did:[a-z][a-z0-9]*:[^\s]+))?$')

# Known meta keys; anything else is forwarded unchanged
_KNOWN_META = frozenset({'id', 'from', 'to', 'ts', 'reply-to', 'ttl', 'trace', 'did', 'rep'})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_stream(text: str) -> List[str]:
    """Split a multi-message stream on === boundaries (§8.2)."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    parts = re.split(r'\n===\n', text)
    return [p.strip('\n') for p in parts if p.strip()]


def _parse_did(raw: str) -> Union[ParsedDid, None]:
    m = _DID_SIG_RE.match(raw)
    if not m:
        return None
    return ParsedDid(uri=m.group(1), signature=m.group(2))


def _parse_rep(raw: str) -> Union[ParsedRep, None]:
    m = _REP_RE.match(raw)
    if not m:
        return None
    try:
        score = float(m.group(1))
    except ValueError:
        return None
    if not (0.0 <= score <= 1.0):
        return None
    return ParsedRep(score=score, src=m.group(2))  # group(2) is None if absent


def _coerce_meta(key: str, raw: str):
    """Coerce a meta value to its native type for known fields."""
    if key in ('ts', 'ttl'):
        try:
            return int(raw)
        except ValueError:
            return raw          # let validator catch it
    if key == 'trace':
        return [v.strip() for v in raw.split(',')]
    if key == 'did':
        return _parse_did(raw)
    if key == 'rep':
        return _parse_rep(raw)
    return raw                  # id, from, to, reply-to: plain strings


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_message(text: str) -> Union[KoineMessage, ParseError]:
    """
    Parse a single KOINE message.

    Returns a KoineMessage on success, or a ParseError describing the first
    structural problem encountered.  Does not perform semantic validation —
    call validator.validate() for that.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    lineno = 0  # 1-based for error messages

    # -----------------------------------------------------------------------
    # §3.1 Header line
    # -----------------------------------------------------------------------
    if not lines:
        return ParseError("Empty message", line=1)

    m = _HEADER_RE.match(lines[0])
    if not m:
        return ParseError(f"Invalid header line (expected 'KOINE/M.N TYPE'): {lines[0]!r}", line=1)

    major, minor, msg_type = int(m.group(1)), int(m.group(2)), m.group(3).strip()

    # Version check (§7.3)
    if major > IMPL_VERSION[0]:
        return ParseError(
            f"Unsupported major version {major} "
            f"(implementation supports {IMPL_VERSION[0]}.x)",
            line=1,
        )

    # Message type check
    is_ext = msg_type.startswith('EXT/')
    if msg_type not in CORE_MSG_TYPES and not is_ext:
        return ParseError(f"Unrecognised message type: {msg_type!r}", line=1)

    # -----------------------------------------------------------------------
    # §3.2 Meta fields
    # -----------------------------------------------------------------------
    meta_coerced: dict = {}
    meta_unknown: dict = {}
    raw_meta: List[Tuple[str, str]] = []   # (key, raw_value) in document order

    i = 1
    while i < len(lines):
        line = lines[i]
        i += 1

        if line == '---':
            break

        if not line:            # blank line between meta fields — skip
            continue

        mm = _META_RE.match(line)
        if not mm:
            return ParseError(
                f"Invalid meta field (expected '@key: value'): {line!r}",
                line=i,
            )

        key, raw_value = mm.group(1), mm.group(2)
        raw_meta.append((key, raw_value))

        if key in _KNOWN_META:
            meta_coerced[key] = _coerce_meta(key, raw_value)
        else:
            meta_unknown[key] = raw_value
    else:
        return ParseError("Missing '---' separator between meta and semantic sections")

    # Required meta fields (always: @id, @from, @ts)
    for req in ('id', 'from', 'ts'):
        if req not in meta_coerced:
            return ParseError(f"Missing required meta field: @{req}")

    meta = MetaFields(
        id       = meta_coerced['id'],
        from_    = meta_coerced['from'],
        ts       = meta_coerced['ts'],
        to       = meta_coerced.get('to'),
        reply_to = meta_coerced.get('reply-to'),
        ttl      = meta_coerced.get('ttl'),
        trace    = meta_coerced.get('trace'),
        did      = meta_coerced.get('did'),
        rep      = meta_coerced.get('rep'),
        unknown  = meta_unknown,
    )

    # -----------------------------------------------------------------------
    # §3.4 Semantic fields
    # -----------------------------------------------------------------------
    known_field_set = KNOWN_FIELDS.get(msg_type, frozenset())
    sem_fields: dict = {}
    unk_fields: dict = {}

    while i < len(lines):
        line = lines[i]
        i += 1

        if not line:
            continue

        fm = _FIELD_RE.match(line)
        if not fm:
            return ParseError(
                f"Invalid semantic field (expected 'key: value'): {line!r}",
                line=i,
            )

        key, raw_value = fm.group(1), fm.group(2)

        # Block value? (§2.1)
        bm = _BLOCK_RE.match(raw_value)
        if bm:
            delim = bm.group(1)
            block_lines: List[str] = []
            while i < len(lines):
                if lines[i] == delim:
                    i += 1      # consume the closing delimiter line
                    break
                block_lines.append(lines[i])
                i += 1
            else:
                return ParseError(
                    f"Unclosed block value for field {key!r}: "
                    f"closing delimiter {delim!r} not found"
                )
            value: str = '\n'.join(block_lines)
        else:
            value = raw_value

        # Route to known vs unknown fields
        if is_ext or key in known_field_set:
            sem_fields[key] = value
        else:
            unk_fields[key] = value

    return KoineMessage(
        version      = (major, minor),
        msg_type     = msg_type,
        meta         = meta,
        fields       = sem_fields,
        unknown_fields = unk_fields,
        raw_meta     = raw_meta,
    )
