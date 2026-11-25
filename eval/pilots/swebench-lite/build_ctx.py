import json, sys
sys.path.insert(0, '/home/user/vanrain/eval')
from pathlib import Path
from harness import tasks, conditions
from harness.checkout import checkout
conds = sys.argv[1].split(',')
out = Path('/home/user/pilot/contexts'); out.mkdir(parents=True, exist_ok=True)
pool = {t.instance_id: t for t in tasks.load_instances('/home/user/vanrain/eval/data/swebench_lite.jsonl')}
ids = [i['instance_id'] for i in tasks.read_task_file('/home/user/vanrain/eval/tasks/pilot.json')['instances']]
for iid in ids:
    t = pool[iid]; repo = checkout(t, '/home/user/work')
    for c in conds:
        try:
            inj = conditions.build(c, repo, t.problem_statement, 2000)
            (out / f"{iid}.{c}.md").write_text(inj.text, encoding='utf-8')
            print(iid, c, inj.tokens, list(inj.seeds)[:5], flush=True)
        except Exception as e:
            print(iid, c, 'ERROR', e, flush=True)
