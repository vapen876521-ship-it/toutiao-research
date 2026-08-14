import asyncio
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.async_api import async_playwright

OUT = Path('current_trending_output')
OUT.mkdir(exist_ok=True)
HOT_URL = 'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
BLOCK = ['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']


def normalize_hot(data):
    arr = []
    if isinstance(data, dict):
        for k in ('data','Data','list','List'):
            if isinstance(data.get(k), list):
                arr = data[k]
                break
    if not arr and isinstance(data, list): arr = data
    out=[]
    for i,x in enumerate(arr,1):
        if not isinstance(x,dict): continue
        title = str(x.get('Title') or x.get('title') or x.get('Keyword') or x.get('keyword') or '')
        cluster = str(x.get('ClusterId') or x.get('cluster_id') or x.get('ClusterID') or '')
        url = str(x.get('Url') or x.get('url') or '')
        hot = x.get('HotValue') or x.get('hot_value') or x.get('Hot') or 0
        if not title: continue
        if any(t in title for t in BLOCK): continue
        if not url and cluster: url=f'https://www.toutiao.com/trending/{cluster}/'
        out.append({'rank':i,'title':title,'cluster_id':cluster,'url':url,'hot_value':hot})
    return out


def extract_post_links(links):
    posts={}
    for item in links:
        h=(item.get('h') or '').split('#')[0].rstrip('/') + '/'
        if re.fullmatch(r'https://www\.toutiao\.com/(?:article/\d+|w/\d+)/',h):
            posts.setdefault(h,[]).append((item.get('t') or '').strip())
    return posts


def best_text(texts):
    vals=[re.sub(r'\s+',' ',x).strip() for x in texts if x and not re.fullmatch(r'\d+|评论|源于文章|源于微头条|赞|分享',x.strip())]
    return max(vals,key=len) if vals else ''


def nearby_card(body, text):
    if not text: return ''
    needle=text[:50]
    pos=body.find(needle)
    if pos<0: return ''
    return re.sub(r'\s+',' ',body[max(0,pos-120):pos+min(1000,len(text)+450)]).strip()


def parse_visible_counts(card):
    # Conservative: only count a value if it is explicitly adjacent to a label.
    out={'visible_comment_count':0,'visible_share_count':0,'visible_like_count':0,'visible_favorite_count':0}
    patterns={
      'visible_comment_count':[r'(\d[\d万\.]*?)\s*评论',r'评论\s*(\d[\d万\.]*)'],
      'visible_share_count':[r'(\d[\d万\.]*?)\s*分享',r'分享\s*(\d[\d万\.]*)'],
      'visible_like_count':[r'(\d[\d万\.]*?)\s*赞',r'赞\s*(\d[\d万\.]*)'],
      'visible_favorite_count':[r'(\d[\d万\.]*?)\s*收藏',r'收藏\s*(\d[\d万\.]*)'],
    }
    def val(s):
        try:
            if '万' in s:return int(float(s.replace('万',''))*10000)
            return int(float(s))
        except:return 0
    for key,pats in patterns.items():
        for p in pats:
            m=re.search(p,card)
            if m:
                out[key]=val(m.group(1));break
    return out

async def main():
    hot=requests.get(HOT_URL,headers=HEADERS,timeout=30).json()
    topics=normalize_hot(hot)
    report=[]; rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent=HEADERS['User-Agent'])
        for idx,t in enumerate(topics,1):
            page=await ctx.new_page(); rec=dict(t); rec['posts']=[]
            try:
                r=await page.goto(t['url'],wait_until='domcontentloaded',timeout=60000)
                await page.wait_for_timeout(3500)
                # One light scroll to make sure lazy related content is rendered, without trying to reproduce API calls.
                await page.mouse.wheel(0,1600); await page.wait_for_timeout(1200)
                body=await page.locator('body').inner_text()
                links=await page.locator('a').evaluate_all("els=>els.slice(0,1000).map(a=>({t:(a.innerText||'').trim(),h:a.href})).filter(x=>x.h)")
                rec['status']=r.status if r else None;rec['final_url']=page.url;rec['body_chars']=len(body)
                m=re.search(r'热门事件阅读量\s*([\d\.]+)\s*万',body)
                rec['event_views']=int(float(m.group(1))*10000) if m else 0
                for url,texts in extract_post_links(links).items():
                    txt=best_text(texts)
                    card=nearby_card(body,txt)
                    counts=parse_visible_counts(card)
                    typ='article' if '/article/' in url else 'weitoutiao'
                    pid=re.search(r'/(?:article|w)/(\d+)/',url).group(1)
                    row={'hot_rank':t['rank'],'hot_title':t['title'],'hot_value':t['hot_value'],'event_views':rec['event_views'],'post_type':typ,'post_id':pid,'url':url,'visible_text':txt[:3000],'card_context':card[:3500],**counts}
                    rows.append(row);rec['posts'].append(row)
            except Exception as e:rec['error']=repr(e)
            finally:
                await page.close()
            report.append(rec)
            if idx%10==0: print(json.dumps({'progress':f'{idx}/{len(topics)}','raw_posts':len(rows)},ensure_ascii=False),flush=True)
        await browser.close()
    # dedupe post URLs, preserving strongest event/card evidence
    best={}
    for x in rows:
        score=(max(x['visible_comment_count'],x['visible_share_count'],x['visible_like_count'],x['visible_favorite_count']),len(x['visible_text']),x['event_views'])
        if x['url'] not in best or score>best[x['url']][0]:best[x['url']]=(score,x)
    uniq=[v[1] for v in best.values()]
    uniq.sort(key=lambda x:(max(x['visible_comment_count'],x['visible_share_count'],x['visible_like_count'],x['visible_favorite_count']),x['event_views']),reverse=True)
    fields=['hot_rank','hot_title','hot_value','event_views','post_type','post_id','url','visible_comment_count','visible_share_count','visible_like_count','visible_favorite_count','visible_text','card_context']
    with (OUT/'current_trending_posts.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(uniq)
    (OUT/'current_trending_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'topics':len(topics),'raw_posts':len(rows),'unique_native_posts':len(uniq),'articles':sum(x['post_type']=='article' for x in uniq),'weitoutiao':sum(x['post_type']=='weitoutiao' for x in uniq),'max_visible_comment':max([x['visible_comment_count'] for x in uniq] or [0]),'max_visible_like':max([x['visible_like_count'] for x in uniq] or [0]),'max_visible_favorite':max([x['visible_favorite_count'] for x in uniq] or [0]),'top':uniq[:15]},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
