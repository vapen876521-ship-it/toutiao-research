import csv,json,re,sys
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('deep_artifacts')
OUT=Path('category_deep_merged');OUT.mkdir(exist_ok=True)
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','俄罗斯','乌克兰','以色列','加沙','伊朗','特朗普','普京','泽连斯基','拜登','选举','总统','总理','首相','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防','北约','美军','联合国','侵略','制裁','中美','美日']
START_TS=int(datetime(2026,7,14,16,0,tzinfo=timezone.utc).timestamp())
END_TS=int(datetime(2026,8,14,16,0,tzinfo=timezone.utc).timestamp())

def n(v):
    try:return int(float(v or 0))
    except:return 0

def b(v):return str(v).strip().lower() in ('1','true','yes')

def valid(r):
    gid=str(r.get('group_id') or '')
    url=str(r.get('post_url') or '')
    typ=str(r.get('post_type') or '')
    title=str(r.get('title') or '')
    pub=n(r.get('publish_time'))
    if not re.fullmatch(r'\d{15,20}',gid):return False
    if typ not in ('article','weitoutiao'):return False
    if not re.match(r'^https://www\.toutiao\.com/(article|w)/\d+/?$',url):return False
    if not (START_TS<=pub<END_TS):return False
    if any(x in title for x in BLOCK):return False
    if str(r.get('content_schema_type') or '')=='3':return False
    return True

files=list(ROOT.rglob('strict_category_*.csv'))
rows=[]
for f in files:
    with f.open(encoding='utf-8-sig',newline='') as fh:
        for r in csv.DictReader(fh):
            if valid(r):
                for k in ['followers_count','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum','image_count']:
                    r[k]=n(r.get(k))
                r['institution_hint']=b(r.get('institution_hint'))
                r['_source_file']=str(f)
                rows.append(r)

def rank(r):
    return (n(r.get('max_interaction')),n(r.get('interaction_sum')),sum(bool(r.get(k)) for k in ['media_name','user_id','followers_count','abstract','image_count']))
best={}
for r in rows:
    gid=r['group_id']
    if gid not in best or rank(r)>rank(best[gid]):best[gid]=r
uniq=list(best.values())
uniq.sort(key=lambda r:(n(r.get('max_interaction')),n(r.get('interaction_sum'))),reverse=True)
fields=['category','group_id','post_url','post_type','provenance','title','abstract','media_name','user_id','followers_count','institution_hint','publish_time','publish_time_source','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum','image_count','content_schema_type','response_url','json_path','_source_file']
with (OUT/'toutiao_recent_native_posts.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(uniq)
for name,cut in [('top10k',10000),('top3k',3000),('top1k',1000)]:
    ss=[r for r in uniq if n(r.get('max_interaction'))>=cut]
    with (OUT/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(ss)
bycat={}
for r in uniq:bycat[r.get('category','?')]=bycat.get(r.get('category','?'),0)+1
summary={
 'source_csv_files':len(files),'raw_valid_rows':len(rows),'unique_strict_recent_native':len(uniq),
 'article':sum(r.get('post_type')=='article' for r in uniq),'weitoutiao':sum(r.get('post_type')=='weitoutiao' for r in uniq),
 'institution_hint':sum(bool(r.get('institution_hint')) for r in uniq),'individual_hint':sum(not bool(r.get('institution_hint')) for r in uniq),
 'followers_resolved':sum(n(r.get('followers_count'))>0 for r in uniq),
 'hot_10k':sum(n(r.get('max_interaction'))>=10000 for r in uniq),'hot_3k':sum(n(r.get('max_interaction'))>=3000 for r in uniq),'hot_1k':sum(n(r.get('max_interaction'))>=1000 for r in uniq),
 'max':{k:max([n(r.get(k)) for r in uniq] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum']},
 'by_category':dict(sorted(bycat.items(),key=lambda x:x[1],reverse=True)),
 'top20':[ {k:r.get(k) for k in ['category','group_id','post_url','post_type','title','media_name','followers_count','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']} for r in uniq[:20] ]
}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
