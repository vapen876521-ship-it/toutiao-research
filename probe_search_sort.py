import json,re,time,requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode

H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
URL='https://so.toutiao.com/search'
KEYWORD='真实经历'
VARIANTS=[
 ('base',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc'}),
 ('sort0',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','sort_type':'0'}),
 ('sort1',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','sort_type':'1'}),
 ('sort2',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','sort_type':'2'}),
 ('sort_hot',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','sort_type':'hot'}),
 ('order_hot',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','order':'hot'}),
 ('sort_hot2',{'keyword':KEYWORD,'pd':'weitoutiao','dvpf':'pc','sort':'hot'}),
]

def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)

def parse(html):
    soup=BeautifulSoup(html,'lxml');rows=[]
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
                if not isinstance(d,dict) or not d.get('group_id'):continue
                detail=str(d.get('detail_schema') or '')
                if 'awemevideo' in detail or 'xiaoshipin' in detail or 'hotsoon_video' in detail:continue
                rows.append({'gid':str(d.get('group_id')),'title':str(d.get('title') or d.get('abstract') or '')[:200],'digg':d.get('digg_count'),'comment':d.get('comment_count'),'forward':d.get('forward_count'),'repin':d.get('repin_count'),'read':d.get('read_count'),'detail_schema':detail[:150]})
    seen=set();out=[]
    for r in rows:
        if r['gid'] in seen:continue
        seen.add(r['gid']);out.append(r)
    return out

s=requests.Session();s.headers.update(H);result=[]
for name,params in VARIANTS:
    r=s.get(URL,params=params,timeout=30,allow_redirects=True)
    html=r.text;rows=parse(html)
    contexts=[]
    for pat in [r'.{0,120}(?:sort_type|sortType|sort_order|sortOrder|order_by|orderBy).{0,220}',r'.{0,80}(?:最新|热度|排序|时间排序|按时间|最热).{0,160}']:
        for m in re.finditer(pat,html,re.I|re.S):
            txt=re.sub(r'\s+',' ',m.group(0))[:450]
            if txt not in contexts:contexts.append(txt)
            if len(contexts)>=20:break
        if len(contexts)>=20:break
    result.append({'name':name,'requested':params,'status':r.status_code,'final_url':r.url,'bytes':len(r.content),'rows':rows[:30],'contexts':contexts})
    time.sleep(1)
open('search_sort_probe.json','w',encoding='utf-8').write(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps([{'name':x['name'],'status':x['status'],'bytes':x['bytes'],'gids':[r['gid'] for r in x['rows'][:10]],'metrics':[{'digg':r['digg'],'comment':r['comment'],'repin':r['repin'],'read':r['read']} for r in x['rows'][:10]],'contexts':x['contexts'][:5]} for x in result],ensure_ascii=False,indent=2))
