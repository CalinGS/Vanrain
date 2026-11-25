import json, sys
from pathlib import Path
T = Path('/home/user/pilot/make_prompt.py').read_text().split('TEMPLATE = """\\\n')[1].split('"""')[0]
out = Path('/mnt/project-files/Vanrain/pilot-large/prompts'); out.mkdir(parents=True, exist_ok=True)
for l in open('tasks2.jsonl'):
    t = json.loads(l)
    if not t['FAIL_TO_PASS']: continue
    if sys.argv[1:] and t['instance_id'] not in sys.argv[1:]: continue
    for cond, rep in [(c, r) for r in ('', '.r2') for c in ('none', 'vanrain_sig_first')]:
        ctx = ''
        if cond != 'none':
            txt = Path(f"contexts/{t['instance_id']}.{cond}.md").read_text()
            ctx = f'\n{txt}' if txt.strip() else ''
        p = out / f"{t['instance_id']}.{cond}{rep}.md"
        txt = (T.replace('## When you finish\n\n', '## When you finish\n\nAlso save that diff with `cd ~/task && git diff > /mnt/project-files/Vanrain/pilot-large/out/' + p.stem + '.diff`.\n').format(repo=t['repo'], base=t['base_commit'], issue=t['problem_statement'].strip(), context=ctx))
        if t['repo']=='sympy/sympy': txt = txt.replace('git remote remove origin', 'git remote remove origin && git tag sympy-99.0', 1)
        p.write_text(txt)
        print(p, len(txt)//4)
