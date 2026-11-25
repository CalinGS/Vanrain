"""Start nodes from free text: an issue, a bug report, a task description.

``find_seeds`` (in ``seeds``) needs the exact name of a symbol. A task usually
names code loosely: ``xr.DataArray``, ``self._format_fields``, a traceback, a
config option such as ``autodoc_typehints``, or only plain words ("raise an
error when a blueprint name contains a dot"). ``seeds_from_text`` turns such
text into a short list of symbol ids, scoring candidates from three sources:

1. **Names that resolve.** Identifiers in the text (traceback frames first,
   then backticked code, dotted names, code-looking words) that match one to a
   few symbols. A dotted name whose head is not in the repo (``np.``, ``xr.``,
   ``self.``) is retried without it, when what is left is specific enough.
   Builtins, very common names and top-level package modules are skipped.
2. **Names that appear only in code.** Identifiers that are not symbols (config
   options, constants, attributes, string keys) are searched for as whole
   words in the source; the functions and classes containing them score, rarer
   words more.
3. **Plain words**, only when 1 and 2 find nothing: words of the text matched
   against the parts of symbol names (``Blueprint`` for "blueprint"), rarer
   parts more, the first line (an issue's title) counting double.

Test code (``tests/`` folders, ``test_*.py``, ``conftest.py``) scores less, as
a task's fix is normally in the code under test.
"""

from __future__ import annotations

import builtins
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from vanrain.graph import CodeGraph
from vanrain.model import NodeKind
from vanrain.seeds import find_seeds

# --- mentions -------------------------------------------------------------------

_FRAME = re.compile(r'File "([^"]+\.py)", line (\d+), in ([A-Za-z_]\w*)')
_BACKTICK = re.compile(r"`([^`\n]{1,120})`")
_DOTTED = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
_CODEY = re.compile(r"\b([a-z_]+_[a-z0-9_]+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|_[a-z]\w*)\b")
_OPTION = re.compile(r"(?<![\w/])--?([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
_PATH = re.compile(r"\b((?:[\w.-]+/)*[\w.-]+\.py)\b")
_IDENT = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_WORD = re.compile(r"[A-Za-z][a-z]{3,}")
_NAME_PART = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")

_STOP = {
    "self", "cls", "none", "true", "false", "return", "import", "from", "def", "class",
    "python", "pip", "github.com", "http", "https", "www", "e.g", "i.e",
}
#: Names too common to point anywhere when they stand alone.
COMMON = set(dir(builtins)) | {
    "get", "set", "run", "call", "load", "read", "write", "open", "close", "update",
    "data", "name", "value", "values", "items", "keys", "copy", "main", "test", "init",
    "parse", "compile", "format", "append", "add", "make", "new", "result", "results",
    "args", "kwargs", "config", "options", "path", "file", "text", "content", "next",
}
_ENGLISH = {
    "this", "that", "with", "when", "what", "which", "from", "have", "will", "would",
    "should", "could", "there", "their", "they", "then", "than", "into", "also", "only",
    "some", "more", "most", "like", "just", "does", "doesn", "dont", "isnt", "here",
    "were", "been", "being", "about", "after", "before", "because", "using", "used",
    "use", "work", "works", "working", "expected", "behavior", "behaviour", "actual",
    "issue", "error", "errors", "problem", "following", "example", "code", "version",
    "versions", "output", "input", "case", "cases", "need", "needs", "want", "make",
    "seems", "instead", "other", "same", "each", "every", "these", "those", "where",
    "while", "still", "even", "already", "currently", "think", "know", "thanks",
    "please", "maybe", "possible", "something", "anything", "nothing", "describe",
    "reproduce", "steps", "environment", "additional", "context", "system", "information",
    "python", "file", "files", "line", "lines", "test", "tests", "call", "calls",
}


@dataclass(frozen=True)
class Mentions:
    identifiers: tuple[str, ...]  # most specific first, no repeats
    paths: tuple[str, ...]  # .py paths named in the text
    words: tuple[str, ...]  # plain lower-case words, title first


def _keep(out: dict[str, None], name: str) -> None:
    name = name.strip().rstrip("()").strip(".")
    if len(name) < 3 or name.lower() in _STOP or not _IDENT.fullmatch(name):
        return
    out.setdefault(name)


def mentions(text: str, limit: int = 30) -> Mentions:
    """Identifiers, ``.py`` paths and plain words named in ``text``, in priority
    order: traceback functions (innermost first), backticked code, dotted names,
    code-looking words, command-line options (``--ignore-paths`` becomes
    ``ignore_paths``). At most ``limit`` identifiers."""
    idents: dict[str, None] = {}
    paths: dict[str, None] = {}
    for path, _line, func in reversed(_FRAME.findall(text)):
        if func != "<module>":
            _keep(idents, func)
        paths.setdefault(path.replace("\\", "/"))
    for code in _BACKTICK.findall(text):
        _keep(idents, re.split(r"[\s(\[=,:]", code.strip(), maxsplit=1)[0])
    for name in _DOTTED.findall(text):
        if not re.search(r"\.(py|com|org|io|html?|rst|txt|toml|cfg|ini|json|ya?ml)$", name):
            _keep(idents, name)
    for name in _CODEY.findall(text):
        _keep(idents, name)
    for opt in _OPTION.findall(text):
        _keep(idents, opt.replace("-", "_"))
    for p in _PATH.findall(text):
        paths.setdefault(p)
    lines = text.strip().splitlines()
    title = lines[0] if lines else ""
    words: dict[str, None] = {}
    for w in _WORD.findall(title) + _WORD.findall(text):
        w = w.lower()
        if w not in _ENGLISH and w not in COMMON:
            words.setdefault(w)
    return Mentions(tuple(list(idents)[:limit]), tuple(paths), tuple(words))


# --- scoring --------------------------------------------------------------------


def is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            or any(p in ("tests", "test", "testing") for p in parts[:-1]))


def _specific(name: str) -> bool:
    """Specific enough to look up on its own: dotted, snake_case or CamelCase."""
    if name in COMMON:
        return False
    return "." in name or "_" in name.strip("_") or any(c.isupper() for c in name[1:]) \
        or name.startswith("_")


def _module_names(graph: CodeGraph) -> set[str]:
    """Last parts of module ids (``pytest``, ``autosummary``), and their packages."""
    names: set[str] = set()
    for s in graph.symbols.values():
        if s.kind is NodeKind.MODULE:
            names.update(s.id.split("."))
    return names


def _resolve(graph: CodeGraph, name: str, modules: set[str]) -> list[str]:
    """Symbols ``name`` means, retrying without leading parts the repo lacks.

    ``pytest.raises`` keeps ``raises`` because ``pytest`` is a module of the
    repo; ``np.array`` drops to nothing because ``array`` alone is too generic
    and ``np`` is not the repo's.
    """
    found = find_seeds(graph, name)
    parts = name.split(".")
    while not found and len(parts) > 1:
        head, parts = parts[0], parts[1:]
        rest = ".".join(parts)
        if len(parts) == 1 and not _specific(rest) and head not in modules \
                and not rest[:1].isupper():
            return []
        found = find_seeds(graph, rest)
    return found


def _usable(graph: CodeGraph, sid: str) -> bool:
    sym = graph.symbol(sid)
    # A top-level package (``pytest``, ``pylint``) is the whole project.
    return not (sym.kind is NodeKind.MODULE and "." not in sid)


class _Source:
    """Lines of each indexed file, and which symbol encloses a line."""

    def __init__(self, graph: CodeGraph, root: Path):
        self.graph = graph
        self.root = root
        by_file: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for s in graph.symbols.values():
            if s.kind is not NodeKind.MODULE:
                by_file[s.file].append((s.span[0], s.span[1], s.id))
        self.spans = {f: sorted(v, key=lambda t: (t[0], -t[1])) for f, v in by_file.items()}
        self.files = sorted({s.file for s in graph.symbols.values()})
        self._text: dict[str, str] = {}

    def text(self, file: str) -> str:
        if file not in self._text:
            try:
                self._text[file] = (self.root / file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._text[file] = ""
        return self._text[file]

    def enclosing(self, file: str, line: int) -> str | None:
        best = None
        for start, end, sid in self.spans.get(file, ()):
            if start > line:
                break
            if line <= end:
                best = sid  # later starts are nested deeper
        return best

    def holders(self, word: str, limit: int = 40) -> set[str] | None:
        """Symbols whose source contains ``word`` as a whole word; ``None`` if
        more than ``limit`` (too common to say anything)."""
        pat = re.compile(rf"(?<![\w.]){re.escape(word)}(?!\w)|(?<=\.){re.escape(word)}(?!\w)")
        out: set[str] = set()
        for f in self.files:
            text = self.text(f)
            if word not in text:
                continue
            for m in pat.finditer(text):
                sid = self.enclosing(f, text.count("\n", 0, m.start()) + 1)
                if sid:
                    out.add(sid)
                    if len(out) > limit:
                        return None
        return out


def _rank_weight(i: int) -> float:
    return 1.0 / (1.0 + 0.1 * i)


def score_seeds(graph: CodeGraph, root: str | Path, text: str) -> dict[str, float]:
    """Every candidate start symbol for ``text`` with its score (higher first)."""
    m = mentions(text)
    scores: Counter[str] = Counter()
    unresolved: list[tuple[int, str]] = []
    n_frames = len(_FRAME.findall(text))
    modules = _module_names(graph)

    for i, name in enumerate(m.identifiers):
        if name in COMMON:
            continue
        found = [s for s in _resolve(graph, name, modules) if _usable(graph, s)]
        if not found:
            last = name.rsplit(".", 1)[-1]
            if _specific(last) or "_" in last:
                unresolved.append((i, last))
            continue
        if len(found) > 3:
            continue
        w = _rank_weight(i) * (1.5 if i < n_frames else 1.0) / len(found)
        if not _specific(name):
            w *= 0.5  # a bare common-ish word that happens to resolve
        for sid in found:
            scores[sid] += w

    source = _Source(graph, Path(root))
    for i, word in unresolved:
        holders = source.holders(word)
        if not holders:
            continue
        w = 0.6 * _rank_weight(i) / math.sqrt(len(holders))
        for sid in holders:
            scores[sid] += w

    if not scores:
        _score_words(graph, m.words, scores)

    for sid in list(scores):
        sym = graph.symbol(sid)
        if is_test_file(sym.file):
            scores[sid] *= 0.15
        if sym.kind is NodeKind.MODULE:
            # A seed is shown in full, and a whole module eats the budget; prefer
            # the functions and classes in it when the text names them too.
            scores[sid] *= 0.5
    return dict(scores)


def _score_words(graph: CodeGraph, words: tuple[str, ...], scores: Counter) -> None:
    parts: dict[str, set[str]] = defaultdict(set)
    for s in graph.symbols.values():
        if s.kind is NodeKind.MODULE:
            continue
        for p in _NAME_PART.findall(s.id.rsplit(".", 1)[-1]):
            parts[p.lower()].add(s.id)
    n = max(1, len(graph))
    for i, w in enumerate(words[:40]):
        stem = w[:-1] if w.endswith("s") and w[:-1] in parts else w
        holders = parts.get(stem)
        if not holders or len(holders) > n / 20:
            continue
        idf = math.log(n / len(holders))
        for sid in holders:
            scores[sid] += idf * _rank_weight(i)


def seeds_from_text(graph: CodeGraph, root: str | Path, text: str,
                    max_seeds: int = 5, min_share: float = 0.25) -> list[str]:
    """Up to ``max_seeds`` symbol ids to start from for the task in ``text``.

    Keeps the best-scoring candidates whose score is at least ``min_share`` of
    the best one, so one strong match is not diluted by weak ones.
    """
    scores = score_seeds(graph, root, text)
    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[0][1]
    return [sid for sid, s in ranked[:max_seeds] if s >= min_share * top]
