import asyncio,csv,json,re
from pathlib import Path
from playwright.async_api import async_playwright

GIDS=['7666289460623032874','7673362469359714826','7665671174047547919','7672981576782758400','7673054716309357065','7666317366066528806','7672411514145358371','7663676775276315170','7662201911889658418','7663805338268779051','7662946835924795942','7673469596170486308']
OUT=Path('retry_hot_output');OUT.mkdir(exist_ok=True)

async def extract(page):
    for _ in range(3):
        try:
            await page.wait_for_selector('body',timeout=8000)
            return await page.evaluate("""() => {
              const doc=document; const body=doc.body||doc.documentElement;
              if(!body) return {selector:'',text:'',paragraphs:[],images:[],links:[]};
              const sels=['article','[class*=\"article-content\"]','[class*=\"syl-page-article\"]','main'];
              let best=null;
              for(const s of sels){for(const e of doc.querySelectorAll(s)){const t=(e.innerText||'').trim();if(t.length>200&&(!best||t.length>best.t.length))best={e:e,t:t,s:s};}}
              const root=best?best.e:body;
              const ps=[...root.querySelectorAll('p')].map(e=>(e.innerText||'').trim()).filter(Boolean);
              const imgs=[...root.querySelectorAll('img')].map(e=>e.currentSrc||e.src||'').filter(x=>/^https?:/.test(x));
              const links=[...doc.querySelectorAll('a[href]')].map(a=>({href:a.href,text:(a.innerText||a.textContent||'').trim().replace(/\\s+/g,' ').slice(0,80)})).filter(x=>/toutiao\\.com\\/(?:c\\/user|user|profile)/.test(x.href));
              return {selector:best?best.s:'body',text:(best?best.t:(body.innerText||'')).slice(0,20000),paragraphs:ps.slice(0,160),images:[...new Set(imgs)].slice(0,100),links:links.slice(0,20)};
            }""")
        except Exception:
            await page.wait_for_timeout(1800)
    return {'selector':'','text':'','paragraphs':[],'images':[],'links':[]}

async def main():
    rows=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        ctx=await b.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36')
        for gid in GIDS:
            best=None
            for attempt in range(1,4):
                page=await ctx.new_page(); url=f'https://www.toutiao.com/article/{gid}/'
                try:
                    resp=await page.goto(url,wait_until='domcontentloaded',timeout=55000)
                    await page.wait_for_timeout(5500)
                    d=await extract(page); final=page.url; status=resp.status if resp else 0
                    title=''
                    try:title=await page.title()
                    except:pass
                    rec={'group_id':gid,'attempt':attempt,'http_status':status,'final_url':final,'detail_verified':bool(status==200 and gid in final and len(d['text'])>200),'page_title':title,'content_selector':d['selector'],'content_chars':len(d['text']),'paragraph_count':len(d['paragraphs']),'paragraphs_json':json.dumps(d['paragraphs'],ensure_ascii=False),'first_3_paragraphs':json.dumps(d['paragraphs'][:3],ensure_ascii=False),'last_3_paragraphs':json.dumps(d['paragraphs'][-3:],ensure_ascii=False),'content_text':d['text'],'detail_image_count':len(d['images']),'detail_image_urls':json.dumps(d['images'],ensure_ascii=False),'author_links':json.dumps(d['links'],ensure_ascii=False),'detail_error':''}
                except Exception as e:
                    rec={'group_id':gid,'attempt':attempt,'http_status':0,'final_url':page.url,'detail_verified':False,'page_title':'','content_selector':'','content_chars':0,'paragraph_count':0,'paragraphs_json':'[]','first_3_paragraphs':'[]','last_3_paragraphs':'[]','content_text':'','detail_image_count':0,'detail_image_urls':'[]','author_links':'[]','detail_error':repr(e)[:500]}
                await page.close()
                if best is None or rec['content_chars']>best['content_chars']: best=rec
                if rec['detail_verified']: break
                await asyncio.sleep(4)
            rows.append(best);print(json.dumps({'gid':gid,'verified':best['detail_verified'],'status':best['http_status'],'chars':best['content_chars']},ensure_ascii=False),flush=True);await asyncio.sleep(3)
        await b.close()
    fields=list(rows[0].keys())
    with (OUT/'retry_hot_details.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    (OUT/'summary.json').write_text(json.dumps({'rows':len(rows),'verified':sum(r['detail_verified'] for r in rows)},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
