import sys; sys.path.insert(0,'/home/user/vanrain/eval')
import importlib, types
from pathlib import Path
from harness import tasks, conditions
from harness.checkout import checkout
out=Path('/home/user/pilot/contexts')
pool={t.instance_id:t for t in tasks.load_instances('/home/user/vanrain/eval/data/swebench_lite.jsonl')}
for i in tasks.read_task_file('/home/user/vanrain/eval/tasks/pilot.json')['instances']:
    t=pool[i['instance_id']]; repo=checkout(t,'/home/user/work')
    try:
        inj=conditions.build('aider_map',repo,t.problem_statement,2000)
        (out/f"{t.instance_id}.aider_map.md").write_text(inj.text,encoding='utf-8'); print(t.instance_id,inj.tokens,flush=True)
    except Exception as e: print(t.instance_id,'ERROR',e,flush=True)
