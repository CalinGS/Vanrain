"""A clean working copy of a task's repo at its base commit.

The agent must not be able to find the fix in git history (``git log --all``
would show later commits in a full clone), so the checkout holds exactly one
commit: we fetch the base commit with depth 1 into an empty repo.

Index caches (``.vanrain/``, Aider's ``.aider.tags.cache*``) are excluded from
git so they never show up in the agent's diff.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.tasks import Task

IGNORED = (".vanrain/", ".aider*")


def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


def checkout(task: Task, workdir: str | Path) -> Path:
    """``<workdir>/<instance_id>`` at ``task.base_commit`` with one commit of history.

    Reuses the directory if it is already at that commit, after ``git reset
    --hard`` and ``git clean -fdx`` (so a previous run's edits are gone).
    """
    dest = Path(workdir) / task.instance_id
    url = f"https://github.com/{task.repo}.git"
    if (dest / ".git").exists():
        if _git(["rev-parse", "HEAD"], dest) == task.base_commit:
            _git(["reset", "--hard", "-q"], dest)
            _git(["clean", "-fdxq"], dest)
            return dest
        raise RuntimeError(f"{dest} exists at another commit; remove it first")
    dest.mkdir(parents=True)
    _git(["init", "-q"], dest)
    _git(["remote", "add", "origin", url], dest)
    _git(["fetch", "-q", "--depth", "1", "origin", task.base_commit], dest)
    _git(["checkout", "-q", "FETCH_HEAD"], dest)
    _git(["remote", "remove", "origin"], dest)
    exclude = dest / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as f:
        f.write("\n".join(IGNORED) + "\n")
    return dest


def diff(repo: Path) -> str:
    """The agent's change as a patch (what SWE-bench evaluates)."""
    _git(["add", "-A"], repo)
    return subprocess.run(["git", "diff", "--cached"], cwd=repo, check=True,
                          capture_output=True, text=True).stdout
