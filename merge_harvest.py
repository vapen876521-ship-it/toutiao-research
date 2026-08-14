import csv
import json
from pathlib import Path

root=Path('harvest_downloads')
out=Path('harvest_merged')
out.mkdir(exist_ok=True)
files=sorted(root.rglob('shard_*.csv'))
rows=[]
for p in files:
    if p.name.endswith('_report.json'): continue
    with p.open('r',encoding='utf-8-sig',newline='') as f:
        rows.extend(csv.DictReader(f))

def n(v):
    try: return int(float(v)) if v not in ('',None,'None') else 0
    except: return 0

best={}
for r in rows:
    gid=r.get('group_id','')
    if not gid: continue
    score=n(r.get('read_count'))+10*n(r.get('digg_count'))+20*n(r.get('comment_count'))+20*n(r.get('forward_count'))
    richness=sum(bool(r.get(k)) for k in ['article_url','media_name','media_url','publish_time','abstract'])
    key=(score,richness)
    if gid not in best or key>best[gid][0]: best[gid]=(key,r)
uniq=[v[1] for v in best.values()]
uniq.sort(key=lambda r:(n(r.get('comment_count')),n(r.get('digg_count')),n(r.get('forward_count')),n(r.get('read_count'))),reverse=True)
fields=list(uniq[0].keys()) if uniq else []
if fields:
    with (out/'candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(uniq)
(out/'candidates.json').write_text(json.dumps(uniq,ensure_ascii=False,indent=2),encoding='utf-8')
summary={
    'shard_files':len(files),'raw_rows':len(rows),'unique_rows':len(uniq),
    'nonzero_read':sum(n(r.get('read_count'))>0 for r in uniq),
    'nonzero_digg':sum(n(r.get('digg_count'))>0 for r in uniq),
    'nonzero_comment':sum(n(r.get('comment_count'))>0 for r in uniq),
    'nonzero_forward':sum(n(r.get('forward_count'))>0 for r in uniq),
    'top_comment':sorted([n(r.get('comment_count')) for r in uniq],reverse=True)[:20],
    'top_digg':sorted([n(r.get('digg_count')) for r in uniq],reverse=True)[:20],
    'top_forward':sorted([n(r.get('forward_count')) for r in uniq],reverse=True)[:20]
}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
