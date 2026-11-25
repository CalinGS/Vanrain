# Free coverage check, pilot tasks (2026-11-25)

No model involved. For each of the 25 pilot tasks (`eval/tasks/pilot.json`,
SWE-bench Lite revision `6ec7bb8`), each condition built its context from the
issue text alone, at a 2,000-token budget. Score: does the context name the
file that the gold fix changed? (Every pilot fix touches exactly one file.)
Tokens were counted with tiktoken `o200k_base`. Raw rows: `coverage-2000.jsonl`.

Reproduce from `eval/`: `python -m harness coverage data/swebench_lite.jsonl
tasks/pilot.json --workdir work` (Aider needs `aider-chat`, here 0.86.2 in a
separate venv).

## Results

| Condition | Names the fixed file | Empty context | Median injected tokens |
|---|---|---|---|
| Vanrain, signatures-first | 12 / 25 | 5 / 25 (no seed found) | 2,212 |
| Vanrain, signatures-only | 12 / 25 | 5 / 25 | 2,213 |
| Aider repo map | 12 / 25 | 0 / 25 | 1,960 |

- **A tie overall, but on different tasks.** Both name the file on 6 tasks;
  Vanrain alone on 6 (requests-2674, -2148, -863, sphinx-8713, astropy-7746,
  -14365); Aider alone on 6; neither on 7.
- **Vanrain's misses come in two kinds.**
  1. *No seed* (5 tasks): the issue names nothing that resolves to a symbol (a
     config option like `autodoc_typehints`, XML field names, or only a module
     name). Vanrain then adds nothing. Aider always returns a map, because it
     falls back to a global PageRank, and that found the file on 4 of these 5.
  2. *Wrong seed* (7 tasks): the issue names user-facing API (`pairplot`,
     `Table`, `register_blueprint`, `pytest`) while the fix is deeper or
     elsewhere (`_oldcore.py`, `cli.py`, `assertion/rewrite.py`). Seeds also
     pick up noise such as `open`, `load` or whole modules.
- **At 2,000 tokens, signatures-only and signatures-first are the same.** The
  text was identical on 22 of 25 tasks: signatures use the whole budget, so
  nothing is left to upgrade to full bodies. The pilot comparison "do bodies
  help" is empty at this budget. 4,000 tokens did not name any more fixed files
  either (same 12 tasks).
- Vanrain overshoots its budget by about 10% (median 2,212 at 2,000) because
  the markdown framing is not counted, as noted in DESIGN.md.

## What this means for the plan

1. **Seeding is the bottleneck, before ranking.** A fallback for issues with no
   resolvable seed (file and module mentions, or a global rank like Aider's)
   and filtering noisy seeds (builtins, whole modules, test-only names) would
   address most misses. This fits milestone 7 or a small fix before the agent
   pilot.
2. **Replace `vanrain_sig_only` in the pilot** with `vanrain_full_first`, which
   differs at 2,000 tokens, or test bodies at a larger budget. As planned, the
   two conditions would spend agent runs on identical prompts.
3. File-level coverage is a coarse check: Aider's map lists many files with a
   few lines each, Vanrain fewer files in more depth. Only the agent runs show
   which of the two helps more.
