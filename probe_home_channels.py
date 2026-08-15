import asyncio,json,re
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

OUT=Path('home_channel_probe');OUT.mkdir(exist_ok=True)
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

def walk(o):
    if isinstance(o,dict):
        yield o
        for v in o.values():
            if isinstance(v,(dict,list)):yield from walk(v)
    elif isinstance(o,list):
        for v in o:yield from walk(v)

def native_obj(d):
    if not isinstance(d,dict):return None
    gid=d.get('group_id') or d.get('item_id') or d.get('groupId')
    title=d.get('title') or d.get('abstract') or d.get('description') or ''
    if not gid or not title:return None
    joined=json.dumps(d,ensure_ascii=False)[:8000].lower()
    if any(x in joined for x in ['awemevideo','hotsoon_video','xiaoshipin']):return None
    if d.get('has_video') or d.get('video_id'):return None
    typ=str(d.get('content_schema_type') or '')
    url=''
    for k in ['article_url','display_url','share_url','seo_url','url']:
        u=str(d.get(k) or '')
        if re.match(r'https?://(?:www\.)?toutiao\.com/(?:article|w)/\d+',u):url=u.split('?')[0].rstrip('/')+'/';break
    if not url and typ in ('7','10'):url=f'https://www.toutiao.com/article/{gid}/'
    if not url and typ=='12':url=f'https://www.toutiao.com/w/{gid}/'
    if not url:return None
    return {'group_id':str(gid),'title':re.sub(r'\s+',' ',str(title)).strip()[:500],'url':url,'schema':typ,
      'publish_time':d.get('publish_time') or d.get('create_time') or d.get('behot_time') or 0,
      'read_count':d.get('read_count') or 0,'digg_count':d.get('digg_count') or 0,'comment_count':d.get('comment_count') or 0,
      'forward_count':d.get('forward_count') or 0,'repin_count':d.get('repin_count') or 0,
      'media_name':d.get('media_name') or d.get('source') or '', 'user_id':d.get('user_id') or d.get('media_creator_id') or ''}

async def inspect(page,url,label):
    captured=[]; responses=[]
    async def on_resp(resp):
        if resp.request.resource_type not in ('xhr','fetch'):return
        u=resp.url
        try:txt=await resp.text()
        except:return
        if 'group_id' not in txt and 'item_id' not in txt:return
        token_counts={k:txt.count(k) for k in ['group_id','digg_count','comment_count','forward_count','repin_count','followers_count']}
        responses.append({'url':u,'status':resp.status,'content_type':resp.headers.get('content-type',''),'bytes':len(txt),'tokens':token_counts})
        if 'json' not in resp.headers.get('content-type','') and not txt.lstrip().startswith(('{','[')):return
        try:o=json.loads(txt)
        except:return
        for d in walk(o):
            r=native_obj(d)
            if r:captured.append(r)
    page.on('response',on_resp)
    rec={'label':label,'url':url}
    try:
        r=await page.goto(url,wait_until='domcontentloaded',timeout=60000);await page.wait_for_timeout(3500)
        for i in range(6):
            await page.mouse.wheel(0,2200);await page.wait_for_timeout(1100)
        body=await page.locator('body').inner_text(); links=await page.locator('a').evaluate_all("els=>els.map(a=>({h:a.href,t:(a.innerText||'').trim()})).filter(x=>x.h)")
        rec.update({'status':r.status if r else None,'final_url':page.url,'title':await page.title(),'body_chars':len(body),'body_prefix':re.sub(r'\s+',' ',body)[:1000]})
        rec['channel_links']=[x for x in links if '/ch/' in x['h']][:200]
        rec['content_links']=[x for x in links if re.search(r'toutiao\.com/(article|w)/\d+',x['h'])][:100]
    except Exception as e:rec['error']=repr(e)
    page.remove_listener('response',on_resp)
    best={}
    for x in captured:
        k=x['group_id'];score=max(int(x.get(c) or 0) if str(x.get(c) or 0).isdigit() else 0 for c in ['read_count','digg_count','comment_count','forward_count','repin_count'])
        if k not in best or score>best[k][0]:best[k]=(score,x)
    rec['captured_native']=list(v[1] for v in best.values())
    rec['responses']=responses[:300]
    return rec

async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True);ctx=await b.new_context(locale='zh-CN',user_agent=UA,viewport={'width':1400,'height':1000});page=await ctx.new_page()
        home=await inspect(page,'https://www.toutiao.com/','home')
        chans=[];seen=set()
        for x in home.get('channel_links',[]):
            h=x['h'].split('?')[0].rstrip('/')+'/'
            if h in seen:continue
            seen.add(h);chans.append((h,x.get('t','')))
        reports=[home]
        for h,t in chans[:12]:reports.append(await inspect(page,h,t or urlparse(h).path))
        await b.close()
    (OUT/'report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'pages':len(reports),'home_channels':len(chans),'channels':[{'url':u,'text':t} for u,t in chans[:80]],'page_stats':[{'label':r['label'],'url':r['url'],'native':len(r.get('captured_native',[])),'responses':len(r.get('responses',[])),'channel_links':len(r.get('channel_links',[]))} for r in reports]}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
