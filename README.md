# Vanrain

Feed your coding agent the code that's connected, not whole files.

Vanrain parses a repository into a typed graph of functions, classes and modules,
then answers one question: given a target and a token budget, which code should the
agent see, and at what level of detail? Close neighbours get full source, further
ones get signatures only, and the rest is left out.

> **Status:** pre-alpha. Milestones 0 to 4 (setup, data model, Python parser and
> resolver, cached code graph, BFS selector and markdown renderer) are done. There
> is no CLI yet; the Python API works:
>
> ```python
> from vanrain.graph import index
> from vanrain.seeds import resolve_seed
> from vanrain.selector import BFSSelector
> from vanrain.render import render
>
> graph = index("path/to/repo").graph
> seed = resolve_seed(graph, "Order.total")
> print(render(BFSSelector().select(graph, [seed], budget=2000), graph, "path/to/repo"))
> ```

## Layout

```
src/vanrain/
  model.py          shared data types (the contract between all modules)
  parsers/          one parser per language (Python via ast first)
  resolver.py       references -> typed edges
  graph.py          CodeGraph + cache
  seeds.py          task -> start nodes
  selector/         budgeted traversal strategies (BFS first)
  tokens.py         token counting
  render.py         Selection -> text for the LLM
  cli.py            command-line interface (thin, no logic)
  mcp_server.py     MCP server (later)
tests/
  fixtures/tiny_repo/   hand-made repo whose correct graph is known
eval/                   benchmark, never shipped in the package
docs/model-review.md    what changed from the draft schema, and why
```

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

## License

MIT
