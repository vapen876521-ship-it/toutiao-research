import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT=Path('output_details'); OUT.mkdir(exist_ok=True)
ITEMS=[
 ('article','7673466869773287977'),
 ('article','7673356385198883347'),
 ('thread','1873448253700099'),
 ('thread','1873446750901248'),
]
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
s=requests.Session();s.headers.update(HEADERS)
rows=[]
for kind,gid in ITEMS:
 urls=[
   f'https://www.toutiao.com/group/{gid}/',
   f'https://www.toutiao.com/article/{gid}/',
   f'https://www.toutiao.com/w/{gid}/',
 ]
 for url in urls:
  try:
   r=s.get(url,timeout=20,allow_redirects=True); text=r.text; soup=BeautifulSoup(text,'lxml')
   body=soup.get_text('\n',strip=True)
   article=soup.find('article')
   article_text=article.get_text('\n',strip=True) if article else ''
   imgs=[]
   for im in soup.find_all('img'):
    src=im.get('src') or im.get('data-src') or ''
    if src:imgs.append(src)
   terms={k:text.count(k) for k in ['article-content','publish_time','group_id','image_list','content','comment_count','digg_count','forward_count']}
   scripts=[]
   for i,sc in enumerate(soup.find_all('script')):
    b=(sc.string or sc.get_text() or '')
    if any(k in b for k in ['article-content','group_id','publish_time','image_list','comment_count','digg_count']):
     scripts.append({'i':i,'prefix':b[:3500]})
     if len(scripts)>=6:break
   rows.append({'kind':kind,'gid':gid,'requested':url,'status':r.status_code,'final_url':r.url,'bytes':len(r.content),'title':soup.title.get_text(strip=True) if soup.title else '', 'body_chars':len(body),'body_prefix':body[:2000],'article_chars':len(article_text),'article_prefix':article_text[:4000],'image_count_dom':len(imgs),'image_samples':imgs[:20],'terms':terms,'scripts':scripts})
  except Exception as e:
   rows.append({'kind':kind,'gid':gid,'requested':url,'status':'ERROR','error':repr(e)})
  time.sleep(1)
(OUT/'details_probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:v for k,v in x.items() if k not in ('scripts','body_prefix','article_prefix','image_samples')} for x in rows],ensure_ascii=False,indent=2))
