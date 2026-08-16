import csv,json,re
from pathlib import Path

ROOT=Path('category_deep_merged')
CSV=ROOT/'toutiao_recent_native_posts.csv'

DIRECT=[
'赖清德','石油美元','欧美给中国挖','集体造反','美媒终于说实话','美国这次真输了','碾压美国',
'日本永远追不上中国','各国媒体纷纷承认','不需再向世界证明','中国领土恐怕最终会全收回',
'美战略','美债换成人民币','美财长天塌了','美欧拒发适航证','中东一战','美国弹药家底',
'扣押中国人','中国重拳出击，抓捕','宁做美国鬼不做中国人','港独','国力角度','扶不起的阿斗',
'苏联养','美国全面衰落','西方战略专家','阻击华为','国家还大力砸钱发展','为什么中国不是发达国家',
'明明已经世界第二了','中国不是发达国家','没中国的命，却得了中国的“病”','没中国的命，却得了中国的病',
'第二战场突然打开','西方40年封锁','西方40年技术封锁','中国机床直接掀桌子'
]
COUNTRIES=[
'美国','日本','印度','俄罗斯','乌克兰','以色列','伊朗','菲律宾','台湾','朝鲜','韩国','欧盟','法国','英国','德国',
'加拿大','新西兰','澳大利亚','巴基斯坦','越南','波兰','欧洲','沙特','阿联酋','利比亚','土耳其','叙利亚',
'卡塔尔','伊拉克','阿富汗','巴勒斯坦','黎巴嫩','埃及','约旦','也门','印尼','马来西亚','新加坡','泰国',
'柬埔寨','缅甸','老挝','巴西','阿根廷','墨西哥'
]
GEO_CUES=[
'总统','总理','首相','政府','选举','外交','制裁','关税','军方','军事','导弹','航母','战机','防务','战争','冲突','停火',
'领土','军队','条约','投降','稀土','美债','反制','对决','靖国','驻军','反华','战败','侵略','主权','边境','联盟',
'谈判','战事','防长','对抗','统一','武统','和统','白宫','五角大楼','国会','北约','征税','反倾销','禁令','出口管制',
'封锁','击落','参战','贸易战','援助','中资','铁路项目','大豆','出口商品','试射','摊牌','发难','战略','石油美元',
'地缘','霸权','牌桌','造反','脱钩','封杀','适航证','国力','领土','军火','弹药'
]
STATE_RE=re.compile(r'(?:国家|我国|政府|公安部|最高检|教育部|商务部|国务院|国家邮政局)')
POLICY_RE=re.compile(r'(?:施行|政策|规定|禁烧|一刀切|重拳出击|扫黑|反腐|医保|社保|延迟退休|退休年龄|出台|整治|立案调查|想通了|发钱催生)')

def reason(row):
    t=(str(row.get('title') or '')+' '+str(row.get('abstract') or '')).strip()
    hits=[x for x in DIRECT if x in t]
    if hits:return 'direct:'+','.join(hits[:4])
    ch=[x for x in COUNTRIES if x in t]
    cu=[x for x in GEO_CUES if x in t]
    if ch and cu:return 'country+geopolitics:'+','.join(ch[:3])+'|'+','.join(cu[:3])
    if STATE_RE.search(t) and POLICY_RE.search(t):return 'state+policy'
    return ''

with CSV.open(encoding='utf-8-sig',newline='') as f:
    rows=list(csv.DictReader(f)); fields=list(rows[0].keys()) if rows else []
kept=[];removed=[]
for r in rows:
    why=reason(r)
    if why:
        r['final_exclusion_reason']=why;removed.append(r)
    else:kept.append(r)

def n(v):
    try:return int(float(v or 0))
    except:return 0
kept.sort(key=lambda r:(n(r.get('max_interaction')),n(r.get('interaction_sum'))),reverse=True)
with CSV.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(kept)
for name,cut in [('top10k',10000),('top3k',3000),('top1k',1000)]:
    with (ROOT/f'{name}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows([r for r in kept if n(r.get('max_interaction'))>=cut])
remfields=fields+(['final_exclusion_reason'] if 'final_exclusion_reason' not in fields else [])
with (ROOT/'final_excluded_politics.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=remfields,extrasaction='ignore');w.writeheader();w.writerows(removed)
bycat={}
for r in kept:bycat[r.get('category','?')]=bycat.get(r.get('category','?'),0)+1
summary={
 'input_rows':len(rows),'removed_final_audit':len(removed),'unique_strict_recent_native':len(kept),
 'hot_10k':sum(n(r.get('max_interaction'))>=10000 for r in kept),
 'hot_3k':sum(n(r.get('max_interaction'))>=3000 for r in kept),
 'hot_1k':sum(n(r.get('max_interaction'))>=1000 for r in kept),
 'max':{k:max([n(r.get(k)) for r in kept] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum']},
 'by_category':dict(sorted(bycat.items(),key=lambda x:x[1],reverse=True)),
 'top20':[{k:r.get(k) for k in ['category','group_id','post_url','title','media_name','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum']} for r in kept[:20]],
 'removed_top':[{k:r.get(k) for k in ['group_id','title','max_interaction','interaction_sum','final_exclusion_reason']} for r in sorted(removed,key=lambda r:n(r.get('max_interaction')),reverse=True)[:50]]
}
(ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
