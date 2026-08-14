import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT=Path('output_profiles'); OUT.mkdir(exist_ok=True)
AUTHORS=[
 ('光明网','http://toutiao.com/m5806115967/'),
 ('馋嘴屋','http://toutiao.com/m1824382144865289/'),
 ('美猴王海门光明南路','http://toutiao.com/m1738225326104576/'),
 ('陆弃','http://toutiao.com/m50650238814/'),
 ('权谋家','http://toutiao.com/m3517249816/'),
]
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36','Accept-Language':'zh-CN,zh;q=0.9'}
TERMS=['fans','fans_count','follower','followers','followers_count','follow_count','粉丝','获赞','关注']
s=requests.Session(); s.headers.update(HEADERS)
rows=[]
for name,url in AUTHORS:
    for candidate in [url.replace('http://','https://'), url.replace('http://toutiao.com','https://www.toutiao.com')]:
        try:
            r=s.get(candidate,timeout=25,allow_redirects=True)
            text=r.text
            soup=BeautifulSoup(text,'lxml')
            title=soup.title.get_text(strip=True) if soup.title else ''
            term_counts={t:text.lower().count(t.lower()) for t in TERMS}
            matches={}
            patterns={
              'fans_count':r'"(?:fans_count|fansCount|follower_count|followers_count|followersCount)"\s*:\s*"?(\d+)',
              'following_count':r'"(?:follow_count|following_count|followingCount)"\s*:\s*"?(\d+)',
            }
            for k,p in patterns.items():
                vals=re.findall(p,text,re.I); matches[k]=vals[:20]
            scripts=[]
            for i,sc in enumerate(soup.find_all('script')):
                body=(sc.string or sc.get_text() or '')
                low=body.lower()
                if any(t.lower() in low for t in TERMS):
                    scripts.append({'i':i,'prefix':body[:2500]})
                    if len(scripts)>=8: break
            rows.append({'name':name,'requested':candidate,'status':r.status_code,'final_url':r.url,'bytes':len(r.content),'title':title,'term_counts':term_counts,'matches':matches,'scripts':scripts})
        except Exception as e:
            rows.append({'name':name,'requested':candidate,'status':'ERROR','error':repr(e)})
        time.sleep(1)
(OUT/'profiles_probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:v for k,v in x.items() if k!='scripts'} for x in rows],ensure_ascii=False,indent=2))
