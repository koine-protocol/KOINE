"""
KOINE identity — DID verification for @did fields (§5.5.1).

Implements did:key resolution (REQUIRED per spec) and Ed25519 signature
verification.  Requires the 'cryptography' package for actual verification;
falls back gracefully if unavailable.

This module is NOT called by the parser or validator — identity verification
is a runtime behaviour (§5.5.3), not a parsing concern.  Call
verify_did_signature() from agent runtime code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .models import KoineMessage, ParsedDid


# ---------------------------------------------------------------------------
# Base58btc decoder (needed for did:key without any dependencies)
# ---------------------------------------------------------------------------

_BASE58_ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _base58_decode(s: str) -> bytes:
    """Decode a base58btc string to bytes."""
    n = 0
    for char in s.encode('ascii'):
        idx = _BASE58_ALPHABET.find(bytes([char]))
        if idx < 0:
            raise ValueError(f"Invalid base58 character: {chr(char)!r}")
        n = n * 58 + idx
    result = n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
    # Preserve leading zero bytes encoded as '1'
    pad = len(s) - len(s.lstrip('1'))
    return b'\x00' * pad + result


# ---------------------------------------------------------------------------
# did:key resolver
# ---------------------------------------------------------------------------

# Ed25519 multicodec prefix: 0xed01
_ED25519_MULTICODEC = bytes([0xed, 0x01])


def _resolve_did_key(did_uri: str) -> Optional[bytes]:
    """
    Resolve a did:key URI to a 32-byte Ed25519 public key.

    Returns None if the DID is not a did:key, not Ed25519, or malformed.
    No network access — did:key is self-describing.
    """
    prefix = 'did:key:z'           # 'z' = base58btc multibase prefix
    if not did_uri.startswith(prefix):
        return None
    encoded = did_uri[len(prefix):]
    try:
        decoded = _base58_decode(encoded)
    except (ValueError, Exception):
        return None
    if len(decoded) < 34 or decoded[:2] != _ED25519_MULTICODEC:
        return None
    return decoded[2:]             # 32-byte public key


# ---------------------------------------------------------------------------
# Canonical signing input
# ---------------------------------------------------------------------------

def canonical_signing_input(msg: KoineMessage) -> bytes:
    """
    Build the canonical signing input for a message's @did signature (§5.5.1).

    Input = header line + all @meta fields in document order,
    excluding @did and @rep.
    """
    parts = [f"KOINE/{msg.version[0]}.{msg.version[1]} {msg.msg_type}\n"]
    for key, raw_value in msg.raw_meta:
        if key not in ('did', 'rep'):
            parts.append(f"@{key}: {raw_value}\n")
    return ''.join(parts).encode('utf-8')


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    verified: bool
    method: Optional[str]    = None   # e.g. "did:key Ed25519"
    reason: str              = ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def verify_did_signature(msg: KoineMessage) -> VerificationResult:
    """
    Attempt to verify the @did signature on a parsed message.

    Resolution timeout enforcement (§5.5.1) is the caller's responsibility
    (wrap in threading.Timer or asyncio.wait_for for production use).

    Returns a VerificationResult with .verified and a human-readable .reason.
    """
    did: Optional[ParsedDid] = msg.meta.did

    if did is None:
        return VerificationResult(verified=False, reason="No @did field present")

    # -----------------------------------------------------------------------
    # did:key — self-contained, no network needed
    # -----------------------------------------------------------------------
    if did.uri.startswith('did:key:'):
        pubkey_bytes = _resolve_did_key(did.uri)
        if pubkey_bytes is None:
            return VerificationResult(
                verified=False,
                reason=f"did:key resolution failed: unsupported key type or malformed URI",
            )

        signing_input = canonical_signing_input(msg)

        import base64
        try:
            sig_bytes = base64.urlsafe_b64decode(did.signature + '==')
        except Exception as exc:
            return VerificationResult(
                verified=False,
                reason=f"Signature is not valid base64url: {exc}",
            )

        # Try cryptography library first, then PyNaCl
        result = _verify_ed25519_cryptography(pubkey_bytes, sig_bytes, signing_input)
        if result is not None:
            return result

        result = _verify_ed25519_nacl(pubkey_bytes, sig_bytes, signing_input)
        if result is not None:
            return result

        return VerificationResult(
            verified=False,
            method="did:key Ed25519",
            reason=(
                "No Ed25519 verification library available. "
                "Install 'cryptography' or 'PyNaCl' to enable signature verification. "
                "Parsed fields are structurally valid."
            ),
        )

    # -----------------------------------------------------------------------
    # Other DID methods — require network resolution
    # -----------------------------------------------------------------------
    return VerificationResult(
        verified=False,
        reason=(
            f"DID method '{did.uri.split(':')[1]}' requires network resolution "
            "(did:web, did:ion, did:peer). "
            "Implement a resolver and call it before invoking this function."
        ),
    )


def _verify_ed25519_cryptography(
    pubkey: bytes, sig: bytes, msg_bytes: bytes
) -> Optional[VerificationResult]:
    """Attempt verification via the 'cryptography' package."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return None

    try:
        key = Ed25519PublicKey.from_public_bytes(pubkey)
        key.verify(sig, msg_bytes)
        return VerificationResult(
            verified=True,
            method="did:key Ed25519 (cryptography)",
            reason="Signature verified successfully.",
        )
    except InvalidSignature:
        return VerificationResult(
            verified=False,
            method="did:key Ed25519 (cryptography)",
            reason="Signature is invalid: does not match the public key.",
        )
    except Exception as exc:
        return VerificationResult(
            verified=False,
            method="did:key Ed25519 (cryptography)",
            reason=f"Verification error: {exc}",
        )


def _verify_ed25519_nacl(
    pubkey: bytes, sig: bytes, msg_bytes: bytes
) -> Optional[VerificationResult]:
    """Attempt verification via PyNaCl."""
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except ImportError:
        return None

    try:
        vk = VerifyKey(pubkey)
        vk.verify(msg_bytes, sig)
        return VerificationResult(
            verified=True,
            method="did:key Ed25519 (PyNaCl)",
            reason="Signature verified successfully.",
        )
    except BadSignatureError:
        return VerificationResult(
            verified=False,
            method="did:key Ed25519 (PyNaCl)",
            reason="Signature is invalid: does not match the public key.",
        )
    except Exception as exc:
        return VerificationResult(
            verified=False,
            method="did:key Ed25519 (PyNaCl)",
            reason=f"Verification error: {exc}",
        )
