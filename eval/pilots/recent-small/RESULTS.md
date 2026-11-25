# Agent pilot on recent issues (2026-11-25)

Agent: Claude Code cloud sessions (Opus 5.5, medium effort), one session per (task, condition), one run each.
Conditions: `none` (issue only) and `vanrain_sig_first` (issue + Vanrain context, 2,000 tokens, issue-text seeds from Gate 1).
Aider's repo map was not run: its maps can't be built in the cloud (blocked download); run it on a local machine later.

## Task set and contamination check
18 bug fixes from pytest (6), pylint (11) and xarray (1). Every fix commit is dated 2026-07-23 or later
(git commit date in the upstream repo), after the model's training cutoff (June 2026); 17 of 18 issues were also
opened after July 1 (`issues.jsonl` / `tasks.jsonl` have both dates). Selection: commits since July 1 that change
exactly one non-test .py file plus tests and say "fixes #N"; kept those where the upstream tests fail before the fix and
pass after it in a clean venv (FAIL_TO_PASS), and the agent never sees the tests. Grading = apply the agent's diff plus
the upstream test changes, run them (`grade.py`).

## Results
| | none | Vanrain |
|---|---|---|
| Solved (all FAIL_TO_PASS and PASS_TO_PASS pass) | 13/18 | 13/18 |
| Total cost | $8.81 | $8.84 |
| Model calls (approx.) | 190 | 170 |
| Median token change vs none, 16 tasks with a Vanrain context | | -5% (mean -7%) |
| pytest tasks with context (5) | | tokens -30% and cost -14% on average (calls 64 to 44), lower on every one, same solves |
| pylint/xarray tasks with context (11) | | tokens +4%, cost +7% on average, mixed (calls 93 to 90) |

Two tasks had no Vanrain seed (identical prompts in both conditions); they differ by 1% and 10%, which is the noise floor of one run.
Solve differences: Vanrain solved pylint-11511 where none failed; none solved pylint-11440 where Vanrain failed.

Why the effect is small: each model call carries about 70k tokens of fixed harness context (system prompt, tools,
project instructions), so tokens mostly track the number of calls, and Vanrain's 2k block is about 3% of one call.
Easy tasks finish in 5 to 10 calls either way. Cost per run: $0.32 to $0.87, mean $0.49.

## Per task
| Task | Vanrain context | Cost none | Cost Vanrain | Tokens none (k) | Tokens Vanrain (k) | Calls none | Calls Vanrain | Solved none | Solved Vanrain |
|---|---|---|---|---|---|---|---|---|---|
| pydata__xarray-11867 | yes | $0.39 | $0.44 | 588 | 626 | 8 | 8 | yes | yes |
| pylint-dev__pylint-11224 | yes | $0.36 | $0.40 | 449 | 542 | 6 | 7 | yes | yes |
| pylint-dev__pylint-11286 | yes | $0.35 | $0.38 | 447 | 464 | 6 | 6 | yes | yes |
| pylint-dev__pylint-11357 | yes | $0.32 | $0.37 | 366 | 458 | 5 | 6 | yes | yes |
| pylint-dev__pylint-11361 | yes | $0.46 | $0.45 | 764 | 634 | 10 | 8 | no | no |
| pylint-dev__pylint-11440 | yes | $0.70 | $0.85 | 1290 | 1294 | 16 | 15 | yes | no |
| pylint-dev__pylint-11459 | yes | $0.37 | $0.38 | 521 | 524 | 7 | 7 | yes | yes |
| pylint-dev__pylint-11466 | yes | $0.48 | $0.45 | 782 | 702 | 10 | 9 | yes | yes |
| pylint-dev__pylint-11479 | yes | $0.35 | $0.38 | 447 | 462 | 6 | 6 | yes | yes |
| pylint-dev__pylint-11511 | yes | $0.37 | $0.41 | 447 | 540 | 6 | 7 | no | yes |
| pylint-dev__pylint-11679 | yes | $0.57 | $0.54 | 1015 | 885 | 13 | 11 | no | no |
| pylint-dev__pylint-11809 | no seed | $0.55 | $0.58 | 1003 | 1014 | 13 | 14 | yes | yes |
| pytest-dev__pytest-14724 | yes | $0.65 | $0.53 | 1187 | 811 | 15 | 10 | yes | yes |
| pytest-dev__pytest-15005 | yes | $0.50 | $0.42 | 847 | 546 | 11 | 7 | yes | yes |
| pytest-dev__pytest-15052 | yes | $0.64 | $0.59 | 1305 | 1052 | 17 | 13 | no | no |
| pytest-dev__pytest-15290 | no seed | $0.81 | $0.87 | 1696 | 1874 | 20 | 22 | yes | yes |
| pytest-dev__pytest-15410 | yes | $0.52 | $0.43 | 852 | 543 | 11 | 7 | no | no |
| pytest-dev__pytest-15436 | yes | $0.40 | $0.36 | 735 | 527 | 10 | 7 | yes | yes |
Also found: Vanrain crashed indexing pylint (`tuple[()]` annotation, IndexError in the parser); fixed in PR #10.

## Note on gold patches
`tasks.jsonl` (with the upstream fix patches) was moved out of this shared folder so later run sessions can't read it.
Rebuild it with `prep.py` from the upstream repos when grading again.
