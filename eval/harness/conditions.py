"""The conditions we compare, and the context each one adds to the prompt.

Every condition produces an ``Injected`` block that goes into the agent's first
message at the same place, under the same heading (``wrap``). The agent and its
tools are identical across conditions; only this block differs. ``none`` adds
nothing, so the agent explores the repo on its own.

| name                 | context                                              |
|----------------------|------------------------------------------------------|
| none                 | nothing                                              |
| vanrain_sig_first    | Vanrain, signatures for all near code, then bodies   |
| vanrain_sig_only     | Vanrain, signatures only (isolates "do bodies help") |
| vanrain_full_first   | Vanrain, whole bodies nearest first (optional)       |
| aider_map            | Aider's repo map, same mentions, same budget         |
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harness.issue_seeds import Mentions, extract, resolve_vanrain_seeds
from harness.metrics import count_tokens

HEADING = "## Code that may be relevant (selected automatically)"


@dataclass
class Injected:
    """What one condition adds for one task."""

    condition: str
    text: str  # the block as the agent sees it ("" for none)
    tokens: int  # counted with the harness's fixed tokenizer (metrics.count_tokens)
    seeds: tuple[str, ...] = ()  # what the condition started from
    index_seconds: float = 0.0  # building the graph / tags cache
    select_seconds: float = 0.0  # choosing and rendering under the budget
    notes: list[str] = field(default_factory=list)


def wrap(body: str) -> str:
    """The shared framing, so conditions differ only in content."""
    if not body.strip():
        return ""
    return (f"{HEADING}\n\nThis may or may not contain what you need; "
            f"read files yourself when it does not.\n\n{body.strip()}\n")


def _vanrain(strategy: str) -> Callable[[Path, str, int], Injected]:
    def build(repo: Path, issue: str, budget: int) -> Injected:
        from vanrain import api

        name = f"vanrain:{strategy}"  # build() replaces it with the registry name
        t0 = time.perf_counter()
        graph = api.open_repo(repo, cache=False).graph
        t1 = time.perf_counter()
        seeds = resolve_vanrain_seeds(graph, extract(issue))
        if not seeds:
            return Injected(name, "", 0, (), t1 - t0, 0.0, ["no seed resolved"])
        ctx = api.get_context(repo, seeds, budget=budget, strategy=strategy, graph=graph)
        t2 = time.perf_counter()
        text = wrap(ctx.text)
        return Injected(name, text, count_tokens(text), tuple(ctx.seeds), t1 - t0, t2 - t1)

    return build


def _none(repo: Path, issue: str, budget: int) -> Injected:
    return Injected("none", "", 0)


def _aider_map(repo: Path, issue: str, budget: int) -> Injected:
    """Aider's repo map for the same mentions at the same budget.

    Runs Aider's ``RepoMap`` from a separate, pinned install (aider-chat pulls
    in many dependencies we keep out of Vanrain's venv). The call below follows
    aider's ``aider/repomap.py``; check it against the pinned version before the
    first run, since RepoMap is internal API and may change between releases.
    """
    try:
        from aider.io import InputOutput
        from aider.models import Model
        from aider.repomap import RepoMap
    except ImportError as e:  # pragma: no cover - optional dependency
        raise RuntimeError("aider_map needs aider-chat installed (see eval/requirements.txt)") from e

    mentions: Mentions = extract(issue)
    files = [str(p) for p in repo.rglob("*.py") if ".git" not in p.parts]
    t0 = time.perf_counter()
    rm = RepoMap(map_tokens=budget, root=str(repo), main_model=Model("gpt-4o"),
                 io=InputOutput(yes=True), refresh="always")
    body = rm.get_repo_map(chat_files=[], other_files=files,
                           mentioned_fnames=set(mentions.paths),
                           mentioned_idents=set(mentions.identifiers)) or ""
    t1 = time.perf_counter()
    text = wrap(body)
    return Injected("aider_map", text, count_tokens(text),
                    mentions.identifiers + mentions.paths, 0.0, t1 - t0,
                    ["index and selection time are not separable in RepoMap"])


CONDITIONS: dict[str, Callable[[Path, str, int], Injected]] = {
    "none": _none,
    "vanrain_sig_first": _vanrain("signatures_first"),
    "vanrain_sig_only": _vanrain("signatures_only"),
    "vanrain_full_first": _vanrain("full_first"),
    "aider_map": _aider_map,
}

#: The pilot runs these four; vanrain_full_first is optional (DESIGN.md, 2).
PILOT_CONDITIONS = ("none", "vanrain_sig_first", "vanrain_sig_only", "aider_map")


def build(condition: str, repo: str | Path, issue: str, budget: int = 2000) -> Injected:
    if condition not in CONDITIONS:
        raise KeyError(f"unknown condition {condition!r}; known: {', '.join(CONDITIONS)}")
    out = CONDITIONS[condition](Path(repo), issue, budget)
    out.condition = condition
    return out
