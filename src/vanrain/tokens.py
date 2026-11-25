"""Token counting: an estimator now, a real tokenizer later.

Code that counts text at query time (the renderer) goes through
``count_tokens``, so a real tokenizer can replace the estimator in one place
with ``set_counter``. The selector never counts text itself: it spends
``Symbol.tokens_full`` and ``Symbol.tokens_sig``, which parsers fill in with
``estimate_tokens`` at index time. Moving those to a real tokenizer means
changing the parser and re-indexing (the cache fingerprint covers parser code).
"""

from __future__ import annotations

from collections.abc import Callable

TokenCounter = Callable[[str], int]


def estimate_tokens(text: str) -> int:
    """Rough token count: about four characters per token, at least one."""
    return max(1, (len(text) + 3) // 4)


_counter: TokenCounter = estimate_tokens


def count_tokens(text: str) -> int:
    """Count tokens with the current counter (the estimator by default)."""
    return _counter(text)


def set_counter(counter: TokenCounter | None) -> TokenCounter:
    """Use ``counter`` from now on (``None`` restores the estimator).

    Returns the previous counter so callers can put it back.
    """
    global _counter
    previous = _counter
    _counter = estimate_tokens if counter is None else counter
    return previous
