import csv,json,re,time,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9','Referer':'https://www.toutiao.com/'}
HOT='https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc'
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']

def walk(x,path='$'):
    if isinstance(x,dict):
        yield path,x
        for k,v in x.items():yield from walk(v,path+'.'+str(k))
    elif isinstance(x,list):
        for i,v in enumerate(x):yield from walk(v,f'{path}[{i}]')

def n(v):
    try:return int(float(v or 0))
    except:return 0

def compact_row(d,topic_title,rank,hot_value):
    if not isinstance(d,dict) or not d.get('group_id'):return None
    title=str(d.get('title') or d.get('abstract') or d.get('content') or '').strip()
    if not title or any(x in title for x in BLOCK):return None
    detail=str(d.get('detail_schema') or d.get('inner_schema') or '')
    if 'awemevideo' in detail or 'xiaoshipin' in detail or 'hotsoon_video' in detail:return None
    url=str(d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or d.get('source_url') or d.get('display_url') or '')
    media=str(d.get('media_name') or d.get('source') or '')
    media_url=str(d.get('media_url') or d.get('user_source_url') or '')
    native=('toutiao.com' in url or url.startswith('sslocal://thread_detail') or detail.startswith('sslocal://thread_detail'))
    if not native and not (media and media_url and ('toutiao.com' in media_url or media_url.startswith('/'))):return None
    return {'hot_rank':rank,'hot_topic':topic_title,'hot_value':hot_value,'group_id':str(d.get('group_id')),'title':re.sub(r'\s+',' ',title)[:1000],'abstract':re.sub(r'\s+',' ',str(d.get('abstract') or d.get('description') or ''))[:3000],'article_url':url,'media_name':media,'media_url':media_url,'user_id':str(d.get('user_id') or d.get('media_creator_id') or ''),'publish_time':n(d.get('publish_time') or d.get('create_time') or d.get('behot_time')),'read_count':n(d.get('read_count')),'digg_count':n(d.get('digg_count')),'comment_count':n(d.get('comment_count')),'forward_count':n(d.get('forward_count')),'repin_count':n(d.get('repin_count')),'image_count':n(d.get('image_count')),'content_schema_type':str(d.get('content_schema_type') or ''),'detail_schema':detail[:400]}

s=requests.Session();s.headers.update(H)
r=s.get(HOT,timeout=30); data=r.json(); items=data.get('data') or []
# Keep all hot-board records for provenance, but skip political/military topics when crawling details.
hot_rows=[]; native_rows=[]; detail_report=[]
for i,item in enumerate(items,1):
    title=str(item.get('Title') or '').strip();cid=str(item.get('ClusterIdStr') or item.get('ClusterId') or '')
    hv=n(item.get('HotValue'));u=str(item.get('Url') or '') or (f'https://www.toutiao.com/trending/{cid}/' if cid else '')
    hot_rows.append({'rank':i,'cluster_id':cid,'title':title,'hot_value':hv,'url':u,'label':item.get('Label') or item.get('LabelDesc') or '','category':item.get('Category') or ''})
    if not cid or any(x in title for x in BLOCK):continue
    urls=[]
    for z in [u,f'https://www.toutiao.com/trending/{cid}/']:
        if z and z not in urls:urls.append(z)
    got=[]
    for du in urls:
        try:
            rr=s.get(du,timeout=30,allow_redirects=True);html=rr.text;soup=BeautifulSoup(html,'lxml')
            for sc in soup.find_all('script'):
                b=(sc.string or sc.get_text() or '').strip()
                if not b:continue
                payload=[]
                if b.startswith('{') or b.startswith('['):payload=[b.rstrip(';')]
                elif '"extraData"' in b:
                    m=re.search(r'(\{"extraData".*\})',b,re.S)
                    if m:payload=[m.group(1)]
                for p in payload:
                    try:x=json.loads(p)
                    except:continue
                    for path,d in walk(x):
                        z=compact_row(d,title,i,hv)
                        if z:got.append(z)
            # Also collect direct Toutiao content links from rendered server HTML as evidence.
            hrefs=[]
            for a in soup.find_all('a',href=True):
                h=a.get('href','')
                if 'toutiao.com' in h and any(k in h for k in ['/article/','/group/','/w/']):hrefs.append(h)
            detail_report.append({'rank':i,'topic':title,'requested':du,'status':rr.status_code,'bytes':len(rr.content),'final_url':rr.url,'native_objects':len(got),'content_hrefs':list(dict.fromkeys(hrefs))[:100],'term_counts':{k:html.count(k) for k in ['group_id','digg_count','comment_count','forward_count','repin_count','article_url','sslocal://thread_detail','awemevideo']}})
            if got:break
        except Exception as e:detail_report.append({'rank':i,'topic':title,'requested':du,'error':repr(e)})
        time.sleep(.5)
    native_rows.extend(got)
    time.sleep(.7)
# dedupe native rows
best={}
for z in native_rows:
    gid=z['group_id'];rank=(max(z['digg_count'],z['comment_count'],z['forward_count'],z['repin_count']),z['read_count'],len(z['abstract']))
    if gid not in best or rank>best[gid][0]:best[gid]=(rank,z)
out=[v[1] for v in best.values()]
with open('hot_board.json','w',encoding='utf-8') as f:json.dump(hot_rows,f,ensure_ascii=False,indent=2)
with open('hot_trending_report.json','w',encoding='utf-8') as f:json.dump(detail_report,f,ensure_ascii=False,indent=2)
fields=['hot_rank','hot_topic','hot_value','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','image_count','content_schema_type','detail_schema']
with open('hot_native_posts.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
print(json.dumps({'hot_status':r.status_code,'hot_count':len(items),'nonpolitical_topics_crawled':len({x['rank'] for x in detail_report}),'unique_native_posts':len(out),'max_read':max([x['read_count'] for x in out] or [0]),'max_digg':max([x['digg_count'] for x in out] or [0]),'max_comment':max([x['comment_count'] for x in out] or [0]),'max_forward':max([x['forward_count'] for x in out] or [0]),'max_repin':max([x['repin_count'] for x in out] or [0]),'top_hot':[{'rank':x['rank'],'title':x['title'],'hot_value':x['hot_value']} for x in hot_rows[:10]]},ensure_ascii=False,indent=2))
