import json, subprocess, time
seen = {}; out = open('issues.jsonl', 'w')
for line in open('linked.txt'):
    r, h, dt, n, s = line.rstrip('\n').split('|', 4)
    if (r, n) in seen: continue
    seen[(r, n)] = 1
    q = f'repo:{r} is:issue {n}'
    res = subprocess.run(['gh', 'api', '-X', 'GET', 'search/issues', '-f', f'q={q}', '-f', 'per_page=50'], capture_output=True, text=True)
    try: items = json.loads(res.stdout).get('items', [])
    except Exception: items = []
    it = next((i for i in items if str(i['number']) == n), None)
    if it:
        out.write(json.dumps({'repo': r, 'fix_commit': h, 'fix_date': dt, 'issue': int(n), 'title': it['title'],
                              'created_at': it['created_at'], 'body': it['body'] or '', 'subject': s}) + '\n'); out.flush()
    time.sleep(2.2)
