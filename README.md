# Vanrain

Feed your coding agent the code that's connected, not whole files.

Vanrain parses a repository into a typed graph of functions, classes and modules,
then answers one question: given a target and a token budget, which code should the
agent see, and at what level of detail? Close neighbours get full source, further
ones get signatures only, and the rest is left out.

> **Status:** pre-alpha. Milestones 0 to 5 (setup, data model, Python parser and
> resolver, cached code graph, BFS selector and markdown renderer, CLI) are done.

## Install

Vanrain needs Python 3.10 or newer and has no runtime dependencies. From a clone:

```bash
python -m pip install -e .
```

This puts a `vanrain` command on your path (`python -m vanrain` works too).

## Usage

Run the commands from the root of any Python repository, or pass `--root DIR`.

```bash
vanrain index                              # build the graph, cached in .vanrain/
vanrain context Order.total --budget 2000  # markdown context for a symbol
vanrain find total                         # which symbols a name could mean
vanrain stats                              # size and shape of the graph
```

`context` takes one or more symbols. A symbol is a full id (`shop.models.Order.total`)
or its trailing dotted parts (`Order.total`, `total`). If a name matches nothing or
several symbols, Vanrain lists the candidates and exits with code 1; `vanrain find`
shows them with their files and lines. The seed is shown in full when it fits, and
the budget is spent on the connected code nearest to it.

| Option | Commands | Default | Meaning |
| --- | --- | --- | --- |
| `--budget N` | context | 2000 | token budget for the selected code |
| `--strategy S` | context | `signatures_first` | `signatures_first` (signatures for everything near, then full source nearest first), `full_first`, or `signatures_only` |
| `--root DIR` | all | `.` | repository to read |
| `--no-cache` | all | off | index from scratch and write nothing to `.vanrain/` |
| `--top N` | stats | 10 | rows in the most-called and largest lists |

The cache lives in `.vanrain/cache.json` under the root; only files that changed
are parsed again. Add `.vanrain/` to your `.gitignore`.

Example on pytest's own source (79 files, 2,444 symbols, 7,132 edges, about 2.3 s
to index and 0.1 s with the cache):

```text
$ vanrain context getfixturevalue --budget 2000
# Context for _pytest.fixtures.FixtureRequest.getfixturevalue

49 symbols (1 full, 48 signatures), 1997 of 2000 tokens. ...

## _pytest/fixtures.py
...
```

### Python API

The CLI only calls `vanrain.api`, which you can use directly:

```python
from vanrain import api

ctx = api.get_context("path/to/repo", ["Order.total"], budget=2000)
print(ctx.text)            # the markdown
print(ctx.selection.items) # what was chosen, at which detail
```

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
  api.py            public Python API (what the CLI calls)
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
