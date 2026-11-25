"""Prepare recent tasks: checkout at fix^, gold/test patches, venv, FAIL_TO_PASS/PASS_TO_PASS."""
import json, os, re, subprocess, sys
os.environ['SETUPTOOLS_SCM_PRETEND_VERSION']='99.0.0'
from pathlib import Path
PICK = {'sympy/sympy': [31272,31130,31096,30999,30913,30884,30790,30804,30568,30499,30507,30335,30014,30343,30268,30272],
        'astropy/astropy': [20664,20704,20489,20360,20173,19895]}
W = Path('/home/user/rwork'); W.mkdir(exist_ok=True)
def sh(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True)
    if check and r.returncode: raise RuntimeError(f'{cmd}\n{r.stderr[-2000:]}')
    return r.stdout
def is_test(p): return bool(re.search(r'(^|/)(tests?|testing)/|(^|/)test_', p))
rows = [json.loads(l) for l in open('issues2.jsonl')]
out = open(sys.argv[1] if False else 'tasks2.jsonl', 'a')
only = sys.argv[1:]
def one(r):
    iid = f"{r['repo'].replace('/', '__')}-{r['issue']}"
    src = Path(r['repo'].replace('/', '_')).resolve(); h = r['fix_commit']
    base = sh(f'git -C {src} rev-parse {h}^').strip()
    files = sh(f'git -C {src} show --format= --name-only {h}').split()
    tfiles = [f for f in files if is_test(f)]; gfiles = [f for f in files if not is_test(f) and not f.startswith(('changelog', 'doc/whatsnew', 'doc/', 'docs/'))]
    gold = sh(f'git -C {src} diff {base} {h} -- ' + ' '.join(gfiles))
    test = sh(f'git -C {src} diff {base} {h} -- ' + ' '.join(tfiles))
    d = W / iid
    if r['repo']=='sympy/sympy': sh(f'git -C {src} tag -f sympy-99.0.{r["issue"]} {base}')
    if not d.exists():
        sh(f'git -C {src} worktree add -q --detach {d} {base}')
    v = W / f'{iid}.venv'
    if not v.exists() or r['repo']=='pytest-dev/pytest':
        sh(f'uv venv -q -p /usr/bin/python3.12 {v}')
        extra = {'sympy/sympy': 'pytest mpmath hypothesis', 'astropy/astropy': 'pytest pytest-doctestplus pytest-astropy-header pytest-remotedata hypothesis scipy pyyaml', 'pytest-dev/pytest': 'hypothesis xmlschema pygments requests', 'pylint-dev/pylint': 'pytest pytest-timeout typing_extensions', 'pydata/xarray': 'pytest netCDF4 scipy dask cftime'}[r['repo']]
        sh(f'VIRTUAL_ENV={v} uv pip install --no-config -q -e . {extra}', cwd=d)
    # which tests to run
    targets = set()
    for f in tfiles:
        if f.endswith('.py') and (re.search(r'(^|/)test_[^/]*\.py$', f) or (r['repo']=='pytest-dev/pytest' and f.startswith('testing/') and 'conftest' not in f and '/example_scripts/' not in f)): targets.add(f)
        elif r['repo'] == 'pylint-dev/pylint' and f.startswith('tests/functional/'):
            targets.add(f'tests/test_functional.py -k {Path(f).stem}')
    ADD = '-o addopts=""' if r['repo'] in ('pydata/xarray','astropy/astropy') else ''
    def run():
        res = {}
        for t in sorted(targets):
            o = sh(f'timeout 900 {v}/bin/python -m pytest -rA -q -p no:cacheprovider {ADD} {t} 2>&1 | tail -3000', cwd=d, check=False)
            for m in re.finditer(r'^(PASSED|FAILED|ERROR) (\S+)', o, re.M): res[m.group(2)] = m.group(1)
        return res
    sh('git reset -q --hard && git clean -qfd', cwd=d)
    Path(f'/tmp/t_{iid}.patch').write_text(test); sh(f'git apply /tmp/t_{iid}.patch', cwd=d)
    before = run()
    Path(f'/tmp/g_{iid}.patch').write_text(gold); sh(f'git apply /tmp/g_{iid}.patch', cwd=d)
    after = run()
    sh('git reset -q --hard && git clean -qfd', cwd=d)
    f2p = sorted(k for k, s in after.items() if s == 'PASSED' and before.get(k) != 'PASSED')
    p2p = sorted(k for k, s in after.items() if s == 'PASSED' and before.get(k) == 'PASSED')
    rec = dict(instance_id=iid, repo=r['repo'], base_commit=base, fix_commit=h, fix_date=r['fix_date'], issue=r['issue'],
               issue_created=r['created_at'], problem_statement=f"{r['title']}\n{r['body']}", patch=gold, test_patch=test,
               targets=sorted(targets), FAIL_TO_PASS=f2p, PASS_TO_PASS=p2p, venv=str(v), checkout=str(d))
    out.write(json.dumps(rec) + '\n'); out.flush()
    print(iid, 'F2P', len(f2p), 'P2P', len(p2p), flush=True)

for r in rows:
    if r['issue'] not in PICK.get(r['repo'], []): continue
    iid = f"{r['repo'].replace('/', '__')}-{r['issue']}"
    if only and not any(o in iid for o in only): continue
    try: one(r)
    except Exception as e: print(iid, 'ERR', str(e)[-500:], flush=True)
