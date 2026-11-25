"""Build the first message for one pilot run session (task x condition)."""
import json, sys
from pathlib import Path
DATA = '/home/user/vanrain/eval/data/swebench_lite.jsonl'
CTX = Path('/home/user/pilot/contexts')
TEMPLATE = """\
This is one run of a benchmark. Work alone: no subagents, no web search or web fetch, no GitHub API, do not push or open pull requests.

First set up the repository with exactly this command (one commit of history, no remote):

```
mkdir -p ~/task && cd ~/task && git init -q && git remote add origin https://github.com/{repo}.git && git fetch -q --depth 1 origin {base} && git checkout -q FETCH_HEAD && git remote remove origin
```

You are working in a Python repository checked out at ~/task.
Fix the issue below. Edit the source files; do not add or change tests.
When you are done, stop.

## Issue

{issue}
{context}
## When you finish

Your final message must be only the output of `cd ~/task && git diff`, inside one ```diff block, with nothing else.
"""
def build(iid, cond):
    row = next(json.loads(l) for l in open(DATA) if f'"{iid}"' in l)
    ctx = ''
    if cond != 'none':
        txt = (CTX / f'{iid}.{cond}.md').read_text(encoding='utf-8')
        ctx = f'\n{txt}' if txt.strip() else ''
    return TEMPLATE.format(repo=row['repo'], base=row['base_commit'],
                           issue=row['problem_statement'].strip(), context=ctx)
if __name__ == '__main__':
    iid, cond = sys.argv[1], sys.argv[2]
    out = Path('/home/user/pilot/prompts') / f'{iid}.{cond}.md'
    out.write_text(build(iid, cond), encoding='utf-8'); print(out, len(out.read_text())//4, 'tokens approx')
