"""What an issue mentions: code identifiers and file paths.

Both Vanrain and Aider get the *same* mentions from this module, so neither
condition is helped by a better issue parser than the other (DESIGN.md, 2).

- Vanrain resolves identifiers to symbols with ``vanrain.api.find_symbols``.
- Aider's repo map takes them as ``mentioned_idents`` and the paths as
  ``mentioned_fnames``.

Deliberately simple and deterministic: no LLM, no access to the gold patch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Traceback frame: File "path/to/x.py", line 12, in func_name
_FRAME = re.compile(r'File "([^"]+\.py)", line (\d+), in ([A-Za-z_]\w*)')
# Inline code `like_this` or `Foo.bar()`
_BACKTICK = re.compile(r"`([^`\n]{1,120})`")
# Dotted names: a.b.c (at least one dot), optionally called
_DOTTED = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
# Words that look like code: snake_case with an underscore, or CamelCase
_CODEY = re.compile(r"\b([a-z_]+_[a-z0-9_]+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+)\b")
_PATH = re.compile(r"\b((?:[\w.-]+/)*[\w.-]+\.py)\b")
_IDENT = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")

# Common words that match the patterns but are almost never the target.
_STOP = {
    "self", "cls", "none", "true", "false", "print", "len", "str", "int", "list",
    "dict", "set", "type", "object", "return", "import", "from", "def", "class",
    "python", "pip", "e.g", "i.e", "github.com", "http", "https", "www",
}


@dataclass(frozen=True)
class Mentions:
    identifiers: tuple[str, ...]  # most specific first, no repeats
    paths: tuple[str, ...]


def _add(out: dict[str, None], name: str) -> None:
    name = name.strip().rstrip("()").strip(".")
    if not name or name.lower() in _STOP or len(name) < 3:
        return
    if not _IDENT.fullmatch(name):
        return
    out.setdefault(name)


def extract(text: str, limit: int = 20) -> Mentions:
    """Identifiers and ``.py`` paths named in ``text``, in priority order.

    Order: traceback functions (innermost first), backticked code, dotted
    names, then code-looking words. Capped at ``limit`` identifiers.
    """
    idents: dict[str, None] = {}
    paths: dict[str, None] = {}

    frames = _FRAME.findall(text)
    for path, _line, func in reversed(frames):  # innermost frame last in a traceback
        if func != "<module>":
            _add(idents, func)
        paths.setdefault(path.replace("\\", "/"))

    for code in _BACKTICK.findall(text):
        head = re.split(r"[\s(\[=,]", code.strip(), maxsplit=1)[0]
        _add(idents, head)
    for name in _DOTTED.findall(text):
        if not name.endswith(".py") and not re.search(r"\.(com|org|io|html?)$", name):
            _add(idents, name)
    for name in _CODEY.findall(text):
        _add(idents, name)
    for p in _PATH.findall(text):
        paths.setdefault(p)

    return Mentions(tuple(list(idents)[:limit]), tuple(paths))


def resolve_vanrain_seeds(graph, mentions: Mentions, max_seeds: int = 5,
                          max_candidates: int = 3) -> list[str]:
    """Symbol ids for the first mentions that name few enough symbols.

    A mention matching more than ``max_candidates`` symbols (``get``, ``run``)
    is skipped as too vague; one matching 2..``max_candidates`` contributes all
    of them. Stops at ``max_seeds``.
    """
    from vanrain import api

    seeds: dict[str, None] = {}
    for name in mentions.identifiers:
        found = [s.id for s in api.find_symbols(graph, name)]
        if not found and "." in name:  # "pkg.mod.Class.meth" vs ids without the pkg
            found = [s.id for s in api.find_symbols(graph, name.split(".", 1)[1])]
        if 0 < len(found) <= max_candidates:
            for sid in found:
                seeds.setdefault(sid)
        if len(seeds) >= max_seeds:
            break
    return list(seeds)[:max_seeds]
