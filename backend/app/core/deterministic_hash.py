"""Deterministic stable hash — SHA-256-based, cross-process consistent.

Replaces Python's built-in hash() which is salted per process (PYTHONHASHSEED).
Used for section sampling decisions in llm_engine and semantic_chunking so the
same document produces identical sampling decisions across runs.
"""

import hashlib


def stable_hash_int(name: str) -> int:
    """Deterministic integer hash from a string, stable across processes.

    Uses SHA-256 over UTF-8 bytes, then extracts the first 31 bits.
    This is cross-PYTHONHASHSEED consistent.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def stable_hash_hex(data: bytes) -> str:
    """SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()
