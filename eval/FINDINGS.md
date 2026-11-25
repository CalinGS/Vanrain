# Vanrain: findings and verdict (2026-11-25)

**Verdict: stopped.** Across three agent pilots, giving the agent a 2,000-token
Vanrain context did not change how many tasks it solved, and it cut tokens by
only 5 to 7%, which is inside run-to-run noise. The project is archived here
so the results and tools can be reused.

## Results at a glance

| Experiment | Without Vanrain | With Vanrain | Notes |
|---|---|---|---|
| Agent pilot, recent issues in small repos (pytest, pylint, xarray) | 13/18 solved | 13/18 solved | tokens -5% median; pytest -30%, pylint/xarray +4% |
| Agent pilot, recent issues in larger repos (sympy, astropy) | 23/27 solved | 23/27 solved | tokens -7 to -8% median; repeat runs differ by ~10% |
| File coverage from issue text (25 SWE-bench Lite tasks, no model) | Aider map 12/25 | Vanrain 12/25, then 14/25 with Gate 1 text seeds | "names the file the fix changed" |
| Offline detail test (145 commits, no model) | whole functions 29% | signatures-first 48% | share of needed symbols visible at 2,000 tokens |
| Learned edge weights (324 commits, held-out repos) | BFS 46 to 48% | learned 48 to 49% | +1 to +3 points; big gains only on training repos |

Details: `pilots/recent-small/RESULTS.md`, `pilots/recent-large/RESULTS.md`,
`results/coverage-2000.md`, `research/detail-test-results.md`,
`research/weight-search-results.md`, `pilots/swebench-lite/README.md`.

## What we learned

1. **SWE-bench Lite is contaminated for current models.** In the first trial
   (flask-4992) both conditions wrote the exact upstream patch after one grep.
   It measures recall, not context selection. The later pilots used only fixes
   committed after the model's training cutoff, checked against upstream git
   dates and FAIL_TO_PASS tests.
2. **The agent harness drowns the signal.** Each Claude Code call carries about
   70k tokens of fixed context (system prompt, tools, instructions). Vanrain's
   2k block is about 3% of one call, so total tokens track the number of
   calls. Vanrain saved a few calls (280 to 254 on the large repos), but cost
   barely moved (median -1%).
3. **The tasks were too easy to need a map.** Most runs finished in 5 to 14
   calls either way. Where exploration dominated (pytest), Vanrain helped
   most (calls 64 to 44); elsewhere it was mixed.
4. **Signatures beat whole functions, offline.** At the same budget the graph
   with signatures shows about twice as much needed code as whole functions,
   and more than reading the target's whole file. At 2,000 tokens
   signatures-first and signatures-only are identical: signatures fill the
   budget, so bodies never get added.
5. **Seeding matters more than ranking.** Most coverage misses came from no
   seed (the issue names a config option or only a module) or a wrong seed
   (user-facing API while the fix is deeper). Gate 1 text seeds moved coverage
   from 12/25 to 14/25.
6. **Learned edge weights do not generalise.** A search over per-edge-kind
   weights gained 7 to 12 points on the repos it was tuned on and only 1 to 3
   on unseen repos. Richer per-candidate signals (co-change, recency, name
   overlap) were never tried.
7. **The Aider repo-map baseline was never run in the agent pilots.** Its maps
   could not be built in the cloud (tiktoken download blocked). It only
   appears in the offline file-coverage check.

## What a real test would need

Harder tasks where exploration dominates cost, a lean agent harness (or a
cheaper model) so the fixed context does not swamp a 2k block, several repeats
per task, and the Aider baseline in the agent runs.

## Code state

- `main`: milestones 1 to 6 plus Gate 1 text seeds (PR #11).
- `fix-empty-subscript` (PR #10, open): parser crash on `tuple[()]`
  annotations, found while indexing pylint.
- `eval/research/tools/`: offline detail test, weight search, smoke test.
- `eval/pilots/`: scripts, per-run tables and grades for the three agent
  pilots. Prompts, contexts and agent diffs stay in the project library, not
  in git. Gold patches were kept out on purpose; rebuild with `prep.py`.
