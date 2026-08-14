import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path('output_pagination_fullhtml')
OUT.mkdir(exist_ok=True)
KEYWORDS = ['美食', '餐厅', '早餐']
HINTS = ['group_id','publish_time','read_count','digg_count','comment_count','forward_count','media_name','article_url']


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def inspect_html(html):
    soup = BeautifulSoup(html, 'lxml')
    scripts = []
    candidates = {}
    for idx, tag in enumerate(soup.find_all('script')):
        body = (tag.string or tag.get_text() or '').strip()
        rec = {
            'idx': idx,
            'id': tag.get('id',''),
            'type': tag.get('type',''),
            'length': len(body),
            'hint_counts': {k: body.count(k) for k in HINTS if k in body},
        }
        if body:
            rec['prefix'] = body[:300]
        scripts.append(rec)
        payloads=[]
        if body.startswith('{') or body.startswith('['):
            payloads.append(body.rstrip(';'))
        if '\"extraData\"' in body and not payloads:
            m=re.search(r'(\{\"extraData\".*\})',body,flags=re.S)
            if m: payloads.append(m.group(1))
        for payload in payloads:
            try: obj=json.loads(payload)
            except Exception: continue
            for d in walk(obj):
                if not isinstance(d,dict): continue
                gid=d.get('group_id')
                if gid and (d.get('title') or d.get('abstract')):
                    candidates[str(gid)]={
                        'group_id':str(gid),
                        'title':d.get('title') or d.get('abstract') or '',
                        'abstract':d.get('abstract') or '',
                        'publish_time':d.get('publish_time') or d.get('create_time') or d.get('behot_time'),
                        'read_count':d.get('read_count'),
                        'digg_count':d.get('digg_count'),
                        'comment_count':d.get('comment_count'),
                        'forward_count':d.get('forward_count'),
                        'media_name':d.get('media_name') or d.get('source') or '',
                        'article_url':d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or '',
                    }
    hrefs=[]
    for a in soup.find_all('a',href=True):
        h=a.get('href','')
        if any(x in h for x in ['/article/','/group/','/item/','thread_detail','toutiao.com/i']):
            hrefs.append(h)
    return {
        'html_length':len(html),
        'hint_counts':{k:html.count(k) for k in HINTS},
        'script_count':len(scripts),
        'scripts':scripts,
        'candidate_count':len(candidates),
        'candidates':list(candidates.values()),
        'content_hrefs':list(dict.fromkeys(hrefs))[:200],
    }


async def main():
    report=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(
            locale='zh-CN',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        for kw in KEYWORDS:
            page=await context.new_page()
            entry={'keyword':kw}
            document_bodies=[]
            async def on_response(resp):
                if resp.request.resource_type=='document' and 'toutiao.com/search' in resp.url:
                    try:
                        txt=await resp.text()
                        document_bodies.append((resp.url,txt))
                    except Exception as e:
                        document_bodies.append((resp.url,'ERROR:'+repr(e)))
            page.on('response',on_response)
            try:
                url=f'https://so.toutiao.com/search/?dvpf=pc&keyword={quote(kw)}'
                await page.goto(url,wait_until='domcontentloaded',timeout=60000)
                await page.wait_for_timeout(3500)
                entry['page1_url']=page.url
                h1=await page.content()
                (OUT/f'{kw}_page1_rendered.html').write_text(h1,encoding='utf-8')
                entry['page1']=inspect_html(h1)
                nxt=page.get_by_text('下一页',exact=True)
                entry['next_count']=await nxt.count()
                if await nxt.count() and await nxt.first.is_visible():
                    old=page.url
                    await nxt.first.click()
                    try:
                        await page.wait_for_url(lambda u:str(u)!=old,timeout=15000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(6000)
                    entry['page2_url']=page.url
                    h2=await page.content()
                    (OUT/f'{kw}_page2_rendered.html').write_text(h2,encoding='utf-8')
                    entry['page2']=inspect_html(h2)
                entry['document_responses']=[]
                for i,(u,txt) in enumerate(document_bodies):
                    if txt.startswith('ERROR:'):
                        entry['document_responses'].append({'url':u,'error':txt})
                        continue
                    fname=f'{kw}_document_{i}.html'
                    (OUT/fname).write_text(txt,encoding='utf-8')
                    ins=inspect_html(txt)
                    entry['document_responses'].append({'url':u,'file':fname,'inspection':ins})
            except Exception as e:
                entry['error']=repr(e)
            report.append(entry)
            await page.close()
        await browser.close()
    (OUT/'fullhtml_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for x in report:
        compact.append({
            'keyword':x.get('keyword'),'error':x.get('error'),'page1_url':x.get('page1_url'),'page2_url':x.get('page2_url'),
            'p1_candidates':(x.get('page1') or {}).get('candidate_count'),
            'p2_candidates':(x.get('page2') or {}).get('candidate_count'),
            'p2_hints':(x.get('page2') or {}).get('hint_counts'),
            'p2_scripts':[s for s in (x.get('page2') or {}).get('scripts',[]) if s.get('hint_counts')],
            'document_candidates':[d.get('inspection',{}).get('candidate_count') for d in x.get('document_responses',[]) if d.get('inspection')],
            'document_hints':[d.get('inspection',{}).get('hint_counts') for d in x.get('document_responses',[]) if d.get('inspection')],
        })
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=='__main__':
    asyncio.run(main())
