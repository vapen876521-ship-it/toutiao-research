import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

OUT=Path('output_user_search'); OUT.mkdir(exist_ok=True)
AUTHORS=[
    ('北漂外婆(周一至周五12点50直播)','12766427864','1640489772877831'),
    ('青春已不在','712919958162008','1798740715284484'),
    ('山腰间行走的徒步客','406150388124867','1865418371092492'),
]
HINTS=['fans','fan_count','fans_count','follower','followers','follower_count','followers_count','粉丝','user_id','media_id','media_name','name']

async def main():
    report=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        for name,uid,mid in AUTHORS:
            page=await ctx.new_page(); docs=[]; events=[]
            async def on_resp(resp):
                if 'toutiao.com' not in resp.url: return
                if resp.request.resource_type not in ('document','xhr','fetch'): return
                rec={'url':resp.url,'status':resp.status,'type':resp.request.resource_type,'content_type':resp.headers.get('content-type','')}
                try: txt=await resp.text()
                except Exception as e: txt=''; rec['error']=repr(e)
                rec['length']=len(txt); rec['hints']={h:txt.lower().count(h.lower()) for h in HINTS if h.lower() in txt.lower()}
                if rec['hints']:
                    # snippets around follower/fans terms, not entire payload
                    snippets=[]
                    low=txt.lower()
                    for h in ['followers_count','follower_count','fans_count','fan_count','followers','fans','粉丝']:
                        pos=0
                        while len(snippets)<20:
                            i=low.find(h.lower(),pos)
                            if i<0: break
                            snippets.append(txt[max(0,i-250):min(len(txt),i+500)])
                            pos=i+len(h)
                    rec['snippets']=snippets
                events.append(rec)
            page.on('response',on_resp)
            urls=[
                f'https://so.toutiao.com/search/?dvpf=pc&keyword={quote(name)}&pd=user',
                f'https://www.toutiao.com/search/?keyword={quote(name)}',
            ]
            item={'name':name,'user_id':uid,'media_id':mid,'pages':[]}
            for u in urls:
                try:
                    await page.goto(u,wait_until='domcontentloaded',timeout=60000)
                    await page.wait_for_timeout(4000)
                    html=await page.content(); body=await page.locator('body').inner_text()
                    item['pages'].append({'requested':u,'final_url':page.url,'html_len':len(html),'body_len':len(body),'body_prefix':re.sub(r'\s+',' ',body[:3000]),'hints':{h:html.lower().count(h.lower()) for h in HINTS if h.lower() in html.lower()}})
                    (OUT/f'{uid}_{len(item["pages"])}.html').write_text(html,encoding='utf-8')
                except Exception as e:
                    item['pages'].append({'requested':u,'error':repr(e)})
            item['events']=events
            report.append(item)
            await page.close()
        await browser.close()
    (OUT/'user_search_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for x in report:
        compact.append({'name':x['name'],'pages':x['pages'],'interesting_events':[e for e in x['events'] if e.get('hints')]})
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=='__main__': asyncio.run(main())
