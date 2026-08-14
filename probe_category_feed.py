import asyncio, csv, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

OUT=Path('output_category_feed'); OUT.mkdir(exist_ok=True)
CATEGORIES=[
 ('home','https://www.toutiao.com/'),
 ('hot','https://www.toutiao.com/ch/news_hot/'),
 ('tech','https://www.toutiao.com/ch/news_tech/'),
 ('finance','https://www.toutiao.com/ch/news_finance/'),
 ('ent','https://www.toutiao.com/ch/news_entertainment/'),
 ('sports','https://www.toutiao.com/ch/news_sports/'),
 ('car','https://www.toutiao.com/ch/news_car/'),
 ('food','https://www.toutiao.com/ch/news_food/'),
 ('travel','https://www.toutiao.com/ch/news_travel/'),
 ('game','https://www.toutiao.com/ch/news_game/'),
 ('edu','https://www.toutiao.com/ch/news_edu/'),
 ('house','https://www.toutiao.com/ch/news_house/'),
 ('culture','https://www.toutiao.com/ch/news_culture/'),
]
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']
VIDEO_HINTS=['aweme','hotsoon','xiaoshipin','short_video']


def n(v):
    try:return int(float(v or 0))
    except:return 0

def as_json(v):
    if not isinstance(v,str):return None
    s=v.strip()
    if not s or s[0] not in '[{':return None
    try:return json.loads(s)
    except:return None

def walk(obj,path='$'):
    if isinstance(obj,dict):
        yield path,obj
        for k,v in obj.items():
            sub=as_json(v)
            if sub is not None:
                yield from walk(sub,path+'.'+str(k)+'<json>')
            elif isinstance(v,(dict,list)):
                yield from walk(v,path+'.'+str(k))
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            sub=as_json(v)
            if sub is not None: yield from walk(sub,f'{path}[{i}]<json>')
            else: yield from walk(v,f'{path}[{i}]')

def scalar(d,*keys):
    for k in keys:
        if k in d and d[k] not in (None,''):return d[k]
    return None

def candidate(d,category,response_path):
    gid=scalar(d,'group_id','groupId','item_id','itemId')
    title=scalar(d,'title','abstract','description')
    if not gid or not title:return None
    text=(str(title)+' '+str(d.get('abstract') or ''))
    if any(x in text for x in BLOCK):return None
    joined=json.dumps(d,ensure_ascii=False)[:15000].lower()
    if any(x in joined for x in VIDEO_HINTS):return None
    url=scalar(d,'article_url','display_url','source_url','share_url','url','seo_url') or ''
    if isinstance(url,dict):url=''
    if url and 'toutiao.com' not in str(url) and not str(url).startswith('sslocal://thread_detail'):
        # Keep object only when provenance is otherwise clearly Toutiao article/thread.
        schema=str(scalar(d,'detail_schema','schema','open_url') or '')
        if 'thread_detail' not in schema and '/article/' not in schema:return None
    media=scalar(d,'media_name','source','source_name') or ''
    if not media and isinstance(d.get('media_info'),dict):media=d['media_info'].get('name') or d['media_info'].get('user_name') or ''
    user_id=scalar(d,'user_id','media_creator_id') or ''
    ts=n(scalar(d,'publish_time','create_time','behot_time','publish_time_unix'))
    digg=n(scalar(d,'digg_count','diggCount','like_count','likeCount'))
    comment=n(scalar(d,'comment_count','comments_count','commentCount'))
    forward=n(scalar(d,'forward_count','share_count','shareCount','forwardCount'))
    repin=n(scalar(d,'repin_count','favorite_count','collect_count','repinCount'))
    read=n(scalar(d,'read_count','readCount','go_detail_count'))
    return {
      'category':category,'response_path':response_path,'group_id':str(gid),'title':str(title),
      'abstract':str(d.get('abstract') or ''),'url':str(url),'media_name':str(media),'user_id':str(user_id),
      'publish_time':ts,'read_count':read,'digg_count':digg,'comment_count':comment,'forward_count':forward,'repin_count':repin,
      'max_interaction':max(digg,comment,forward,repin),
      'raw_type':str(scalar(d,'content_schema_type','cell_type','content_type','type') or ''),
      'has_video':bool(d.get('has_video') or d.get('video_duration') or d.get('video_id')),
    }

async def main():
    cutoff=int((datetime.now(timezone.utc)-timedelta(days=31)).timestamp())
    now=int(datetime.now(timezone.utc).timestamp())
    rows=[]; report=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        for name,url in CATEGORIES:
            page=await ctx.new_page(); events=[]; cat_rows=[]
            async def on_resp(resp):
                try:path=urlsplit(resp.url).path
                except:path=''
                if resp.request.resource_type not in ('xhr','fetch') or '/api/pc/list/feed' not in path:return
                try:txt=await resp.text(); obj=json.loads(txt)
                except:return
                found=0
                for pth,d in walk(obj):
                    if not isinstance(d,dict):continue
                    c=candidate(d,name,path)
                    if c:
                        c['json_path']=pth;cat_rows.append(c);found+=1
                events.append({'path':path,'status':resp.status,'bytes':len(txt),'found':found})
            page.on('response',on_resp)
            rec={'category':name,'requested':url}
            try:
                r=await page.goto(url,wait_until='domcontentloaded',timeout=60000)
                await page.wait_for_timeout(3500)
                rec['status']=r.status if r else None; rec['final_url']=page.url; rec['title']=await page.title()
                rec['body_start']=re.sub(r'\s+',' ',(await page.locator('body').inner_text())[:1200])
                for i in range(16):
                    await page.mouse.wheel(0,2600)
                    await page.wait_for_timeout(850)
                rec['body_chars']=len(await page.locator('body').inner_text())
            except Exception as e:rec['error']=repr(e)
            page.remove_listener('response',on_resp); await page.close()
            best={}
            for x in cat_rows:
                gid=x['group_id']; rank=(x['max_interaction'],sum(bool(x[k]) for k in ['url','media_name','publish_time']))
                if gid not in best or rank>best[gid][0]:best[gid]=(rank,x)
            uniq=[v[1] for v in best.values()]
            recent=[x for x in uniq if cutoff<=x['publish_time']<=now+86400]
            rows.extend(uniq)
            rec['feed_events']=events
            rec['unique_candidates']=len(uniq);rec['recent_candidates']=len(recent)
            rec['viral10k_recent']=sum(x['max_interaction']>=10000 for x in recent)
            rec['max_metrics']={k:max([x[k] for x in recent] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']}
            rec['top_recent']=sorted(recent,key=lambda x:x['max_interaction'],reverse=True)[:8]
            report.append(rec)
        await browser.close()
    # global dedupe
    best={}
    for x in rows:
        gid=x['group_id'];rank=(x['max_interaction'],sum(bool(x[k]) for k in ['url','media_name','publish_time']))
        if gid not in best or rank>best[gid][0]:best[gid]=(rank,x)
    uniq=[v[1] for v in best.values()]
    fields=['category','group_id','title','abstract','url','media_name','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','raw_type','has_video','response_path','json_path']
    with (OUT/'category_feed.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(uniq)
    (OUT/'category_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    recent=[x for x in uniq if cutoff<=x['publish_time']<=now+86400]
    print(json.dumps({'categories':len(report),'unique_candidates':len(uniq),'recent_candidates':len(recent),'viral10k_recent':sum(x['max_interaction']>=10000 for x in recent),'max':{k:max([x[k] for x in recent] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']},'per_category':[{k:r.get(k) for k in ['category','status','final_url','body_chars','unique_candidates','recent_candidates','viral10k_recent','max_metrics','error']} for r in report]},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
