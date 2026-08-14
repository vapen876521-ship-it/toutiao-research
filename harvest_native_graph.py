import asyncio, csv, json, os, re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.async_api import async_playwright

OUT=Path('native_graph_output');OUT.mkdir(exist_ok=True)
HOT='https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
START_TS=int(datetime(2026,7,14,16,0,tzinfo=timezone.utc).timestamp())
END_TS=int(datetime(2026,8,14,16,0,tzinfo=timezone.utc).timestamp())
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','俄罗斯','乌克兰','以色列','加沙','伊朗','特朗普','普京','泽连斯基','拜登','选举','总统','总理','首相','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防','北约','美军','制裁','强军']
INSTITUTION=['新华社','人民日报','央视','央广','中新网','中国新闻网','光明网','日报','晚报','卫视','融媒','广播电视','新闻','官方','发布','时报','澎湃','红星新闻','极目新闻','九派','36氪','钛媒体','虎嗅']

def n(v):
    try:return int(float(v or 0))
    except:return 0

def clean_url(u):
    if not isinstance(u,str):return ''
    u=u.split('#')[0].split('?')[0].rstrip('/')+'/'
    return u if re.fullmatch(r'https://www\.toutiao\.com/(?:article|w)/\d+/',u) else ''

def post_id(u):
    m=re.search(r'/(?:article|w)/(\d+)/',u);return m.group(1) if m else ''

def political(s):return any(x in (s or '') for x in BLOCK)

def hot_topics():
    data=requests.get(HOT,headers={'User-Agent':UA},timeout=30).json(); arr=data.get('data') or data.get('Data') or data.get('list') or []
    out=[]
    for i,x in enumerate(arr,1):
        title=str(x.get('Title') or x.get('title') or '')
        cid=str(x.get('ClusterId') or x.get('cluster_id') or '')
        url=str(x.get('Url') or x.get('url') or '')
        if not title or political(title):continue
        if not url and cid:url=f'https://www.toutiao.com/trending/{cid}/'
        if '/trending/' not in url and cid:url=f'https://www.toutiao.com/trending/{cid}/'
        out.append({'rank':i,'title':title,'url':url,'cluster_id':cid})
    return out

def walk(o):
    if isinstance(o,dict):
        yield o
        for v in o.values():
            if isinstance(v,(dict,list)):yield from walk(v)
    elif isinstance(o,list):
        for v in o:yield from walk(v)

def structured_row(d):
    if not isinstance(d,dict):return None
    gid=d.get('group_id') or d.get('item_id') or d.get('groupId')
    if not gid:return None
    title=str(d.get('title') or d.get('abstract') or d.get('description') or '')
    if political(title):return None
    url=''
    for k in ['article_url','display_url','share_url','source_url','url','seo_url']:
        u=clean_url(d.get(k,''))
        if u:url=u;break
    if not url:
        typ=str(d.get('content_schema_type') or '')
        if typ in ('7','10'):url=f'https://www.toutiao.com/article/{gid}/'
        elif typ=='12':url=f'https://www.toutiao.com/w/{gid}/'
    if not url:return None
    joined=json.dumps(d,ensure_ascii=False)[:12000].lower()
    if any(x in joined for x in ['awemevideo','hotsoon_video','xiaoshipin']):return None
    if d.get('has_video') or d.get('video_id'):return None
    pub=n(d.get('publish_time') or d.get('create_time') or d.get('behot_time'))
    return {'url':url,'post_id':post_id(url),'title_structured':title[:1000],'publish_time_structured':pub,'read_count':n(d.get('read_count')),'digg_count_structured':n(d.get('digg_count')),'comment_count_structured':n(d.get('comment_count')),'forward_count':n(d.get('forward_count') or d.get('share_count')),'repin_count':n(d.get('repin_count') or d.get('favorite_count') or d.get('collect_count')),'image_count_structured':n(d.get('image_count')),'media_name_structured':str(d.get('media_name') or d.get('source') or '')}

async def aria_number(page, kind):
    sels={'like':'[aria-label^="点赞"]','comment':'[aria-label*="评论"]'}
    best=0
    try:
        vals=await page.locator(sels[kind]).evaluate_all("els=>els.map(e=>e.getAttribute('aria-label')||'')")
        for s in vals:
            if kind=='like':m=re.search(r'点赞\s*([0-9.]+)\s*万?',s)
            else:m=re.search(r'([0-9.]+)\s*万?评论',s)
            if m:
                v=float(m.group(1));v=int(v*10000) if '万' in s else int(v);best=max(best,v)
    except:pass
    return best

def parse_datetime_text(body):
    # Direct article pages commonly expose YYYY-MM-DD HH:MM; use first recent-looking date.
    for m in re.finditer(r'(2026)-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})',body):
        try:
            dt=datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5)),tzinfo=timezone.utc)
            # displayed time is China time; subtract 8h for UTC timestamp
            return int(dt.timestamp())-8*3600
        except:pass
    return 0

async def main():
    shard=int(os.getenv('SHARD_INDEX','0'));total=int(os.getenv('TOTAL_SHARDS','12'));max_pages=int(os.getenv('MAX_PAGES','140'))
    topics=[t for i,t in enumerate(hot_topics()) if i%total==shard]
    queue=deque(); discovered={}; source={}
    rows={}; logs=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent=UA)
        # Seed from rendered trending pages assigned to this shard.
        for t in topics:
            pg=await ctx.new_page()
            try:
                await pg.goto(t['url'],wait_until='domcontentloaded',timeout=60000);await pg.wait_for_timeout(3000);await pg.mouse.wheel(0,1600);await pg.wait_for_timeout(800)
                links=await pg.locator('a').evaluate_all("els=>els.map(a=>a.href).filter(Boolean)")
                for h in links:
                    u=clean_url(h)
                    if u and u not in discovered:
                        discovered[u]=0;source[u]=f"trending:{t['rank']}:{t['title']}";queue.append((u,0))
            except Exception as e:logs.append({'stage':'trending','url':t['url'],'error':repr(e)})
            await pg.close()
        print(json.dumps({'shard':shard,'topics':len(topics),'seed_urls':len(queue)},ensure_ascii=False),flush=True)
        visited=set()
        while queue and len(visited)<max_pages:
            u,depth=queue.popleft()
            if u in visited:continue
            visited.add(u); pg=await ctx.new_page(); network=[]
            async def on_resp(resp):
                if resp.request.resource_type not in ('xhr','fetch'):return
                if '/api/pc/list/feed' not in resp.url:return
                try:o=json.loads(await resp.text())
                except:return
                for d in walk(o):
                    rr=structured_row(d)
                    if rr:network.append(rr)
            pg.on('response',on_resp)
            rec={'shard':shard,'url':u,'post_id':post_id(u),'post_type':'article' if '/article/' in u else 'weitoutiao','depth':depth,'discovery_source':source.get(u,'')}
            try:
                r=await pg.goto(u,wait_until='domcontentloaded',timeout=60000);await pg.wait_for_timeout(2600);await pg.mouse.wheel(0,1700);await pg.wait_for_timeout(900)
                body=await pg.locator('body').inner_text(); rec['status']=r.status if r else None;rec['final_url']=pg.url
                rec['like_count']=await aria_number(pg,'like');rec['comment_count']=await aria_number(pg,'comment')
                rec['publish_time_dom']=parse_datetime_text(body)
                try:rec['title']=await pg.locator('h1').first.inner_text(timeout=1500)
                except:rec['title']=''
                if not rec['title'] and rec['post_type']=='weitoutiao':
                    # Take a bounded content prefix after metadata/nav noise.
                    rec['title']=re.sub(r'\s+',' ',body)[:1200]
                rec['body_text']=re.sub(r'\s+',' ',body)[:10000]
                rec['image_count_dom']=await pg.locator('main img, article img').count()
                links=await pg.locator('a').evaluate_all("els=>els.map(a=>({h:a.href,t:(a.innerText||'').trim()})).filter(x=>x.h)")
                # author heuristic from direct page around 关注; preserved as text, not follower claim.
                bshort=re.sub(r'\s+',' ',body)
                rec['author_hint']=''
                mm=re.search(r'(?:·|\s)([^\s]{2,24})\s+(?:官方账号\s+)?关注',bshort[:2500])
                if mm:rec['author_hint']=mm.group(1)
                # exact structured record for this post id if browser feed contains it
                exact=[x for x in network if x['post_id']==rec['post_id']]
                if exact:
                    s=max(exact,key=lambda x:max(x['digg_count_structured'],x['comment_count_structured'],x['forward_count'],x['repin_count'],x['read_count']))
                    for k,v in s.items():
                        if k not in ('url','post_id'):rec[k]=v
                rec['publish_time']=n(rec.get('publish_time_structured')) or n(rec.get('publish_time_dom'))
                rec['recent_verified']=START_TS<=rec['publish_time']<END_TS if rec['publish_time'] else False
                rec['political_risk']=political((rec.get('title') or '')+' '+rec.get('body_text','')[:2500])
                rec['institution_hint']=any(x in (rec.get('author_hint','')+' '+rec.get('media_name_structured','')) for x in INSTITUTION)
                rec['max_interaction']=max(n(rec.get('like_count')),n(rec.get('comment_count')),n(rec.get('digg_count_structured')),n(rec.get('comment_count_structured')),n(rec.get('forward_count')),n(rec.get('repin_count')))
                rows[u]=rec
                if depth<2:
                    added=0
                    for x in links:
                        nu=clean_url(x['h'])
                        if not nu or nu in discovered or political(x.get('t','')):continue
                        discovered[nu]=depth+1;source[nu]=u;queue.append((nu,depth+1));added+=1
                        if added>=18:break
                    # Also expand exact native URLs observed in browser-loaded structured feed.
                    for s in network[:30]:
                        nu=s['url']
                        if nu and nu not in discovered:
                            discovered[nu]=depth+1;source[nu]=u;queue.append((nu,depth+1))
            except Exception as e:rec['error']=repr(e);rows[u]=rec
            pg.remove_listener('response',on_resp);await pg.close()
            if len(visited)%20==0:print(json.dumps({'shard':shard,'visited':len(visited),'queued':len(queue),'rows':len(rows),'recent':sum(x.get('recent_verified') for x in rows.values()),'viral10k':sum(x.get('recent_verified') and x.get('max_interaction',0)>=10000 for x in rows.values())},ensure_ascii=False),flush=True)
        await browser.close()
    out=list(rows.values());valid=[x for x in out if x.get('recent_verified') and not x.get('political_risk')]
    fields=sorted({k for r in out for k in r.keys()})
    with (OUT/f'native_graph_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(out)
    summary={'shard':shard,'topics':len(topics),'visited':len(visited),'discovered':len(discovered),'rows':len(out),'recent_verified_nonpolitical':len(valid),'viral10k':sum(x.get('max_interaction',0)>=10000 for x in valid),'viral3k':sum(x.get('max_interaction',0)>=3000 for x in valid),'max_like':max([n(x.get('like_count')) for x in valid] or [0]),'max_comment':max([n(x.get('comment_count')) for x in valid] or [0]),'max_forward':max([n(x.get('forward_count')) for x in valid] or [0]),'max_repin':max([n(x.get('repin_count')) for x in valid] or [0]),'max_interaction':max([n(x.get('max_interaction')) for x in valid] or [0])}
    (OUT/f'native_graph_{shard}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
