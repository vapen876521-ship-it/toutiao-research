import csv,json,re
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('deep_artifacts')
OUT=Path('category_deep_merged');OUT.mkdir(exist_ok=True)
LEADERS=['习近平','毛泽东','毛主席','周恩来','朱德','邓小平','江泽民','胡锦涛','朱镕基','温家宝','李克强','刘少奇','刘伯承','彭德怀','陈毅','贺龙','林彪','叶剑英','粟裕','蒋介石','孙中山','宋庆龄','特朗普','拜登','普京','泽连斯基','高市早苗','高市','马科斯','莫迪','杜特尔特','郑丽文','李在明']
PARTY_STATE=['党中央','政治局','中央军委','国务院','外交部','国防部','全国人大','全国政协','省委书记','市委书记','党委书记','纪委书记','纪检监察','严重违纪违法','审查调查','商务部','白宫','五角大楼','美国国会','参议院','众议院','北约']
MILITARY=['解放军','美军','印军','军方','导弹','航母','战机','军工','核武','防务协议','驻军','抗美援朝','解放战争','抗日战争','日本侵华','731部队','黄岩岛','仁爱礁','台海','南海争端','军籍','军演','军事基地','军队','部队','战役','开战','停火','防长','国防部长','现役军人','武警','烈士','军舰','轰-6','歼-20','歼20','歼10','F16']
GEOPOL_DIRECT=['中方','美方','日方','印方','俄方','对华','反制','制裁','贸易战','中美','中日','中印','亲美','反华','靖国神社','藏南','台湾当局','台独','台湾独立','南海','外交博弈','国际局势','对抗中国','武统','和统','祖国统一','统一进入','大陆布下','辱华','投美','背叛中国','官方全球征缴令']
COUNTRIES=['美国','日本','印度','俄罗斯','乌克兰','以色列','伊朗','菲律宾','台湾','朝鲜','韩国','欧盟','法国','英国','德国','加拿大','新西兰','澳大利亚','巴基斯坦','越南','波兰','欧洲']
GEO_CUES=['总统','总理','首相','政府','选举','外交','制裁','关税','军方','军事','导弹','航母','战机','防务','战争','冲突','停火','领土','军队','条约','投降','稀土','美债','反制','对决','靖国','无核','驻军','反华','战败','侵略','军事基地','开第一枪','威胁','让步','主权','边境','联盟','谈判','战事','防长','现役军人','对抗','统一','武统','和统','白宫','五角大楼','国会','北约','商务部','征税','反倾销','禁令','出口管制','封锁','叛逃','叛徒','汉奸','击落','参战','军舰','战力','贸易战','制裁','公告','停手','关系']
START_TS=int(datetime(2026,7,14,16,0,tzinfo=timezone.utc).timestamp())
END_TS=int(datetime(2026,8,14,16,0,tzinfo=timezone.utc).timestamp())

def n(v):
    try:return int(float(v or 0))
    except:return 0

def b(v):return str(v).strip().lower() in ('1','true','yes')

def political(r):
    if str(r.get('category') or '')=='history':return True
    t=(str(r.get('title') or '')+' '+str(r.get('abstract') or '')).strip()
    if any(x in t for x in LEADERS+PARTY_STATE+MILITARY+GEOPOL_DIRECT):return True
    if any(e in t for e in COUNTRIES) and any(k in t for k in GEO_CUES):return True
    return False

def valid(r):
    gid=str(r.get('group_id') or '')
    url=str(r.get('post_url') or '')
    typ=str(r.get('post_type') or '')
    pub=n(r.get('publish_time'))
    prov=str(r.get('provenance') or '')
    src=str(r.get('source_url_raw') or '')
    if not re.fullmatch(r'\d{15,20}',gid):return False
    if typ not in ('article','weitoutiao'):return False
    if not re.match(r'^https://www\.toutiao\.com/(article|w)/\d+/?$',url):return False
    if not (START_TS<=pub<END_TS):return False
    if political(r):return False
    if str(r.get('content_schema_type') or '')=='3':return False
    if prov in ('feed_group_19digit','feed_item_19digit'):
        if not re.search(r'https?://(?:www\.)?toutiao\.com/(?:group|item)/'+re.escape(gid)+r'/?',src):return False
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
fields=['category','group_id','post_url','post_type','provenance','source_url_raw','title','abstract','media_name','user_id','followers_count','institution_hint','publish_time','publish_time_source','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum','image_count','content_schema_type','response_url','json_path','_source_file']
with (OUT/'toutiao_recent_native_posts.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(uniq)
for name,cut in [('top10k',10000),('top3k',3000),('top1k',1000)]:
    ss=[r for r in uniq if n(r.get('max_interaction'))>=cut]
    with (OUT/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(ss)
bycat={};byprov={}
for r in uniq:
    bycat[r.get('category','?')]=bycat.get(r.get('category','?'),0)+1
    byprov[r.get('provenance','?')]=byprov.get(r.get('provenance','?'),0)+1
summary={
 'source_csv_files':len(files),'raw_valid_rows':len(rows),'unique_strict_recent_native':len(uniq),
 'article':sum(r.get('post_type')=='article' for r in uniq),'weitoutiao':sum(r.get('post_type')=='weitoutiao' for r in uniq),
 'mapped_group_item':sum(r.get('provenance') in ('feed_group_19digit','feed_item_19digit') for r in uniq),
 'institution_hint':sum(bool(r.get('institution_hint')) for r in uniq),'individual_hint':sum(not bool(r.get('institution_hint')) for r in uniq),
 'followers_resolved':sum(n(r.get('followers_count'))>0 for r in uniq),
 'hot_10k':sum(n(r.get('max_interaction'))>=10000 for r in uniq),'hot_3k':sum(n(r.get('max_interaction'))>=3000 for r in uniq),'hot_1k':sum(n(r.get('max_interaction'))>=1000 for r in uniq),
 'max':{k:max([n(r.get(k)) for r in uniq] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum']},
 'by_category':dict(sorted(bycat.items(),key=lambda x:x[1],reverse=True)),
 'by_provenance':dict(sorted(byprov.items(),key=lambda x:x[1],reverse=True)),
 'top20':[ {k:r.get(k) for k in ['category','group_id','post_url','post_type','provenance','source_url_raw','title','media_name','followers_count','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']} for r in uniq[:20] ]
}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
