import asyncio,json,re
from urllib.parse import quote
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('output_browser_sort');OUT.mkdir(exist_ok=True)
KW='真实经历'
VAR=[0,1,2]

async def main():
    out=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        ctx=await b.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        for st in VAR:
            page=await ctx.new_page(); rec={'sort_type':st,'network':[]}
            async def on_resp(resp):
                if 'toutiao.com' not in resp.url or resp.request.resource_type not in ('document','xhr','fetch'):return
                rr={'url':resp.url,'status':resp.status,'type':resp.request.resource_type,'ct':resp.headers.get('content-type','')}
                try:
                    txt=await resp.text()
                except Exception:
                    txt=''
                rr['len']=len(txt)
                if any(k in txt for k in ['group_id','comment_count','digg_count','weitoutiao']):
                    rr['counts']={k:txt.count(k) for k in ['group_id','comment_count','digg_count','forward_count','repin_count','weitoutiao']}
                    rr['prefix']=txt[:5000]
                rec['network'].append(rr)
            page.on('response',on_resp)
            try:
                url=f'https://so.toutiao.com/search?keyword={quote(KW)}&pd=weitoutiao&sort_type={st}&dvpf=pc'
                r=await page.goto(url,wait_until='domcontentloaded',timeout=60000)
                await page.wait_for_timeout(8000)
                rec['status']=r.status if r else None;rec['url']=page.url;rec['title']=await page.title()
                body=await page.locator('body').inner_text();rec['body_chars']=len(body);rec['body_prefix']=re.sub(r'\s+',' ',body[:6000])
                rec['texts']=re.findall(r'.{0,30}(?:综合|资讯|微头条|排序|最新|热度|时间).{0,60}',body)[:50]
                rec['links']=await page.locator('a').evaluate_all("els=>els.slice(0,400).map(a=>({t:(a.innerText||'').trim(),h:a.href})).filter(x=>x.h)")
                html=await page.content();rec['html_counts']={k:html.count(k) for k in ['group_id','comment_count','digg_count','forward_count','repin_count','sslocal://thread_detail','awemevideo']}
            except Exception as e:rec['error']=repr(e)
            page.remove_listener('response',on_resp);await page.close();out.append(rec)
        await b.close()
    (OUT/'browser_sort.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'sort_type':x['sort_type'],'status':x.get('status'),'body_chars':x.get('body_chars'),'body_prefix':x.get('body_prefix','')[:1200],'texts':x.get('texts'),'html_counts':x.get('html_counts'),'network_interesting':[{'url':n['url'],'status':n['status'],'type':n['type'],'len':n['len'],'counts':n.get('counts')} for n in x.get('network',[]) if n.get('counts')][:15]} for x in out],ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
