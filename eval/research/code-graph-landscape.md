# Code-graph tools: landscape check (2026-11-25)

Purpose: plan section 9 risk "similar code-graph tools already exist". Web research only; repo unchanged.

## Comparison

| Tool | Parser | Edges | Ranking / selection | Explicit token budget | Detail varies by distance | Change impact | Published benchmarks | Stars (as fetched) |
|---|---|---|---|---|---|---|---|---|
| **Aider repo map** | tree-sitter tags (def/ref queries) | file→file def/ref only | personalized PageRank (chat/mentioned files boosted) | Yes, `--map-tokens` (default ~1k) | No. Uniform signature lines for whatever fits | No | None | (Aider itself not checked) |
| **codebase-memory-mcp** (DeusData) | tree-sitter, 66–162 langs, + LSP-style type resolution | ~20 kinds: CALLS, IMPORTS, INHERITS, IMPLEMENTS, HTTP_CALLS, DATA_FLOWS… with confidence scores | BM25 + embeddings + graph diffusion; BFS for traces | No (row caps only) | No | Yes (`detect_changes`, risk class) | arXiv 2603.27277: answer quality 0.83 vs 0.92 for a file-exploring agent, ~10x fewer tokens (~1k vs ~10k/question), 2.1x fewer tool calls. 31 repos, Opus 4.6, **single grader** | 49.2k; last commit 2026-10-17 (checked by hand) |
| **code-review-graph** | tree-sitter + fallbacks, ~30 langs | CALLS, IMPORTS, inheritance, tests-for, framework edges; EXTRACTED/INFERRED | FTS5 + vector hybrid, BFS/DFS, Leiden, betweenness | Yes for traversal only | No | Yes (impact radius, risk scores) | ~63–65x median token reduction vs **all-source baseline** (they call it an upper bound). Impact F1 0.69 (circular ground truth). Multi-hop 10/11. Own doc lists incremental-update divergence on 7/7 edit kinds | 32.9k; last commit ~2026-11-11 (checked by hand) |
| **CodeGraphContext** | tree-sitter (+SCIP for C/C++, C#) | CALLS, imports, inheritance | Not described | No | No | Yes (by example) | ~62% smaller output format; "100% LLM comprehension" with no method | 4.4k |
| **sdsrss/code-graph-mcp** | tree-sitter, 6 full langs | calls, imports, inheritance, impls, refs, HTTP routes | BM25 + vectors (RRF), recursive CTE traversal | Yes (`max_tokens`), drops by caller-count rank | No (`compact` flag drops bodies globally) | Yes | Latency only; tool-call reduction table is hand-estimated | 86 |
| **cgraphy** | tree-sitter, 7 full langs | calls, imports, inheritance, git co-change | PageRank + FTS5, optional embeddings | Yes, greedy expansion "stops exactly at budget" | No | Yes (+ affected tests) | SWE-bench Lite 14 vs 8 of 57 resolved, "400+ runs" (method page blocked, **unverified**) | 0 |
| **budget-aware-mcp** | regex (or CodeGraphContext tree-sitter) | calls, imports, inheritance, usage | BFS by hop from anchor, alphabetical within hop | Yes (`max_tokens`) | No, inclusion by hop only | Yes | Latency only | 24 |
| **suatkocar/codegraph** | tree-sitter, 32 langs | not listed | BM25 + embeddings (RRF), PageRank / personalized PageRank | Yes, "4-tier budget" (tiers undefined) | Unclear, possibly tiers | Yes (blast radius) | 68% fewer tokens on one 11-file TS project, 5 tasks | 18 |
| **tree-sitter-analyzer** | tree-sitter, 13 langs | callers/callees, inheritance, imports | BM25 + cosine rerank | No | No | Yes (+ affected tests) | None | 61 |
| **Sourcegraph Cody** | static analysis (unnamed); tree-sitter for autocomplete only | call sites, implementations (no schema) | Zoekt keyword + embeddings + graph retrievers → trained pointwise ranker | Yes, greedy top-N into budget ("like knapsack") | No, full snippets only | No | None (paper and blog are qualitative) | n/a |
| **Cursor** | "syntactic chunks" (parser not named) | None | Own embedding model + grep as agent tools | Not stated | No | No | Semantic search: +12.5% QA accuracy (6.5–23.5% by model); A/B +0.3% code retention (+2.6% on 1k+ file repos) | n/a |
| **Continue** | tree-sitter AST chunking | None ("graph relations" was future work) | Embeddings + keyword, LLM rerank (25 → 5) | No, counts only | No | No | None. `@Codebase` now deprecated in favour of agent tools | n/a |

## Verdict

**The gap is real but narrower than the plan states.**

1. **Change-impact is not a differentiator.** Nearly every MCP code-graph server ships blast-radius / impact queries, often with risk scores and affected tests. Keep it as a feature, drop it from the pitch.
2. **A token budget alone is not a differentiator.** Aider, Cody, code-graph-mcp, cgraphy, budget-aware-mcp and codegraph all select under a budget. They do it greedily (rank, then fill).
3. **Variable detail by graph distance is the open gap.** No tool I found returns full source near the target, signatures further out and nothing beyond, chosen together as one budget-optimal decision. Aider uses one detail level (signature lines). The others include or exclude whole units. codegraph's "4-tier budget" is the only possible overlap and its tiers are undocumented.
4. **Rigorous benchmarks are the second open gap.** Published numbers are vendor-run, single-grader, or use a weak baseline (all source files). Nobody reports task success vs tokens against the realistic baselines: a grep/explore agent, Aider's repo map and a greedy budgeted graph. The Codebase-Memory paper is the strongest result, and it shows a quality *cost* (0.83 vs 0.92) for 10x fewer tokens. That is exactly the trade-off Vanrain claims to improve.

**Does the angle hold?** Yes, if it is framed as "same success as an exploring agent at a fraction of the tokens, and better than greedy budgeted selection at the same budget", and that is measured. The risk is that the big projects (33k–49k stars, both committed to within the last ~6 weeks) could add a detail tier quickly, so the moat is the measured result and the benchmark, not the feature. Suggested baselines for milestone benchmarks: Aider repo map (via RepoMapper or Aider), a greedy BFS-under-budget variant of Vanrain itself, and a grep-only agent.

## Could not verify

- Star counts and last commits for codebase-memory-mcp (49.2k, 2026-10-17) and code-review-graph (32.9k, ~2026-11-11) were confirmed by hand on 2026-11-25. Both are popular and active.
- Last-commit dates for the smaller repos: GitHub pages did not show them, and the session has no GitHub API access, so their activity is not confirmed.
- cgraphy's SWE-bench claim: its method page was blocked to automated fetching.
- User complaints: no issue trackers were read in depth. The only documented weaknesses are self-reported (code-review-graph incremental-update divergence and over-flagging impact; code-graph-mcp blind spots on dynamic dispatch; Aider's repo map leaving file choice to the user).
- Cody's current product status (e.g. Free/Pro changes) was not checked.
- Cursor's parser and any token budget are not stated by Cursor.

## Sources

- Aider: https://aider.chat/2023/10/22/repomap.html , https://deepwiki.com/Aider-AI/aider/4.1-repository-mapping , https://github.com/Cryect/RepoMapper
- https://github.com/DeusData/codebase-memory-mcp , https://arxiv.org/html/2603.27277v1
- https://github.com/tirth8205/code-review-graph (+ docs/REPRODUCING.md)
- https://github.com/CodeGraphContext/CodeGraphContext
- https://github.com/sdsrss/code-graph-mcp , https://github.com/pmgarg/cgraphy , https://github.com/Doorman11991/budget-aware-mcp , https://github.com/suatkocar/codegraph , https://github.com/aimasteracc/tree-sitter-analyzer , https://github.com/cmillstead/codesight-mcp
- Cody: https://sourcegraph.com/blog/lessons-from-building-ai-coding-assistants-context-retrieval-and-evaluation , https://arxiv.org/html/2408.05344v1 , https://sourcegraph.com/blog/how-cody-understands-your-codebase
- Cursor: https://cursor.com/blog/secure-codebase-indexing , https://cursor.com/blog/semsearch
- Continue: https://docs.continue.dev/reference/deprecated-codebase , https://blog.continue.dev/accuracy-limits-of-codebase-retrieval
