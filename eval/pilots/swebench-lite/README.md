# Agent pilot in the cloud: setup and first trial (2026-11-25)

## How one run works
- One scheduled task per (task, condition), created with `create_new_session_on_fire`, then fired once.
  The prompt is `make_prompt.py TASK CONDITION` (checkout command at the base commit, issue, optional
  context block, "final message = git diff"). Each run becomes a new thread in the Vanrain project.
- Afterwards: `get_session <id>` gives `usage.cost_usd` and token totals; `list_events kinds=[result]`
  gives the final diff and `num_turns`; `kinds=[assistant]` gives every tool call.
- Grading: apply the diff + the SWE-bench test_patch to a clean checkout, run FAIL_TO_PASS/PASS_TO_PASS
  (`grade.sh` does this for flask-4992; other repos need their own venv).

## Inputs prepared
- `contexts/<id>.vanrain_sig_first.md` for all 25 pilot tasks (2,000 tokens; 5 tasks empty: no seed).
- Aider maps NOT built: the cloud blocks tiktoken's download host. Build them on Calin's PC
  (aider already works there) or allow openaipublic.blob.core.windows.net.

## Trial: pallets__flask-4992, Opus 5.5, cloud thread sessions
| condition | cost | model calls | cache read | cache write | output | result |
|---|---|---|---|---|---|---|
| none | $0.38 | 5 | 317k | 32.7k | 2.2k | diff identical to gold patch |
| vanrain_sig_first | $0.32 | 5 | 343k | 25.9k | 2.3k | diff identical to gold patch |

Both runs wrote the exact upstream patch (same `text` parameter, same docstring and versionchanged
lines) after one grep, although the issue asks for `mode="b"`. That is memorization of the public fix:
SWE-bench Lite is contaminated for this model, so it measures recall, not context selection.
About 67k tokens per call are fixed overhead (system prompt, tools, project instructions).
