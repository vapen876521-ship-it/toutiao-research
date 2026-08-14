import asyncio, json, re
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('output_trending_render');OUT.mkdir(exist_ok=True)
TOPICS=[
 ('女子连中4瓶1元换购商家拒兑换','7673763584488456234'),
 ('追觅卖出首台手机 售价超20万元','7673679213765181476'),
 ('国乒男女双全军覆没','7673729998800293418'),
 ('老人车祸离世 46.8万赔偿为何难兑现','7673317474875523126'),
 ('酒吧多人穿近似海航空姐制服跳舞','7673688031060099091'),
]
ARTICLE=('我国生态环境持续向好','https://www.toutiao.com/article/7673404050364170798')
TOKENS=['group_id','item_id','article_id','digg_count','comment_count','forward_count','repin_count','read_count','publish_time','media_name','user_id','article_url','sslocal://thread_detail','awemevideo']


def key_counts(text):
    return {k:text.count(k) for k in TOKENS}

def snippets(text, needle, radius=240, limit=4):
    out=[]; start=0
    for _ in range(limit):
        i=text.find(needle,start)
        if i<0: break
        out.append(text[max(0,i-radius):min(len(text),i+len(needle)+radius)])
        start=i+len(needle)
    return out

async def inspect(page, label, url):
    rec={'label':label,'requested':url,'network':[]}
    async def on_resp(resp):
        if 'toutiao.com' not in resp.url: return
        if resp.request.resource_type not in ('document','xhr','fetch'): return
        item={'url':resp.url,'status':resp.status,'type':resp.request.resource_type,'ct':resp.headers.get('content-type','')}
        try: txt=await resp.text()
        except Exception: txt=''
        item['len']=len(txt)
        counts=key_counts(txt)
        if any(counts.values()) or '/api/' in resp.url or '/trending/' in resp.url or '/article/' in resp.url:
            item['counts']=counts
            hits={}
            for k in ['group_id','digg_count','comment_count','article_url','sslocal://thread_detail']:
                ss=snippets(txt,k,180,2)
                if ss: hits[k]=ss
            if hits:item['snippets']=hits
            rec['network'].append(item)
    page.on('response',on_resp)
    try:
        r=await page.goto(url,wait_until='domcontentloaded',timeout=60000)
        await page.wait_for_timeout(10000)
        rec['status']=r.status if r else None
        rec['final_url']=page.url
        rec['title']=await page.title()
        body=await page.locator('body').inner_text()
        html=await page.content()
        rec['body_chars']=len(body)
        rec['body_prefix']=re.sub(r'\s+',' ',body[:8000])
        rec['html_chars']=len(html)
        rec['html_counts']=key_counts(html)
        rec['links']=await page.locator('a').evaluate_all("els=>els.map(a=>({t:(a.innerText||'').trim().slice(0,180),h:a.href})).filter(x=>x.h&&(/toutiao\\.com\\/(article|w|trending|group)\\//.test(x.h)||x.h.includes('thread_detail'))).slice(0,250)")
        # Inventory script tags and useful embedded structured data, without replaying any protected request.
        scripts=await page.locator('script').evaluate_all("els=>els.map((s,i)=>({i,type:s.type||'',id:s.id||'',len:(s.textContent||'').length,text:(s.textContent||'').slice(0,12000)})).filter(x=>x.len>0)")
        inv=[]
        for s in scripts:
            counts=key_counts(s['text'])
            if s['type']=='application/ld+json' or any(counts.values()) or 'articleBody' in s['text'] or 'author' in s['text']:
                inv.append({'i':s['i'],'type':s['type'],'id':s['id'],'len':s['len'],'counts':counts,'prefix':s['text'][:4000]})
        rec['scripts']=inv[:80]
    except Exception as e:
        rec['error']=repr(e)
    page.remove_listener('response',on_resp)
    return rec

async def main():
    out=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        for title,cid in TOPICS:
            page=await ctx.new_page()
            out.append(await inspect(page,'trending:'+title,f'https://www.toutiao.com/trending/{cid}/'))
            await page.close()
        page=await ctx.new_page()
        out.append(await inspect(page,'article:'+ARTICLE[0],ARTICLE[1]))
        await page.close();await browser.close()
    (OUT/'report.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for x in out:
        compact.append({
          'label':x['label'],'status':x.get('status'),'final_url':x.get('final_url'),'title':x.get('title'),
          'body_chars':x.get('body_chars'),'html_chars':x.get('html_chars'),'html_counts':x.get('html_counts'),
          'links':x.get('links',[])[:30],
          'network':[{'url':n['url'],'status':n['status'],'type':n['type'],'len':n['len'],'counts':n.get('counts')} for n in x.get('network',[])[:40]],
          'script_count':len(x.get('scripts',[])),'body_prefix':x.get('body_prefix','')[:1800], 'error':x.get('error')
        })
    print(json.dumps(compact,ensure_ascii=False,indent=2))

if __name__=='__main__': asyncio.run(main())
