import asyncio,csv,json,os,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

OUT=Path('category_deep_output');OUT.mkdir(exist_ok=True)
NAME=os.environ.get('CATEGORY_NAME','hot')
URL=os.environ.get('CATEGORY_URL','https://www.toutiao.com/ch/news_hot/')
SCROLLS=int(os.environ.get('SCROLLS','55'))
SESSIONS=int(os.environ.get('SESSIONS','2'))
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
START_TS=int(datetime(2026,7,14,16,0,tzinfo=timezone.utc).timestamp())
END_TS=int(datetime(2026,8,14,16,0,tzinfo=timezone.utc).timestamp())
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','俄罗斯','乌克兰','以色列','加沙','伊朗','特朗普','普京','泽连斯基','拜登','选举','总统','总理','首相','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防','北约','美军','联合国','侵略','制裁','中美','美日']
VIDEO_HINTS=['awemevideo','hotsoon_video','xiaoshipin','shortvideo.__search__','short_video','sslocal://awemevideo']
INSTITUTION=['卫视','日报','晚报','新闻','融媒','官方','发布','广播','电视','时报','央视','新华','光明','中新','澎湃','红星','极目','大象新闻','媒体','快讯','36氪']

def n(v):
    try:return int(float(v or 0))
    except:return 0

def gid_ts(gid):
    try:
        s=str(gid)
        if not re.fullmatch(r'\d{18,20}',s):return 0
        x=int(s)>>32
        return x if 1500000000<=x<=2100000000 else 0
    except:return 0

def as_json(v):
    if not isinstance(v,str):return None
    s=v.strip()
    if not s or s[0] not in '[{':return None
    try:return json.loads(s)
    except:return None

def walk(o,path='$'):
    if isinstance(o,dict):
        yield path,o
        for k,v in o.items():
            sub=as_json(v)
            if sub is not None:yield from walk(sub,path+'.'+str(k)+'<json>')
            elif isinstance(v,(dict,list)):yield from walk(v,path+'.'+str(k))
    elif isinstance(o,list):
        for i,v in enumerate(o):yield from walk(v,f'{path}[{i}]')

def scalar(d,*keys):
    for k in keys:
        if k in d and d[k] not in (None,''):return d[k]
    return None

def follower_count(d,uid=''):
    vals=[]
    for _,x in walk(d):
        if not isinstance(x,dict):continue
        f=max([n(x.get(k)) for k in ['followers_count','follower_count','fans_count']] or [0])
        if not f:continue
        ids=[str(x.get(k)) for k in ['user_id','uid','author_id','media_id'] if x.get(k) not in (None,'')]
        if not uid or not ids or str(uid) in ids:vals.append(f)
    return max(vals or [0])

def image_count(d):
    vals=[n(d.get('image_count')),n(d.get('gallary_image_count'))]
    for k in ['image_list','detail_image_list','large_image_list']:
        if isinstance(d.get(k),list):vals.append(len(d[k]))
    return max(vals or [0])

def native_url(d,gid):
    for k in ['article_url','display_url','share_url','seo_url','url','source_url','detail_url']:
        u=str(d.get(k) or '')
        m=re.search(r'https?://(?:www\.|m\.)?toutiao\.com/(article|w)/(\d+)',u)
        if m:return f'https://www.toutiao.com/{m.group(1)}/{m.group(2)}/',('article' if m.group(1)=='article' else 'weitoutiao'),'url'
    ds=str(scalar(d,'detail_schema','schema','open_url') or '')
    if 'sslocal://thread_detail' in ds:return f'https://www.toutiao.com/w/{gid}/','weitoutiao','thread_schema'
    typ=str(scalar(d,'content_schema_type','content_type') or '')
    if typ=='12':return f'https://www.toutiao.com/w/{gid}/','weitoutiao','schema12'
    if typ in ('7','10'):return f'https://www.toutiao.com/article/{gid}/','article','schema'+typ
    return '','',''

def candidate(d,response_url,json_path,session):
    gid=scalar(d,'group_id','groupId','item_id','itemId')
    title=scalar(d,'title','Title','abstract','description')
    if not gid or not title:return None
    gid=str(gid).strip()
    if not re.fullmatch(r'\d{15,20}',gid):return None
    text=str(title)+' '+str(d.get('abstract') or '')
    if any(x in text for x in BLOCK):return None
    joined=json.dumps(d,ensure_ascii=False)[:20000].lower()
    if any(x in joined for x in VIDEO_HINTS):return None
    typ=str(scalar(d,'content_schema_type','content_type') or '')
    if typ=='3' or d.get('has_video') or d.get('video_id') or d.get('video_duration') or d.get('has_m3u8_video') or d.get('has_mp4_video'):return None
    url,post_type,provenance=native_url(d,gid)
    if not url:return None
    explicit=n(scalar(d,'publish_time','create_time','behot_time','publish_time_unix'))
    pub=explicit
    source='explicit'
    if not pub and post_type=='article':
        pub=gid_ts(gid);source='gid_decode' if pub else ''
    if not pub or not (START_TS<=pub<END_TS):return None
    digg=n(scalar(d,'digg_count','diggCount','like_count','likeCount'))
    comment=n(scalar(d,'comment_count','comments_count','commentCount'))
    forward=n(scalar(d,'forward_count','share_count','shareCount','forwardCount'))
    repin=n(scalar(d,'repin_count','favorite_count','collect_count','repinCount'))
    read=n(scalar(d,'read_count','readCount','go_detail_count'))
    media=scalar(d,'media_name','source','source_name') or ''
    if not media and isinstance(d.get('media_info'),dict):media=d['media_info'].get('name') or d['media_info'].get('user_name') or ''
    uid=scalar(d,'user_id','media_creator_id','author_id') or ''
    return {'category':NAME,'session':session,'group_id':gid,'post_url':url,'post_type':post_type,'provenance':provenance,
      'title':re.sub(r'\s+',' ',str(title)).strip()[:700],'abstract':re.sub(r'\s+',' ',str(d.get('abstract') or '')).strip()[:1800],
      'media_name':str(media),'user_id':str(uid),'followers_count':follower_count(d,str(uid)),'institution_hint':any(x in str(media) for x in INSTITUTION),
      'publish_time':pub,'publish_time_source':source,'read_count':read,'digg_count':digg,'comment_count':comment,'forward_count':forward,'repin_count':repin,
      'max_interaction':max(digg,comment,forward,repin),'interaction_sum':digg+comment+forward+repin,'image_count':image_count(d),
      'content_schema_type':typ,'response_url':response_url,'json_path':json_path}

async def run_session(browser,session):
    ctx=await browser.new_context(locale='zh-CN',user_agent=UA,viewport={'width':1365,'height':900})
    page=await ctx.new_page();rows=[];events=[]
    async def on_resp(resp):
        try:path=urlsplit(resp.url).path
        except:path=''
        if resp.request.resource_type not in ('xhr','fetch') or '/api/pc/list/feed' not in path:return
        try:txt=await resp.text();obj=json.loads(txt)
        except:return
        found=0
        for pth,d in walk(obj):
            if not isinstance(d,dict):continue
            c=candidate(d,resp.url,pth,session)
            if c:rows.append(c);found+=1
        events.append({'url':resp.url,'status':resp.status,'bytes':len(txt),'strict_recent_found':found})
    page.on('response',on_resp)
    rec={'category':NAME,'session':session,'requested':URL}
    try:
        r=await page.goto(URL,wait_until='domcontentloaded',timeout=60000);await page.wait_for_timeout(3500)
        rec['status']=r.status if r else None;rec['final_url']=page.url;rec['title']=await page.title()
        for i in range(SCROLLS):
            await page.mouse.wheel(0,2600);await page.wait_for_timeout(850)
            if (i+1)%10==0:print(json.dumps({'category':NAME,'session':session,'scroll':i+1,'raw_strict':len(rows),'feed_events':len(events)},ensure_ascii=False),flush=True)
        rec['body_chars']=len(await page.locator('body').inner_text())
    except Exception as e:rec['error']=repr(e)
    page.remove_listener('response',on_resp);await ctx.close()
    best={}
    for x in rows:
        score=(x['max_interaction'],x['interaction_sum'],sum(bool(x.get(k)) for k in ['media_name','user_id','followers_count','abstract','image_count']))
        if x['group_id'] not in best or score>best[x['group_id']][0]:best[x['group_id']]=(score,x)
    rec['feed_events']=len(events);rec['unique_strict_recent']=len(best);rec['viral10k']=sum(v[1]['max_interaction']>=10000 for v in best.values())
    return [v[1] for v in best.values()],rec

async def main():
    all_rows=[];reports=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        for s in range(SESSIONS):
            rows,rep=await run_session(browser,s);all_rows.extend(rows);reports.append(rep)
        await browser.close()
    best={}
    for x in all_rows:
        score=(x['max_interaction'],x['interaction_sum'],sum(bool(x.get(k)) for k in ['media_name','user_id','followers_count','abstract','image_count']))
        if x['group_id'] not in best or score>best[x['group_id']][0]:best[x['group_id']]=(score,x)
    rows=[v[1] for v in best.values()]
    fields=['category','session','group_id','post_url','post_type','provenance','title','abstract','media_name','user_id','followers_count','institution_hint','publish_time','publish_time_source','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum','image_count','content_schema_type','response_url','json_path']
    with (OUT/f'strict_category_{NAME}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    summary={'category':NAME,'sessions':SESSIONS,'scrolls_per_session':SCROLLS,'unique_strict_recent':len(rows),'article':sum(x['post_type']=='article' for x in rows),'weitoutiao':sum(x['post_type']=='weitoutiao' for x in rows),'viral10k':sum(x['max_interaction']>=10000 for x in rows),'viral3k':sum(x['max_interaction']>=3000 for x in rows),'viral1k':sum(x['max_interaction']>=1000 for x in rows),'followers_resolved':sum(x['followers_count']>0 for x in rows),'max':{k:max([x[k] for x in rows] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']},'reports':reports}
    (OUT/f'summary_{NAME}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':asyncio.run(main())
