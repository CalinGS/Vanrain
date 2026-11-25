"""One record per (task, condition, repeat), and how each number is counted.

Tokens are counted two ways (DESIGN.md, section 3):

- ``billed``: what the provider reports per model call (input, cached input,
  output), summed over the run. This is cost, and is only comparable between
  conditions that use the same model.
- ``fixed``: every message the model saw or wrote, re-counted with one fixed
  tokenizer (``count_tokens``), summed per call. Comparable across models.

File reads and tool calls come from the agent's commands (``classify_command``)
or, for agents with typed tools, from the tool name (``classify_tool``).
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:  # one fixed tokenizer for every condition and model, if available
    import tiktoken

    _ENC = tiktoken.get_encoding("o200k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text, disallowed_special=()))

    TOKENIZER = "tiktoken:o200k_base"
except ImportError:  # fall back to Vanrain's own estimator
    from vanrain.tokens import estimate_tokens as count_tokens  # noqa: F401

    TOKENIZER = "vanrain:chars/4"


@dataclass
class CallUsage:
    """One model call."""

    input_tokens: int = 0  # uncached input, as billed
    cached_input_tokens: int = 0  # cache reads, as billed
    cache_write_tokens: int = 0
    output_tokens: int = 0  # includes reasoning/thinking tokens where reported
    fixed_input_tokens: int = 0  # whole prompt re-counted with count_tokens
    fixed_output_tokens: int = 0
    seconds: float = 0.0


@dataclass
class RunRecord:
    """Everything we keep about one agent run."""

    instance_id: str
    condition: str
    repeat: int
    agent: str  # adapter name and version
    model: str  # exact model id string sent to the provider
    budget: int  # context budget given to the condition (0 for none)
    tokenizer: str = TOKENIZER
    injected_tokens: int = 0
    seeds: list[str] = field(default_factory=list)
    calls: list[CallUsage] = field(default_factory=list)
    tool_calls: int = 0
    file_reads: int = 0  # commands/tools that show file contents
    searches: int = 0  # grep/find/ls style exploration
    edits: int = 0
    distinct_files_read: list[str] = field(default_factory=list)
    agent_seconds: float = 0.0  # wall time of the agent loop only
    index_seconds: float = 0.0  # condition's indexing (reported separately)
    select_seconds: float = 0.0
    exit_status: str = ""  # submitted / step_limit / cost_limit / error
    patch: str = ""
    resolved: bool | None = None  # SWE-bench verdict, filled in by evaluation
    fail_to_pass_passed: int | None = None
    fail_to_pass_total: int | None = None
    pass_to_pass_failed: int | None = None
    gold_files_in_context: float | None = None  # coverage, see gold_file_coverage

    # Totals the analysis reads; computed, not stored separately.
    @property
    def billed_input(self) -> int:
        return sum(c.input_tokens + c.cached_input_tokens + c.cache_write_tokens
                   for c in self.calls)

    @property
    def billed_output(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def fixed_total(self) -> int:
        return sum(c.fixed_input_tokens + c.fixed_output_tokens for c in self.calls)

    def to_json(self) -> str:
        d = asdict(self)
        d.update(billed_input=self.billed_input, billed_output=self.billed_output,
                 fixed_total=self.fixed_total)
        return json.dumps(d)


def append(record: RunRecord, path: str | Path) -> None:
    """Runs go to one JSONL file per experiment; append-only."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(record.to_json() + "\n")


# --- classifying what the agent did --------------------------------------------

_READ = {"cat", "head", "tail", "less", "more", "nl", "bat", "view"}
_SEARCH = {"grep", "rg", "ag", "find", "ls", "tree", "fd", "git"}
_EDIT = {"sed", "patch", "tee", "apply_patch", "ed"}


def classify_command(command: str) -> tuple[str, list[str]]:
    """``("read"|"search"|"edit"|"run"|"other", files)`` for one bash command.

    Looks at the first word of each piece of a pipeline or ``&&`` chain and
    takes the strongest kind (read > edit > search > run). ``sed -n`` and
    ``python -c "print(open(...))"`` style reads count as reads; ``sed -i`` and
    heredoc redirections (``cat > f``) as edits.
    """
    kinds: set[str] = set()
    files: list[str] = []
    for piece in re.split(r"\|\||&&|;|\|", command):
        try:
            words = shlex.split(piece, posix=True)
        except ValueError:
            words = piece.split()
        if not words:
            continue
        head = Path(words[0]).name
        rest = [w for w in words[1:] if not w.startswith("-")]
        py_files = [w for w in rest if re.search(r"\.(py|pyi|txt|cfg|toml|rst|md)$", w)]
        if head in _READ and ">" not in piece:
            kinds.add("read")
            files += py_files
        elif head == "sed":
            if "-i" in words:
                kinds.add("edit")
            else:
                kinds.add("read")
                files += py_files
        elif head in _EDIT or re.search(r"(^|\s)>{1,2}\s*\S", piece):
            kinds.add("edit")
        elif head in _SEARCH:
            kinds.add("search")
        elif head in {"python", "python3", "pytest", "tox", "pip"}:
            if "open(" in piece and "read" in piece:
                kinds.add("read")
            else:
                kinds.add("run")
    for kind in ("read", "edit", "search", "run"):
        if kind in kinds:
            return kind, files
    return "other", files


#: Typed tools (Claude Code style) mapped to the same kinds.
TOOL_KINDS = {"Read": "read", "Grep": "search", "Glob": "search", "LS": "search",
              "Edit": "edit", "MultiEdit": "edit", "Write": "edit", "Bash": None}


def classify_tool(name: str, tool_input: dict) -> tuple[str, list[str]]:
    kind = TOOL_KINDS.get(name, "other")
    if kind is None:  # Bash: look inside
        return classify_command(str(tool_input.get("command", "")))
    path = tool_input.get("file_path") or tool_input.get("path")
    return kind, [path] if kind == "read" and path else []


def tally(record: RunRecord, actions: list[tuple[str, list[str]]]) -> None:
    """Fill the tool-call counters of ``record`` from classified actions."""
    seen: dict[str, None] = dict.fromkeys(record.distinct_files_read)
    for kind, files in actions:
        record.tool_calls += 1
        if kind == "read":
            record.file_reads += 1
            for f in files:
                seen.setdefault(f.removeprefix("./"))
        elif kind == "search":
            record.searches += 1
        elif kind == "edit":
            record.edits += 1
    record.distinct_files_read = list(seen)


# --- offline coverage: does the context name the files the fix touched? -------------

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/", re.M)


def patch_files(patch: str) -> list[str]:
    """Files a unified diff changes, in order."""
    return list(dict.fromkeys(_DIFF_FILE.findall(patch)))


def gold_file_coverage(context: str, gold_patch: str) -> float | None:
    """Share of the gold patch's files that the injected context names.

    A cheap, model-free check that works the same for Vanrain and Aider (both
    print file paths). ``None`` when the patch names no files.
    """
    files = patch_files(gold_patch)
    if not files:
        return None
    return sum(1 for f in files if f in context) / len(files)
