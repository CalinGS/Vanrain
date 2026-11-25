# Detail-level test, first run (2026-11-25)

Question: at the same token budget, does showing nearby code with *varying* detail beat
showing whole functions only, or signatures only?

## Setup

- Script: `/mnt/project-files/Vanrain/tools/detail_test.py` (offline, no LLM). Uses
  Vanrain milestone 3 (`index()` + `CodeGraph`) unchanged; nothing in the repo was modified.
- Tasks: 145 real commits from requests, click, httpx and flask that changed exactly one
  function in one file and added 1–40 lines.
- Target = the changed function, from the graph *before* the commit. Always shown in full.
- Answer key = repo functions/classes whose names appear in the added lines (code the
  author had to know about). Found by name matching, independent of Vanrain's resolver.
- Ranking: plain BFS over all edges, both directions, nearest first. Same for every strategy.
- Score = share of needed symbols the model can see (whole or signature).

## Results (mean over 145 tasks)

| Budget | Whole functions only | Signatures only | Mixed (dist 1 whole, rest sig) | Mixed2 (sig first, then upgrade) |
|---|---|---|---|---|
| 500 | 10% | 26% | 25% | 26% |
| 1,000 | 18% | 36% | 31% | 36% |
| 2,000 | 29% | 48% | 44% | 48% |
| 4,000 | 34% | 63% | 52% | 63% |

- Only 32 tasks used a symbol the function had not used before; on those, recall at 2,000 tokens was 4% (whole), 29% (signatures), 18% (mixed).
- Paired at 2,000 tokens: signatures-first beat whole-functions on 37 tasks and never lost. Mixed lost to signatures-only on 11 tasks and won on 1.
- Reading the target's whole file (median 7,205 tokens) finds only 33% of the needed symbols. The graph with signatures finds 48% using 2,000 tokens.
- Needed symbols are spread out: 75 at 1 hop, 71 at 2, 43 at 3, 51 at 4+.
- By repo at 2,000 tokens (whole / sig / mixed): click 31/47/39, flask 22/37/33, httpx 18/36/34, requests 30–47/58–72/58–69.

## What it means

1. **Graph + signatures clearly beats both whole functions and reading the file.** It shows about twice as much of the needed code at the same budget. That supports Vanrain's core idea.
2. **Full source for neighbours did not pay off here.** But this test cannot reward it: it only checks whether the model can *see* a symbol, not whether it needed the body. Whether bodies help has to be measured with an LLM on real tasks (plan milestone 6).
3. **Ranking matters more than detail right now.** Even at 4,000 tokens with ~114 signatures, 37% of needed code is missing, because plain BFS reaches it late. Better ranking (plan milestone 7: edge weights, recency) is the bigger lever.
4. "Mixed2" (signatures first, upgrade to whole only with spare budget) never hurts, so it is the safe default for milestone 4.

## Limits

- No LLM: measures visibility, not task success.
- Answer key by name matching is noisy (common names like `get` match many symbols).
- Small, single-function commits only; 4 repos, all HTTP/CLI libraries.
- Token counts use Vanrain's 4-chars-per-token estimate.
