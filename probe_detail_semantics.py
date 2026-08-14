import asyncio, json, re
from pathlib import Path
from playwright.async_api import async_playwright

OUT=Path('output_detail_semantics');OUT.mkdir(exist_ok=True)
URLS=[
 'https://www.toutiao.com/article/7673404050364170798/',
 'https://www.toutiao.com/article/7673748043556028968/',
 'https://www.toutiao.com/w/1873418329962503/',
 'https://www.toutiao.com/w/1873497880782859/',
]
KEYS=['赞','点赞','评论','收藏','分享','转发']

JS="""els => els.map((e,i)=>({
 tag:e.tagName,
 text:(e.innerText||e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,300),
 aria:e.getAttribute('aria-label')||'',
 title:e.getAttribute('title')||'',
 cls:(e.className&&typeof e.className==='string'?e.className:'').slice(0,300),
 role:e.getAttribute('role')||'',
 data:Object.fromEntries(Array.from(e.attributes||[]).filter(a=>a.name.startsWith('data-')).slice(0,12).map(a=>[a.name,a.value])),
 parent:(e.parentElement?.innerText||'').trim().replace(/\\s+/g,' ').slice(0,500),
 grand:(e.parentElement?.parentElement?.innerText||'').trim().replace(/\\s+/g,' ').slice(0,700)
}))"""

async def main():
 out=[]
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True)
  ctx=await b.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
  for url in URLS:
   page=await ctx.new_page();rec={'url':url}
   try:
    r=await page.goto(url,wait_until='domcontentloaded',timeout=60000);await page.wait_for_timeout(5000)
    rec['status']=r.status if r else None;rec['final_url']=page.url;rec['title']=await page.title()
    body=await page.locator('body').inner_text();rec['body_prefix']=re.sub(r'\s+',' ',body[:3500]);rec['body_chars']=len(body)
    # Broadly collect interactive/text elements, then filter in Python so we see structure around numeric-only controls too.
    sel='button,a,[role="button"],span,div'
    raw=await page.locator(sel).evaluate_all(JS)
    interesting=[]
    for x in raw:
     blob=' '.join(str(x.get(k) or '') for k in ['text','aria','title','parent','grand'])
     if any(k in blob for k in KEYS):
      # Ignore huge containers; retain compact controls/parents carrying engagement semantics.
      if len(x.get('text',''))<=120 or x.get('aria') or x.get('title') or len(x.get('parent',''))<=260:
       interesting.append(x)
    rec['engagement_elements']=interesting[:300]
    # Also capture compact numeric text elements near top half of document.
    nums=[]
    for x in raw:
     t=x.get('text','').strip()
     if re.fullmatch(r'[+]?\d+(?:\.\d+)?(?:万)?',t) and len(x.get('parent',''))<=180:
      nums.append(x)
    rec['numeric_elements']=nums[:200]
   except Exception as e:rec['error']=repr(e)
   out.append(rec);await page.close()
  await b.close()
 (OUT/'detail_semantics.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 for r in out:
  print(json.dumps({'url':r['url'],'status':r.get('status'),'title':r.get('title'),'body_prefix':r.get('body_prefix','')[:900],'engagement_elements':r.get('engagement_elements',[])[:35],'numeric_elements':r.get('numeric_elements',[])[:25],'error':r.get('error')},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
