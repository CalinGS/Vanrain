# Learned edge weights, first try (2026-11-25)

Script: `eval/research/tools/weight_search.py`. 324 single-function commits
(click 85, flask 49, httpx 78, requests 112). Ranking = Dijkstra with a cost per
(edge kind, direction), divided by edge confidence. Selection = signatures first until
the budget is spent. Score = share of needed symbols visible. Random search, 1,500 trials,
optimised at 2,000 tokens.

| Split | Budget | BFS train | Learned train | BFS **test** | Learned **test** |
|---|---|---|---|---|---|
| tune click+flask, test httpx+requests | 1,000 | 32.5% | 36.7% | 33.9% | 33.1% |
| | 2,000 | 46.4% | 53.3% | 47.5% | **48.3%** |
| | 4,000 | 61.2% | 63.5% | 59.2% | 60.6% |
| tune httpx+requests, test click+flask | 1,000 | 33.9% | 36.7% | 32.5% | 33.9% |
| | 2,000 | 47.5% | 59.3% | 46.4% | **49.3%** |
| | 4,000 | 59.2% | 67.2% | 61.2% | 59.1% |

## Reading

- On repos it was tuned on, the gain looks big (+7 to +12 points at 2,000 tokens).
- On unseen repos it mostly vanishes: +1 to +3 points at 2,000 tokens, and slightly worse in two cells.
- The two splits learned different weights. Agreement only on: "who imports me" should be followed late or not at all, and outgoing calls/imports are cheap.
- So edge-kind weights alone mostly fit quirks of the training repos. They are not where the big win is.

## Next ideas (not done)

- Richer signals per candidate: git co-change with the target, recent edits, name/word overlap with the target, same file/class, how many callers it has. Fit a small model (logistic regression) on those.
- More data: thousands of commits across 15–20 repos, so tuning can generalise.
- Keep the honest split (tune on some repos, report on others).
