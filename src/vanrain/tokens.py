"""Token counting: an estimator now, a real tokenizer later (milestone 4)."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token count: about four characters per token, at least one."""
    return max(1, (len(text) + 3) // 4)
