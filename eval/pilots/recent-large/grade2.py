"""grade.py IID DIFF_FILE -> JSON verdict (F2P all pass and P2P all pass = resolved)."""
import json, re, subprocess, sys
from pathlib import Path
iid, diff = sys.argv[1], Path(sys.argv[2]).read_text()
t = [x for x in map(json.loads, open('/home/user/recent/tasks2.jsonl')) if x['instance_id'] == iid and x['FAIL_TO_PASS']][-1]
d, v = t['checkout'], t['venv']
sh = lambda c: subprocess.run(c, cwd=d, shell=True, capture_output=True, text=True)
sh('git reset -q --hard && git clean -qfd')
Path('/tmp/a_'+iid+'.patch').write_text(diff); Path('/tmp/tg_'+iid+'.patch').write_text(t['test_patch'])
ok = sh('git apply /tmp/a_'+iid+'.patch').returncode == 0
if not ok: ok = sh('patch -p1 -s < /tmp/a_'+iid+'.patch').returncode == 0
res = {}
if ok:
    sh('git checkout -q -- $(git diff --name-only | grep -E "(^|/)(tests?|testing)/|test_" ) 2>/dev/null')  # drop agent test edits
    sh('git apply /tmp/tg_'+iid+'.patch')
    add = '-o addopts=""' if t['repo'] in ('pydata/xarray','astropy/astropy') else ''
    for tg in t['targets']:
        o = sh(f'{v}/bin/python -m pytest -rA -q -p no:cacheprovider {add} {tg} 2>&1 | tail -3000').stdout
        for m in re.finditer(r'^(PASSED|FAILED|ERROR) (\S+)', o, re.M): res[m.group(2)] = m.group(1)
sh('git reset -q --hard && git clean -qfd')
f2p = sum(res.get(k) == 'PASSED' for k in t['FAIL_TO_PASS']); p2p = sum(res.get(k) == 'PASSED' for k in t['PASS_TO_PASS'])
print(json.dumps(dict(instance_id=iid, applied=ok, f2p=f"{f2p}/{len(t['FAIL_TO_PASS'])}", p2p=f"{p2p}/{len(t['PASS_TO_PASS'])}",
      resolved=ok and f2p == len(t['FAIL_TO_PASS']) and p2p == len(t['PASS_TO_PASS']))))
