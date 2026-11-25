import json, sys
from pathlib import Path
T = Path('/home/user/pilot/make_prompt.py').read_text().split('TEMPLATE = """\\\n')[1].split('"""')[0]
out = Path('/mnt/project-files/Vanrain/pilot-recent/prompts'); out.mkdir(parents=True, exist_ok=True)
for l in open('tasks.jsonl'):
    t = json.loads(l)
    if sys.argv[1:] and t['instance_id'] not in sys.argv[1:]: continue
    for cond in ('none', 'vanrain_sig_first'):
        ctx = ''
        if cond != 'none':
            txt = Path(f"contexts/{t['instance_id']}.{cond}.md").read_text()
            ctx = f'\n{txt}' if txt.strip() else ''
        p = out / f"{t['instance_id']}.{cond}.md"
        p.write_text(T.replace('## When you finish\n\n', '## When you finish\n\nAlso save that diff with `cd ~/task && git diff > /mnt/project-files/Vanrain/pilot-recent/out/' + p.stem + '.diff`.\n').format(repo=t['repo'], base=t['base_commit'], issue=t['problem_statement'].strip(), context=ctx))
        print(p, len(p.read_text())//4)
