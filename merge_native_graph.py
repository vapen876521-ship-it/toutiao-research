import csv, glob, json, os
from pathlib import Path

OUT=Path('native_graph_merged');OUT.mkdir(exist_ok=True)
files=glob.glob('downloaded/**/native_graph_*.csv',recursive=True)
rows=[]
for f in files:
    try:
        with open(f,encoding='utf-8-sig',newline='') as h: rows += list(csv.DictReader(h))
    except Exception as e: print('skip',f,e)

def iv(r,k):
    try:return int(float(r.get(k) or 0))
    except:return 0

def bv(r,k):return str(r.get(k,'')).lower() in ('1','true','yes')

def score(r):return (iv(r,'max_interaction'),iv(r,'like_count')+iv(r,'comment_count')+iv(r,'forward_count')+iv(r,'repin_count'),len(r.get('body_text','')))
best={}
for r in rows:
    key=r.get('url') or r.get('post_id')
    if not key:continue
    if key not in best or score(r)>score(best[key]):best[key]=r
uniq=list(best.values())
valid=[r for r in uniq if bv(r,'recent_verified') and not bv(r,'political_risk')]
valid.sort(key=lambda r:(iv(r,'max_interaction'),iv(r,'like_count'),iv(r,'comment_count')),reverse=True)
fields=sorted({k for r in valid for k in r.keys()})
with (OUT/'native_recent_valid.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(valid)
for threshold,name in [(10000,'native_hot_10k.csv'),(3000,'native_hot_3k.csv'),(1000,'native_hot_1k.csv')]:
    sub=[r for r in valid if iv(r,'max_interaction')>=threshold]
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(sub)
summary={
 'shard_csv_files':len(files),'raw_rows':len(rows),'unique_rows':len(uniq),'recent_verified_nonpolitical':len(valid),
 'hot_10k':sum(iv(r,'max_interaction')>=10000 for r in valid),'hot_3k':sum(iv(r,'max_interaction')>=3000 for r in valid),'hot_1k':sum(iv(r,'max_interaction')>=1000 for r in valid),
 'individual_hint_count':sum(not bv(r,'institution_hint') for r in valid),
 'max_like':max([iv(r,'like_count') for r in valid] or [0]),'max_comment':max([iv(r,'comment_count') for r in valid] or [0]),'max_forward':max([iv(r,'forward_count') for r in valid] or [0]),'max_repin':max([iv(r,'repin_count') for r in valid] or [0]),'max_interaction':max([iv(r,'max_interaction') for r in valid] or [0]),
 'top20':[{'url':r.get('url'),'title':r.get('title','')[:150],'author':r.get('author_hint') or r.get('media_name_structured'),'like':iv(r,'like_count'),'comment':iv(r,'comment_count'),'forward':iv(r,'forward_count'),'repin':iv(r,'repin_count'),'max':iv(r,'max_interaction'),'institution_hint':bv(r,'institution_hint')} for r in valid[:20]]
}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
