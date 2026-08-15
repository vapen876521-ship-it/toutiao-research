import asyncio,json,re
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('group_mapping_output');OUT.mkdir(exist_ok=True)
IDS=['7673063467049370139','7673362469359714826','7672972441127371291','7672693287387644456','7662201911889658418','7673469596170486308','7673403776296665638','7664199232949174807']
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

async def inspect(page,url):
    rec={'requested':url}
    try:
        r=await page.goto(url,wait_until='domcontentloaded',timeout=60000)
        await page.wait_for_timeout(2500)
        rec['status']=r.status if r else None
        rec['final_url']=page.url
        rec['title']=await page.title()
        body=await page.locator('body').inner_text()
        rec['body_chars']=len(body)
        rec['body_start']=re.sub(r'\s+',' ',body[:500])
        rec['article_links']=await page.locator('a[href*="/article/"]').evaluate_all('(els)=>els.slice(0,10).map(e=>e.href)')
        rec['w_links']=await page.locator('a[href*="/w/"]').evaluate_all('(els)=>els.slice(0,10).map(e=>e.href)')
        labels=await page.locator('[aria-label]').evaluate_all('(els)=>els.map(e=>e.getAttribute("aria-label")).filter(Boolean).slice(0,80)')
        rec['aria_labels']=labels
    except Exception as e:
        rec['error']=repr(e)
    return rec

async def main():
    out=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        c=await b.new_context(locale='zh-CN',user_agent=UA,viewport={'width':1365,'height':900})
        page=await c.new_page()
        for gid in IDS:
            a=await inspect(page,f'https://www.toutiao.com/article/{gid}/')
            g=await inspect(page,f'https://www.toutiao.com/group/{gid}/')
            rec={'group_id':gid,'article':a,'group':g}
            out.append(rec)
            print(json.dumps({'group_id':gid,'article_status':a.get('status'),'article_final':a.get('final_url'),'article_chars':a.get('body_chars'),'group_status':g.get('status'),'group_final':g.get('final_url'),'group_chars':g.get('body_chars')},ensure_ascii=False),flush=True)
        await c.close();await b.close()
    (OUT/'group_mapping.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
