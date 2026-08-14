import base64
import csv
import glob
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd
from playwright.sync_api import sync_playwright

OUT = Path('browser_enrich_output')
OUT.mkdir(exist_ok=True)
START_TS = int(datetime(2026, 7, 14, 16, 0, tzinfo=timezone.utc).timestamp())
END_TS = int(datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc).timestamp())
BLOCK = ['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','俄罗斯','乌克兰','以色列','加沙','伊朗','特朗普','普京','泽连斯基','拜登','选举','总统','总理','首相','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防','北约','美军','空军','海军','陆军','领土','藏南','中美','美日','美国政府','联合国','侵略','制裁']


def as_int(v):
    try:
        if v in (None, ''): return 0
        return int(float(v))
    except Exception:
        return 0


def gid_ts(gid):
    try:
        s=str(gid)
        if re.fullmatch(r'\d{18,20}', s):
            x=int(s)>>32
            if 1500000000 <= x <= 2100000000: return x
    except Exception:
        pass
    return 0


def blocked(text):
    return any(k in (text or '') for k in BLOCK)


def stable_shard(gid, total):
    return int(hashlib.md5(str(gid).encode()).hexdigest()[:8],16) % total


def load_seeds():
    frames=[]
    for f in glob.glob('seed_inputs/**/*.csv', recursive=True):
        try:
            d=pd.read_csv(f, dtype=str)
        except Exception:
            continue
        if 'group_id' not in d.columns or 'title' not in d.columns: continue
        d['_source_file']=f
        frames.append(d)
    if not frames: return []
    df=pd.concat(frames, ignore_index=True, sort=False)
    for c in ['digg_count','comment_count','forward_count','repin_count','publish_time','effective_publish_time']:
        if c not in df.columns: df[c]=''
    acc={}
    for _,r in df.iterrows():
        gid=str(r.get('group_id') or '').strip()
        if not gid or gid.lower()=='nan': continue
        if gid.endswith('.0') and gid[:-2].isdigit(): gid=gid[:-2]
        title=str(r.get('title') or '').strip()
        if blocked(title+' '+str(r.get('abstract') or '')): continue
        pt=as_int(r.get('publish_time')) or as_int(r.get('effective_publish_time')) or gid_ts(gid)
        if not (START_TS <= pt < END_TS): continue
        metrics={c:as_int(r.get(c)) for c in ['digg_count','comment_count','forward_count','repin_count']}
        core=max(metrics.values())
        if core < 10000: continue
        cur=acc.get(gid)
        item={'group_id':gid,'title':title,'publish_time':pt,'source_file':str(r.get('_source_file') or ''),**metrics,'core_max':core}
        if cur is None:
            acc[gid]=item
        else:
            for c in ['digg_count','comment_count','forward_count','repin_count','core_max']:
                cur[c]=max(cur[c],item[c])
            if len(title)>len(cur['title']): cur['title']=title
            cur['source_file'] += '|'+item['source_file']
    return sorted(acc.values(), key=lambda x:x['core_max'], reverse=True)


def maybe_decode_raw(s):
    if not isinstance(s,str) or len(s)<20: return None
    try:
        pad='='*((4-len(s)%4)%4)
        raw=base64.b64decode(s+pad)
        if raw[:1] not in (b'{',b'['): return None
        return json.loads(raw.decode('utf-8','ignore'))
    except Exception:
        return None


def walk(o):
    if isinstance(o,dict):
        yield o
        for k,v in o.items():
            if k=='raw_data':
                z=maybe_decode_raw(v)
                if z is not None: yield from walk(z)
            elif isinstance(v,(dict,list)): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)


def first_nested(d, keys):
    for obj in walk(d):
        for k in keys:
            if k in obj and obj[k] not in (None,''):
                return obj[k]
    return None


def follower_for_author(obj, uid):
    vals=[]
    for d in walk(obj):
        f=0
        for k in ['followers_count','follower_count','fans_count']:
            if k in d: f=max(f,as_int(d.get(k)))
        if not f: continue
        ids=[]
        for k in ['user_id','uid','author_id','media_id']:
            if k in d: ids.append(str(d.get(k)))
        ui=d.get('user_info') if isinstance(d.get('user_info'),dict) else {}
        if ui:
            ids += [str(ui.get(k)) for k in ['user_id','uid'] if ui.get(k)]
        if not uid or str(uid) in ids or not ids:
            vals.append(f)
    return max(vals or [0])


def item_row(d, response_url, seed_gid, author_uid):
    gid=d.get('group_id') or d.get('groupId') or d.get('item_id')
    if not gid:
        cand=d.get('id')
        if str(cand).isdigit() and len(str(cand))>=15: gid=cand
    if not gid: return None
    gid=str(gid)
    title=d.get('title') or d.get('Title') or d.get('abstract') or d.get('Abstract') or ''
    if not isinstance(title,str): title=str(title or '')
    if not title.strip() or blocked(title): return None
    logpb=d.get('log_pb') if isinstance(d.get('log_pb'),dict) else {}
    mi=d.get('media_info') if isinstance(d.get('media_info'),dict) else {}
    uid=d.get('user_id') or logpb.get('author_id') or mi.get('user_id') or first_nested(d,['user_id']) or ''
    uname=mi.get('name') or mi.get('user_name') or first_nested(d,['user_name','name']) or ''
    category=parse_qs(urlparse(response_url).query).get('category',[''])[0]
    if author_uid:
        if uid and str(uid)!=str(author_uid): return None
        if not uid and category!='pc_profile_article': return None
        uid=uid or author_uid
    forward=0
    if isinstance(d.get('forward_info'),dict): forward=as_int(d['forward_info'].get('forward_count'))
    forward=max(forward,as_int(d.get('forward_count')))
    has_video=bool(d.get('has_video') or d.get('has_m3u8_video') or d.get('has_mp4_video') or d.get('video_id'))
    pub=as_int(d.get('publish_time')) or as_int(d.get('behot_time')) or gid_ts(gid)
    images=d.get('image_list') if isinstance(d.get('image_list'),list) else []
    return {
        'seed_group_id':seed_gid,'group_id':gid,'title':re.sub(r'\s+',' ',title).strip()[:500],
        'user_id':str(uid or ''),'user_name':str(uname or ''),
        'publish_time':pub,'digg_count':as_int(d.get('digg_count')),'comment_count':as_int(d.get('comment_count')),
        'forward_count':forward,'repin_count':as_int(d.get('repin_count')),'read_count':as_int(d.get('read_count')),
        'followers_count':follower_for_author(d,uid),'has_video':has_video,'group_source':d.get('group_source') or '',
        'article_url':d.get('article_url') or d.get('display_url') or d.get('share_url') or '',
        'image_count':len(images) or as_int(d.get('gallary_image_count')) or as_int(d.get('image_count')),
        'response_category':category,
    }


def parse_captured(captured, seed_gid, author_uid=''):
    author={}
    posts=[]
    followers=[]
    for ent in captured:
        u=ent['url']; obj=ent.get('json')
        if not isinstance(obj,(dict,list)): continue
        if 'article/v4/tab_comments' in u:
            g=obj.get('group') if isinstance(obj,dict) and isinstance(obj.get('group'),dict) else {}
            if str(g.get('group_id') or '')==str(seed_gid):
                author={
                    'user_id':str(g.get('user_id') or ''),'user_name':str(g.get('user_name') or ''),
                    'is_video':g.get('is_video'),'total_comments':as_int(obj.get('total_number')),
                }
        if 'api/pc/list/feed' in u:
            f=follower_for_author(obj,author_uid or author.get('user_id'))
            if f: followers.append(f)
            data=obj.get('data') if isinstance(obj,dict) else None
            if isinstance(data,list):
                for d in data:
                    if isinstance(d,dict):
                        row=item_row(d,u,seed_gid,author_uid or author.get('user_id'))
                        if row: posts.append(row)
    if followers: author['followers_count']=max(followers)
    return author,posts


def text_follower(page):
    try: txt=page.locator('body').inner_text(timeout=3000)
    except Exception: return 0
    vals=[]
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(万)?\s*粉丝',txt):
        x=float(m.group(1))*(10000 if m.group(2) else 1); vals.append(int(x))
    return max(vals or [0])


def main():
    shard=int(os.environ.get('SHARD_INDEX','0')); total=int(os.environ.get('TOTAL_SHARDS','20'))
    seeds=[s for s in load_seeds() if stable_shard(s['group_id'],total)==shard]
    seed_rows=[]; all_posts=[]; seen_authors={}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        ctx=browser.new_context(viewport={'width':1365,'height':900}, locale='zh-CN', user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
        page=ctx.new_page(); current={'captured':[]}
        def handler(resp):
            u=resp.url
            if 'article/v4/tab_comments' not in u and 'api/pc/list/feed' not in u: return
            try: obj=resp.json()
            except Exception: return
            current['captured'].append({'url':u,'status':resp.status,'json':obj})
        page.on('response',handler)
        try:
            page.goto('https://www.toutiao.com/',wait_until='domcontentloaded',timeout=30000); page.wait_for_timeout(2000)
        except Exception: pass
        for idx,s in enumerate(seeds,1):
            gid=s['group_id']; current['captured']=[]; final_url=''; page_title=''; err=''
            for url in [f'https://www.toutiao.com/group/{gid}/',f'https://www.toutiao.com/video/{gid}/']:
                try:
                    page.goto(url,wait_until='domcontentloaded',timeout=30000); page.wait_for_timeout(3200)
                    page.mouse.wheel(0,1200); page.wait_for_timeout(1200)
                    final_url=page.url; page_title=page.title()
                except Exception as e:
                    err=repr(e)[:300]
                a,_=parse_captured(current['captured'],gid)
                if a.get('user_id'): break
            author,posts=parse_captured(current['captured'],gid)
            uid=author.get('user_id',''); uname=author.get('user_name','')
            profile_follow=0; profile_url=''
            if uid and uid not in seen_authors:
                profile_url=f'https://www.toutiao.com/c/user/{uid}/'
                before=len(current['captured'])
                try:
                    page.goto(profile_url,wait_until='domcontentloaded',timeout=30000); page.wait_for_timeout(3500)
                    page.mouse.wheel(0,1500); page.wait_for_timeout(1800)
                    profile_follow=text_follower(page)
                except Exception as e:
                    err=(err+' | profile:'+repr(e))[:500]
                extra=current['captured'][before:]
                a2,p2=parse_captured(extra,gid,uid)
                profile_follow=max(profile_follow,as_int(a2.get('followers_count')))
                posts.extend(p2)
                seen_authors[uid]=profile_follow
            elif uid:
                profile_follow=seen_authors.get(uid,0)
            follower=max(as_int(author.get('followers_count')),profile_follow)
            for r in posts:
                if follower and str(r.get('user_id'))==str(uid): r['followers_count']=max(as_int(r.get('followers_count')),follower)
            all_posts.extend(posts)
            seed_rows.append({
                **s,'author_user_id':uid,'author_name':uname,'is_video':author.get('is_video',''),
                'browser_total_comments':as_int(author.get('total_comments')),'followers_count':follower,
                'profile_url':profile_url,'detail_final_url':final_url,'page_title':page_title,'captured_responses':len(current['captured']),'error':err,
            })
            print(f'shard={shard} {idx}/{len(seeds)} gid={gid} author={uid or "?"} video={author.get("is_video")} followers={follower} posts={len(posts)}')
            time.sleep(1.5)
        browser.close()
    # dedup profile posts by gid keeping max interaction/richness
    best={}
    for r in all_posts:
        r['core_max']=max(as_int(r.get(c)) for c in ['digg_count','comment_count','forward_count','repin_count'])
        score=(r['core_max'],as_int(r.get('followers_count')),len(r.get('title','')))
        if r['group_id'] not in best or score>best[r['group_id']][0]: best[r['group_id']]=(score,r)
    posts=[x[1] for x in best.values()]
    sf=OUT/f'seed_enriched_{shard}.csv'; pf=OUT/f'profile_posts_{shard}.csv'
    if seed_rows: pd.DataFrame(seed_rows).to_csv(sf,index=False,encoding='utf-8-sig')
    else: pd.DataFrame(columns=['group_id']).to_csv(sf,index=False,encoding='utf-8-sig')
    if posts: pd.DataFrame(posts).to_csv(pf,index=False,encoding='utf-8-sig')
    else: pd.DataFrame(columns=['group_id']).to_csv(pf,index=False,encoding='utf-8-sig')
    recent=[r for r in posts if START_TS <= as_int(r.get('publish_time')) < END_TS]
    summary={
        'shard':shard,'seeds':len(seeds),'resolved_authors':sum(bool(r.get('author_user_id')) for r in seed_rows),
        'video_true':sum(str(r.get('is_video')).lower()=='true' for r in seed_rows),'video_false':sum(str(r.get('is_video')).lower()=='false' for r in seed_rows),
        'followers_resolved':sum(as_int(r.get('followers_count'))>0 for r in seed_rows),'profile_posts_unique':len(posts),'recent_profile_posts':len(recent),
        'recent_profile_viral10k':sum(max(as_int(r.get(c)) for c in ['digg_count','comment_count','forward_count','repin_count'])>=10000 for r in recent),
    }
    (OUT/f'summary_{shard}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__': main()
