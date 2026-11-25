import json, collections, statistics as st
C={}; 
for l in open('costs2.tsv'):
    i,c,_,cost,cr,cw,o,inp=l.split('\t'); C[(i,c)]=dict(cost=float(cost),tok=int(cr)+int(cw)+int(o)+int(inp),calls=int(inp)/2)
G={}
for l in open('grades2.tsv'):
    i,c,j=l.rstrip('\n').split('\t'); G[(i,c)]=json.loads(j)['resolved']
noseed={'sympy__sympy-30913','sympy__sympy-30804','sympy__sympy-30568'}
assert set(C)==set(G), (set(C)^set(G))
rows=collections.defaultdict(lambda: collections.defaultdict(list))
for (i,c),v in C.items():
    cond='none' if c.startswith('none') else 'vanrain'
    rows[i][cond].append({**v,'ok':G[(i,c)]})
print('total runs',len(C),'cost',round(sum(v['cost'] for v in C.values()),2))
def agg(sel):
    out={}
    for cond in ('none','vanrain'):
        rs=[r for i in sel for r in rows[i][cond]]
        out[cond]=(len(rs),sum(r['ok'] for r in rs),round(sum(r['cost'] for r in rs),2),round(sum(r['tok'] for r in rs)/1e3),round(sum(r['calls'] for r in rs)))
    return out
for name,sel in [('sympy',[i for i in rows if 'sympy' in i]),('astropy',[i for i in rows if 'astropy' in i]),('all',list(rows)),('seeded',[i for i in rows if i not in noseed]),('seeded excl 30999',[i for i in rows if i not in noseed and i!='sympy__sympy-30999'])]:
    print(name,agg(sel))
# per-task paired ratios (mean tokens), seeded
ch=[];chc=[]
print('task ctx  none_cost van_cost none_tok van_tok none_calls van_calls solved_none solved_van')
for i in sorted(rows):
    n,v=rows[i]['none'],rows[i]['vanrain']
    m=lambda rs,k: st.mean(r[k] for r in rs)
    if i not in noseed: ch.append(m(v,'tok')/m(n,'tok')-1); chc.append(m(v,'cost')/m(n,'cost')-1)
    print(i, 'no' if i in noseed else 'yes', round(m(n,'cost'),2),round(m(v,'cost'),2),round(m(n,'tok')/1e3),round(m(v,'tok')/1e3),round(m(n,'calls'),1),round(m(v,'calls'),1),f"{sum(r['ok'] for r in n)}/{len(n)}",f"{sum(r['ok'] for r in v)}/{len(v)}")
print('seeded tasks',len(ch),'median tok change',round(st.median(ch)*100,1),'mean',round(st.mean(ch)*100,1),'median cost change',round(st.median(chc)*100,1))
# noise: r1 vs r2 same condition
d=[]
for (i,c),v in C.items():
    if c.endswith('.r2'):
        a=C[(i,c[:-3])]['tok']; d.append(abs(v['tok']/a-1))
print('rep noise |r2/r1-1| tokens median',round(st.median(d)*100,1),'max',round(max(d)*100,1), 'n',len(d))
