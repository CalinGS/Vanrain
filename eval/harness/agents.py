"""Agent adapters: run one agent on one task with one condition's context.

The agent is chosen after the design is approved (DESIGN.md, section 4), so
only the interface and a dry-run adapter exist. Every adapter must:

1. put ``prompt(task, injected)`` in the agent's first user message, unchanged;
2. work in the checkout it is given, with the same step and cost limits for
   every condition;
3. return the per-call usage and every tool call, so ``metrics`` can count them;
4. return the final diff (``checkout.diff``) for SWE-bench to evaluate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from harness.conditions import Injected
from harness.metrics import CallUsage
from harness.tasks import Task

PROMPT = """\
You are working in a Python repository checked out at {repo}.
Fix the issue below. Edit the source files; do not add or change tests.
When you are done, stop.

## Issue

{issue}
{context}"""


def prompt(task: Task, injected: Injected, repo: Path) -> str:
    """The first user message. Identical across conditions except ``context``."""
    context = f"\n{injected.text}" if injected.text else ""
    return PROMPT.format(repo=repo, issue=task.problem_statement.strip(), context=context)


@dataclass
class Limits:
    """Same for every condition, so savings are not just earlier give-ups."""

    max_steps: int = 50
    max_cost_usd: float = 2.0
    max_seconds: int = 1800


@dataclass
class AgentResult:
    calls: list[CallUsage] = field(default_factory=list)
    actions: list[tuple[str, list[str]]] = field(default_factory=list)  # classified tool calls
    exit_status: str = ""
    seconds: float = 0.0
    transcript_path: Path | None = None


class Agent(Protocol):
    name: str
    model: str

    def run(self, task: Task, repo: Path, first_message: str, limits: Limits) -> AgentResult: ...


class DryRun:
    """Writes the prompt it would send and does nothing else. Costs nothing."""

    name = "dry-run"
    model = "none"

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)

    def run(self, task: Task, repo: Path, first_message: str, limits: Limits) -> AgentResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{task.instance_id}.prompt.md"
        path.write_text(first_message, encoding="utf-8")
        return AgentResult(exit_status="dry_run", transcript_path=path)


# Candidates, not implemented until the agent is chosen:
#
# MiniSweAgent   mini-swe-agent's DefaultAgent with a LiteLLM model (Claude API,
#                Gemini, or Ollama), bash-only tools, inside the task's SWE-bench
#                Docker image. Usage per call from LiteLLM's response; actions
#                via metrics.classify_command.
# ClaudeCode     `claude -p <prompt> --output-format stream-json --verbose
#                --max-turns N --disallowedTools Task,WebFetch,WebSearch` in the
#                checkout. Usage per assistant message from the stream; actions
#                via metrics.classify_tool.
