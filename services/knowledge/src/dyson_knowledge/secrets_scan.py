"""Keep credentials out of the index.

Dumping "all my projects" risks ingesting API keys and tokens committed in code. The research is
clear: for true secrets prefer exclusion over masking (embeddings are invertible). So a document
that trips the credential patterns is quarantined at the ingest boundary, never embedded. This
reuses the same patterns as Dyson's outbound SecretGuard, so one definition governs both.
"""

from dyson_memory.secrets import SecretGuard, SecretLeak

_GUARD = SecretGuard(None)  # pattern-only; no store of known values needed at the ingest boundary


def has_secret(text: str) -> bool:
    """True if the text contains something shaped like a credential (and must not be indexed)."""
    try:
        _GUARD.check(text or "")
    except SecretLeak:
        return True
    return False
