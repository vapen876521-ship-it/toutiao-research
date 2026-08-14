import json,re,time,requests
from bs4 import BeautifulSoup
from urllib.parse import quote

KEYWORDS=['内容过于真实','装修避坑','准大一','夫妻 日常vlog']
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
KEEP=['group_id','title','abstract','digg_count','comment_count','forward_count','repin_count','publish_time','article_url','source_url','share_url','media_name','media_url','user_id','content_schema_type','has_video','display_type','content_type','data_type','app_name','platform','site_name','aweme_id','video_id']

def walk(x,path='$'):
    if isinstance(x,dict):
        yield path,x
        for k,v in x.items(): yield from walk(v,path+'.'+str(k))
    elif isinstance(x,list):
        for i,v in enumerate(x): yield from walk(v,f'{path}[{i}]')

s=requests.Session();s.headers.update(H);out=[]
for kw in KEYWORDS:
    r=s.get('https://www.toutiao.com/search/?keyword='+quote(kw),timeout=30)
    objs=[];soup=BeautifulSoup(r.text,'lxml')
    for sc in soup.find_all('script'):
        b=(sc.string or sc.get_text() or '').strip()
        if not b: continue
        payload=[]
        if b.startswith('{') or b.startswith('['): payload=[b.rstrip(';')]
        elif '"extraData"' in b:
            m=re.search(r'(\{"extraData".*\})',b,re.S)
            if m: payload=[m.group(1)]
        for p in payload:
            try:x=json.loads(p)
            except:continue
            for path,d in walk(x):
                if not isinstance(d,dict) or not d.get('group_id'):continue
                try:likes=int(float(d.get('digg_count') or 0))
                except:likes=0
                if likes<10000:continue
                fields={k:d.get(k) for k in KEEP if k in d}
                for k,v in d.items():
                    lk=str(k).lower()
                    if any(t in lk for t in ['source','url','schema','type','app','platform','site','aweme','video','media','user']) and k not in fields:
                        if isinstance(v,(str,int,float,bool)) or v is None: fields[k]=v
                objs.append({'path':path,'keys':sorted(d.keys()),'fields':fields})
    out.append({'keyword':kw,'status':r.status_code,'count':len(objs),'objects':objs[:30]})
    time.sleep(1)
open('native_source_probe.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False)[:50000])
