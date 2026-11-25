# Milestone 6: benchmark design

Status: **draft for approval**. Nothing here has been run against a model yet.
Plan reference: Vanrain.pdf, section 8 and milestone 6 ("same tasks with and
without Vanrain; tokens, tool calls, tests passed").

The question: with the same agent, the same model and the same tasks, does
putting Vanrain's context in the prompt cut tokens per task without lowering the
share of tasks solved? And does it beat Aider's repo map at the same budget?

## 1. Task set

**Source.** SWE-bench Lite (300 real GitHub issues from 12 Python repos, each
with a base commit, the gold fix, and tests that fail before the fix and pass
after). The results stay comparable to published work, and the official
harness grades them.

**Pilot: 25 tasks, small repos first.** `python -m harness select` picks them
deterministically: round-robin over requests, flask, seaborn, pytest, pylint,
xarray, sphinx and astropy, at most 5 per repo, each repo's tasks in a seeded
hash order. Django, sympy, scikit-learn and matplotlib (about 80% of Lite) wait
for the full run because they are large and dominate the set. If the user
agrees, we also keep only instances that are in SWE-bench Verified too, since
those were checked by people to be solvable from the issue text.

**Checkout and tests.**

- Agent side: `checkout.py` fetches only the base commit (`--depth 1` into an
  empty repo, remote removed), so `git log` cannot reveal the fix. The index
  caches (`.vanrain/`, `.aider*`) are git-excluded so they never enter the diff.
- Grading side: the official `swebench` harness (`run_evaluation`) applies the
  agent's diff and the hidden test patch in the instance's Docker image and runs
  FAIL_TO_PASS and PASS_TO_PASS. On Windows this means Docker Desktop with WSL2.
  We never grade by running tests on the host: old repos need old Pythons and
  pinned dependencies, which the images already have.

**Reproducibility.**

- Pin the dataset revision (Hugging Face commit sha) in `tasks/pilot.json`,
  along with the selection seed and the instance ids.
- Pin the versions of `swebench`, the agent, Aider and Vanrain (git sha) in each
  run record. Record the exact model id string.
- Same limits for every condition (steps, cost, wall time), temperature or
  effort fixed, run order interleaved across conditions so a provider slowdown
  or model update hits all of them.
- Each run appends one JSON line (`metrics.RunRecord`) and keeps its full
  transcript, so every number can be recounted later.
- Agents are not deterministic even at temperature 0. The pilot runs each
  (task, condition) once; the full run uses 3 repeats.

## 2. Conditions

| Condition | What the agent gets in its first message |
|---|---|
| `none` | Only the issue. The agent explores normally (the realistic baseline). |
| `vanrain_sig_first` | Issue + Vanrain context, default strategy: signatures for all nearby code, then full bodies with what is left. |
| `vanrain_sig_only` | Issue + Vanrain context, signatures only. Against `sig_first`, this isolates whether full bodies help, because both rank the same symbols and differ only in the upgrade step. |
| `aider_map` | Issue + Aider's repo map at the same budget. Required baseline. |
| `vanrain_full_first` | Optional fifth: whole bodies nearest first. The offline detail test already showed it sees less of the needed code at a fixed budget, so I suggest skipping it in the pilot. |

**How context is injected.** Every condition puts its block in the same place,
the first user message after the issue, under the same heading and the same one
line of framing ("may or may not contain what you need"). The agent, its tools,
its system prompt and its limits are identical. `none` adds nothing. This is
"prompt mode". Giving the agent Vanrain as a tool it can call is a later
condition, after milestone 8 (MCP server).

**Same input for Vanrain and Aider.** Neither gets the gold patch or any hint
from it. `issue_seeds.extract` pulls identifiers and `.py` paths from the issue
text (traceback frames first, then backticked code, dotted names and
code-looking words). Vanrain resolves them to up to 5 seed symbols, skipping
names that match more than 3 symbols. Aider gets the same lists as
`mentioned_idents` and `mentioned_fnames`. When no seed resolves, the Vanrain
condition adds nothing, and we report how often that happens.

**Budget.** The pilot uses 2,000 tokens; 4,000 is optional. Vanrain's budget
covers symbols and their header lines but not the markdown around them, so the
rendered block is about 10% larger (2,231 tokens at 2,000 and 4,374 at 4,000,
measured on Vanrain's own source). Aider counts its map in its own way. So the
harness measures the block that is actually injected with one tokenizer, and the
write-up compares conditions on that measured size.

**Free check before any agent run.** `python -m harness coverage` builds every
condition's context for the pilot tasks and reports what share of the files
changed by the gold patch each context names. It needs no model and costs
nothing, so it shows early whether Vanrain's seeds and ranking reach the right
code on real issues, before we pay for agent runs.

## 3. Metrics

Per run (`metrics.RunRecord`):

| Metric | How it is counted |
|---|---|
| Tokens per task | Two numbers. **Billed** is the provider's reported usage per call (input, cache reads, cache writes, output with thinking), summed over the run. It measures cost and only compares runs on the same model. **Fixed** re-counts every prompt and reply with one tokenizer (tiktoken `o200k_base`, falling back to Vanrain's estimate of 4 characters per token), summed per call, so it compares across models. The injected block is counted on its own as well. |
| Tool calls, file reads | Every agent action is classified as read, search, edit, run or other. Bash commands go through `classify_command` (`cat`, `sed -n` and `head` are reads; `sed -i` and `>` are edits; `grep`, `find` and `ls` are searches). Typed tools (Claude Code's Read, Grep, Edit) go through `classify_tool`. We also keep the list of distinct files read. |
| Tests passed | SWE-bench's verdict: **resolved** means all FAIL_TO_PASS tests pass and no PASS_TO_PASS test breaks. We also keep how many FAIL_TO_PASS tests passed as partial credit, and how often an agent hit its step or cost limit. |
| Wall time | The agent loop only. Indexing and selection time are recorded separately, because the index is built once per repo in real use. |

**Analysis, decided before any runs.** Comparisons are paired by task. The
headline is the median and mean change in billed tokens against `none`, with
paired bootstrap confidence intervals, plus the resolved rate for each
condition. Runs that hit a limit count as failures, and their tokens still
count. With 25 tasks the pilot can show a large token effect (about 30% or more).
It cannot show a small change in success rate; its job is to check the pipeline
and estimate effect sizes so we can size the full run.

## 4. Agent options

One agent and one model run every condition. Options, with what I could and
could not check (web search on 2026-11-25):

| Option | What it needs | Limits | Pilot cost (100 runs) |
|---|---|---|---|
| **A. mini-swe-agent + Claude API** (recommended) | An Anthropic API account with prepaid credit (separate from Claude Pro), `pip install mini-swe-agent` (pinned), Docker in WSL2. | Bash-only agent, so it is simple, open and reproducible, and the SWE-bench team uses it for its own baselines. Exact per-call usage. | Haiku 5.5 about $3 for a shakedown; **Sonnet 5.5 about $45** (range $25 to $100); Opus 5.5 about $80. |
| B. Claude Code headless on Claude Pro | `claude -p ... --output-format stream-json`, with Pro login. | The most realistic agent, and the one milestone 8 targets. Its own system prompt and tools are large and change between versions, so runs are less reproducible; pin the CLI version and disable subagents and web tools. **Unverified:** official docs say `claude -p` on subscription plans draws from a monthly "Agent SDK credit" since 2026-06-15. I could not find how big that credit is for Pro, or whether bulk benchmarking fits the consumer terms. | $0 extra while the credit lasts. At API prices it would be about $50 to $150, because each call carries a large Claude Code prompt. |
| C. Ollama, local Qwen 8B | Ollama, a GPU with roughly 10 GB or more of VRAM for a 32k context (not checked on your machine), mini-swe-agent through LiteLLM. **Set `num_ctx`**, because Ollama's default context is small and it silently truncates long prompts. | Free and unlimited, but an 8B model rarely solves SWE-bench tasks, so the success rate will sit near 0 and tell us little. Weak models also loop, which inflates token counts. Good for testing the pipeline end to end. | $0; roughly 10 to 30 hours of machine time (a guess, hardware unknown). |
| D. Gemini API, free key | mini-swe-agent through LiteLLM. | **Probably not feasible.** Third-party reports (not Google's own page, which only points to AI Studio) say the free tier was cut to about 20 requests a day for Flash models in December 2025. The pilot needs about 4,000 requests (100 runs × about 40 calls). Flash-Lite was reported at about 500 a day, which means about 8 days. Free-tier prompts may also be used by Google; I did not verify the current terms. Your AI Studio page shows your real limits. | $0, if the limits allow it. |
| E. Perplexity Pro | n/a | **Not suitable.** Sonar models are built for search answers, not for coding agents that call tools in a loop. Several sources say the Pro plan's $5 monthly API credit ended in February 2026; I could not confirm it either way. | n/a |

**Recommendation:** option A. Shake down the harness on Ollama (C) or with Haiku
5.5 (about $3), then run the counted pilot on Sonnet 5.5 (about $45). If you
would rather spend nothing on an API, B is the fallback; do one short trial
first to see how much of the Pro credit a single run uses.

## 5. Cost estimate

Assumptions, from published mini-swe-agent trajectories and not yet measured
here: about 40 model calls per run and an average prompt of about 20k tokens,
so about 800k input tokens per run, 90% of them served from cache, plus about
15k output tokens. Claude API list prices from Anthropic's current model table:
Sonnet 5.5 at $2 input, $0.10 cache read and $10 output per million tokens;
Haiku 5.5 at $0.10 and $0.50 (I assumed cache reads at 10% of input); Opus 5.5
at $4, $0.20 and $20.

| | Per run | Pilot: 25 tasks × 4 conditions × 1 = 100 runs | Full: 300 tasks × 4 × 3 repeats = 3,600 runs |
|---|---|---|---|
| Haiku 5.5 | ~$0.03 | ~$3 | ~$100 |
| Sonnet 5.5 | ~$0.45 | ~$45 | ~$1,600 |
| Opus 5.5 | ~$0.80 | ~$80 | ~$2,900 |

Treat these as within a factor of 2. Failed runs that use all 50 steps cost
several times more than the average run. A 4,000-token budget adds about 50%
(two more conditions). The real per-run figure comes from the first 10 pilot
runs, and the full-run budget should be set from that.

Other costs: free, but heavy. SWE-bench Docker images take tens of GB of disk
for the pilot and more for the full run (not measured), and grading takes a few
minutes per instance.

## Harness skeleton (this PR)

`eval/harness/` contains task selection, the clean checkout, issue mention
extraction, all five conditions, run records and action classification, a
dry-run agent, and a CLI for the free steps (`select`, `context`, `coverage`).
The adapters for real agents wait for your decision in section 4.
`pytest eval/tests` runs 13 offline tests. The main suite does not collect them.

## Questions for you

1. **Agent and model:** A (mini-swe-agent + Claude API, about $45 for the
   pilot on Sonnet 5.5), B (Claude Code on your Pro plan), or free only (C)?
2. **Your machine:** is Docker Desktop with WSL2 OK, with about 50 to 100 GB
   free disk? And which GPU (and how much VRAM) do you have, if we use Ollama?
3. **Scope of the pilot:** budget 2,000 only, or 2,000 and 4,000? Skip
   `vanrain_full_first` as I suggest? Limit the pilot to instances that are also
   in SWE-bench Verified?
4. **Free coverage check first:** may I download SWE-bench Lite (a few MB) and
   shallow-clone the 25 pilot repos to run `coverage` before any paid runs?
