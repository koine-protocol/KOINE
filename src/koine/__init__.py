"""
KOINE reference implementation — Python parser, validator, and renderer.

Quick start:
    from koine import parse_message, validate, render

    result = parse_message(text)
    if isinstance(result, ParseError):
        print("Parse failed:", result.message)
    else:
        vr = validate(result)
        if vr.valid:
            print(render(result))
"""
from .parser    import parse_message, split_stream
from .validator import validate
from .renderer  import render
from .models    import (
    KoineMessage, MetaFields, ParsedDid, ParsedRep,
    ParseError, ValidationResult, ValidationError,
    IMPL_VERSION,
)

__version__ = "1.0.0"
__all__ = [
    "parse_message", "split_stream",
    "validate",
    "render",
    "KoineMessage", "MetaFields", "ParsedDid", "ParsedRep",
    "ParseError", "ValidationResult", "ValidationError",
    "IMPL_VERSION",
]
