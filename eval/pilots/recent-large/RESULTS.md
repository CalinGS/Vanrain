# Agent pilot on larger repos: sympy and astropy (2026-11-25)

The setup matches `pilot-recent`. The agent is Claude Code cloud sessions on Opus 5.5 at medium effort, with one session per run.
- **Conditions:** `none` (the issue only) and `vanrain_sig_first` (the issue plus a 2,000-token Vanrain context built from issue-text seeds).
- **Repeats:** most tasks ran twice per condition.

## Tasks and contamination check
There are 15 bug fixes: 11 in sympy (about 1,500 .py files) and 5 in astropy (about 1,000 .py files plus C extensions).
- **Cutoff check:** every fix commit is dated 2026-07-31 or later in upstream git, which is after the model's June 2026 cutoff. 14 of 15 issues were also opened after 2026-07-01. The exception is astropy-19895, opened 2026-06-10.
- **Selection:** I kept fixes that change one non-test .py file and say "fixes #N", and only those whose upstream tests fail before the fix and pass after it (FAIL_TO_PASS). Grading applies the agent's diff plus the upstream test changes and runs those tests.
- **No Vanrain seed:** Vanrain found no seed for sympy 30568, 30804 and 30913, so those prompts are identical in both conditions. They ran once per condition.
- **Dropped:** django (its issue tracker is blocked from the cloud), pandas, matplotlib and scikit-learn (few linked issues, heavy builds), and sympy-30499 (its tests hang).

## Results (54 runs, $35.67 for the runs)
| | none | Vanrain |
|---|---|---|
| Solved, sympy (17 runs each) | 14 | 13 |
| Solved, astropy (10 runs each) | 9 | 10 |
| Cost, sympy / astropy | $12.18 / $5.89 | $11.62 / $5.98 |
| Tokens (k), sympy / astropy | 19,535 / 9,416 | 17,954 / 8,902 |
| Model calls, sympy / astropy | 202 / 107 | 185 / 97 |
| Total cost | $18.07 | $17.60 |

- **Tokens:** across the 12 tasks with a Vanrain context, the median change was -8% (mean -6.5%), and calls fell 280 to 254. The median cost change was only -1%.
- **Noise:** repeat runs of the same prompt differ by a median of 10% in tokens. The -8% is inside run-to-run noise, so it is a weak signal at best.
- **Solves:** they are the same overall (23 of 27 each way). sympy-30999 failed in all 4 runs: the agents broke existing slice tests. It also cost $8.3 of the $35.67 total.

## Per task (mean of repeats)
| Task | Vanrain context | Cost none | Cost Vanrain | Tokens none (k) | Tokens Vanrain (k) | Calls none | Calls Vanrain | Solved none | Solved Vanrain |
|---|---|---|---|---|---|---|---|---|---|
| astropy__astropy-19895 | yes | $0.5 | $0.48 | 801 | 657 | 9.2 | 7.5 | 2/2 | 2/2 |
| astropy__astropy-20173 | yes | $0.61 | $0.61 | 1107 | 1014 | 12.5 | 11.0 | 2/2 | 2/2 |
| astropy__astropy-20489 | yes | $0.45 | $0.46 | 630 | 608 | 7.5 | 7.0 | 2/2 | 2/2 |
| astropy__astropy-20664 | yes | $0.76 | $0.72 | 1182 | 1001 | 13.0 | 10.5 | 2/2 | 2/2 |
| astropy__astropy-20704 | yes | $0.63 | $0.72 | 988 | 1172 | 11.2 | 12.5 | 1/2 | 2/2 |
| sympy__sympy-30335 | yes | $0.66 | $0.62 | 1232 | 1085 | 14.0 | 12.0 | 2/2 | 1/2 |
| sympy__sympy-30507 | yes | $0.56 | $0.56 | 899 | 837 | 10.0 | 9.2 | 2/2 | 2/2 |
| sympy__sympy-30568 | no | $0.5 | $0.49 | 788 | 793 | 9.5 | 9.5 | 1/1 | 1/1 |
| sympy__sympy-30804 | no | $0.55 | $0.54 | 956 | 955 | 11.0 | 11.0 | 1/1 | 1/1 |
| sympy__sympy-30884 | yes | $0.46 | $0.48 | 665 | 651 | 8.0 | 7.5 | 2/2 | 2/2 |
| sympy__sympy-30913 | no | $0.41 | $0.42 | 616 | 616 | 7.5 | 7.5 | 1/1 | 1/1 |
| sympy__sympy-30999 | yes | $2.21 | $1.93 | 3645 | 3256 | 29.8 | 27.2 | 0/2 | 0/2 |
| sympy__sympy-31096 | yes | $0.4 | $0.44 | 538 | 562 | 6.5 | 6.5 | 2/2 | 2/2 |
| sympy__sympy-31130 | yes | $0.51 | $0.53 | 721 | 666 | 8.5 | 7.5 | 2/2 | 2/2 |
| sympy__sympy-31272 | yes | $0.55 | $0.52 | 887 | 736 | 10.0 | 8.5 | 1/2 | 1/2 |

## Takeaway
In larger repos the effect looks like the recent-issues pilot: Vanrain saves a few calls and tokens, but each Claude Code call carries about 70k tokens of fixed context, so cost barely moves. The tasks were mostly easy, with 5 to 14 calls per run.

A real test needs harder tasks, a leaner agent harness, or a cheaper model, so that exploration dominates the cost.
