import csv,json,re,time,requests
from bs4 import BeautifulSoup
from urllib.parse import quote,urlparse

KEYWORDS=['装修','装修避坑','租房','买房','职场','毕业生','大学生活','家庭教育','夫妻','中年生活','养老','美食','早餐','外卖','食品安全','农村生活','县城生活','旅行','自驾游','猫','狗','手机','AI','新能源车','生活妙招','真实经历','消费体验','网购','副业','亲子','育儿']
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']

def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)

def n(v):
    try:return int(float(v or 0))
    except:return 0

def native(d):
    if not isinstance(d,dict) or not d.get('group_id'):return None
    title=str(d.get('title') or d.get('abstract') or '').strip()
    if not title or any(x in title for x in BLOCK):return None
    schema=str(d.get('detail_schema') or '')
    if 'awemevideo' in schema or 'xiaoshipin' in schema or 'hotsoon_video' in schema:return None
    if d.get('has_video') is True:return None
    ctype=str(d.get('content_schema_type') or '')
    if ctype=='3':return None
    url=str(d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or d.get('source_url') or '')
    media=str(d.get('media_name') or d.get('source') or '')
    media_url=str(d.get('media_url') or d.get('user_source_url') or '')
    # Require positive native provenance: Toutiao URL, thread detail, or an author profile on a non-video result.
    native_url=('toutiao.com' in url or url.startswith('sslocal://thread_detail'))
    author_proof=bool(media and media_url and ('toutiao.com' in media_url or media_url.startswith('/')))
    if not (native_url or author_proof):return None
    return {
      'group_id':str(d.get('group_id')),'title':re.sub(r'\s+',' ',title)[:500],'abstract':re.sub(r'\s+',' ',str(d.get('abstract') or ''))[:2000],
      'article_url':url,'media_name':media,'media_url':media_url,'user_id':str(d.get('user_id') or d.get('media_creator_id') or ''),
      'publish_time':n(d.get('publish_time') or d.get('create_time') or d.get('behot_time')),
      'read_count':n(d.get('read_count')),'digg_count':n(d.get('digg_count')),'comment_count':n(d.get('comment_count')),'forward_count':n(d.get('forward_count')),'repin_count':n(d.get('repin_count')),
      'image_count':n(d.get('image_count')),'content_schema_type':ctype,'has_video':d.get('has_video'),'detail_schema':schema[:300]
    }

s=requests.Session();s.headers.update(H);rows=[];report=[]
for kw in KEYWORDS:
    for endpoint in ['https://www.toutiao.com/search/','https://so.toutiao.com/search']:
        try:
            r=s.get(endpoint,params={'keyword':kw,'pd':'information','source':'search_subtab_switch','dvpf':'pc'},timeout=30,allow_redirects=True)
            soup=BeautifulSoup(r.text,'lxml');found=[]
            for sc in soup.find_all('script'):
                b=(sc.string or sc.get_text() or '').strip()
                if not b:continue
                ps=[]
                if b.startswith('{') or b.startswith('['):ps=[b.rstrip(';')]
                elif '"extraData"' in b:
                    m=re.search(r'(\{"extraData".*\})',b,re.S)
                    if m:ps=[m.group(1)]
                for p in ps:
                    try:x=json.loads(p)
                    except:continue
                    for d in walk(x):
                        z=native(d)
                        if z:found.append(z)
            best={}
            for z in found:
                gid=z['group_id'];score=sum(bool(z.get(k)) for k in ['article_url','media_name','media_url','publish_time','read_count','digg_count','comment_count','repin_count'])
                if gid not in best or score>best[gid][0]:best[gid]=(score,z)
            found=[v[1] for v in best.values()]
            for z in found:z['query']=kw;z['endpoint']=urlparse(r.url).netloc;rows.append(z)
            report.append({'keyword':kw,'endpoint':urlparse(r.url).netloc,'status':r.status_code,'bytes':len(r.content),'native_rows':len(found),'max_read':max([z['read_count'] for z in found] or [0]),'max_digg':max([z['digg_count'] for z in found] or [0]),'max_comment':max([z['comment_count'] for z in found] or [0]),'max_forward':max([z['forward_count'] for z in found] or [0]),'max_repin':max([z['repin_count'] for z in found] or [0])})
        except Exception as e:report.append({'keyword':kw,'endpoint':endpoint,'error':repr(e)})
        time.sleep(.7)
# global dedupe
best={}
for z in rows:
    gid=z['group_id'];rank=(max(z['digg_count'],z['comment_count'],z['forward_count'],z['repin_count']),z['read_count'])
    if gid not in best or rank>best[gid][0]:best[gid]=(rank,z)
out=[v[1] for v in best.values()]
fields=['query','endpoint','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','image_count','content_schema_type','has_video','detail_schema']
with open('information_native_probe.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
open('information_native_report.json','w',encoding='utf-8').write(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'queries':len(KEYWORDS),'requests':len(report),'unique_native':len(out),'max_read':max([z['read_count'] for z in out] or [0]),'max_digg':max([z['digg_count'] for z in out] or [0]),'max_comment':max([z['comment_count'] for z in out] or [0]),'max_forward':max([z['forward_count'] for z in out] or [0]),'max_repin':max([z['repin_count'] for z in out] or [0]),'ge_10k_read':sum(z['read_count']>=10000 for z in out),'ge_1k_digg':sum(z['digg_count']>=1000 for z in out),'ge_1k_comment':sum(z['comment_count']>=1000 for z in out),'ge_1k_repin':sum(z['repin_count']>=1000 for z in out)},ensure_ascii=False,indent=2))
