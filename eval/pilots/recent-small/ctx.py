import json, sys
sys.path.insert(0, '/home/user/vanrain/eval')
from pathlib import Path
from harness import conditions
out = Path('/home/user/recent/contexts'); out.mkdir(exist_ok=True)
for l in open('/home/user/recent/tasks.jsonl'):
    t = json.loads(l)
    if sys.argv[1:] and t['instance_id'] not in sys.argv[1:]: continue
    p = out / f"{t['instance_id']}.vanrain_sig_first.md"
    if p.exists(): continue
    inj = conditions.build('vanrain_sig_first', t['checkout'], t['problem_statement'], 2000)
    p.write_text(inj.text, encoding='utf-8')
    print(t['instance_id'], inj.tokens, list(inj.seeds)[:4], flush=True)
