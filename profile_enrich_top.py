import asyncio, csv, glob, json, os, re
from pathlib import Path
import pandas as pd
from playwright.async_api import async_playwright

OUT=Path('profile_top_output'); OUT.mkdir(exist_ok=True)
SHARD=int(os.getenv('SHARD_INDEX','0')); TOTAL=int(os.getenv('TOTAL_SHARDS','4')); LIMIT=int(os.getenv('PROFILE_LIMIT','200'))
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'

def n(v):
    try:return int(float(v or 0))
    except:return 0

def parse_author_token(author_links, media_name):
    if not isinstance(author_links,str) or not author_links.strip(): return ''
    try: arr=json.loads(author_links)
    except:return ''
    name=str(media_name or '').strip()
    for x in arr:
        if not isinstance(x,dict): continue
        h=str(x.get('href') or ''); t=str(x.get('text') or '').strip()
        if name and t==name and '/c/user/token/' in h:
            m=re.search(r'/c/user/token/([^/?]+)',h)
            if m:return m.group(1)
    for x in arr:
        if not isinstance(x,dict): continue
        h=str(x.get('href') or ''); t=str(x.get('text') or '').strip()
        if '/c/user/token/' in h and (not name or t==name):
            m=re.search(r'/c/user/token/([^/?]+)',h)
            if m:return m.group(1)
    return ''

def load_top():
    files=glob.glob('detail_inputs/**/detail_enriched_*.csv',recursive=True)
    if not files: raise RuntimeError('no detail csv inputs')
    df=pd.concat([pd.read_csv(f,low_memory=False) for f in files],ignore_index=True)
    df['group_id']=df['group_id'].astype(str)
    # Patch author links for the high-engagement retry set.
    rfiles=glob.glob('retry_input/**/retry_hot_details.csv',recursive=True)
    if rfiles:
        rt=pd.read_csv(rfiles[0],low_memory=False); rt['group_id']=rt['group_id'].astype(str)
        rp=rt.set_index('group_id')
        for gid in rp.index:
            m=df.group_id==gid
            if m.any() and 'author_links' in rp.columns:
                df.loc[m,'author_links']=rp.loc[gid,'author_links']
    for c in ['max_interaction','interaction_sum']:
        df[c]=pd.to_numeric(df.get(c,0),errors='coerce').fillna(0)
    df['author_token']=df.apply(lambda r:parse_author_token(r.get('author_links'),r.get('media_name')),axis=1)
    top=(df[df.author_token!=''].sort_values(['max_interaction','interaction_sum'],ascending=False)
         .drop_duplicates('author_token').head(LIMIT))
    return top[['author_token','media_name','group_id','title','max_interaction','interaction_sum']].to_dict('records')

def walk(o):
    if isinstance(o,dict):
        yield o
        for v in o.values():
            if isinstance(v,(dict,list)): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)

def parse_compact_num(s):
    s=str(s or '').replace(',','').strip()
    m=re.search(r'(\d+(?:\.\d+)?)\s*([万wW]?)',s)
    if not m:return 0
    v=float(m.group(1)); unit=m.group(2)
    return int(v*10000) if unit in ('万','w','W') else int(v)

async def profile_one(ctx, rec):
    token=rec['author_token']; expected=str(rec.get('media_name') or '')
    url=f'https://www.toutiao.com/c/user/token/{token}/?source=tuwen_detail'
    page=await ctx.new_page(); candidates=[]; response_urls=[]
    async def on_resp(resp):
        if resp.request.resource_type not in ('xhr','fetch'): return
        if 'toutiao.com' not in resp.url: return
        try:
            ctype=(resp.headers.get('content-type') or '').lower()
            if 'json' not in ctype and '/api/' not in resp.url: return
            js=await resp.json()
        except:return
        response_urls.append(resp.url[:500])
        for d in walk(js):
            if not isinstance(d,dict):continue
            fc=None; key=''
            for k in ('followers_count','follower_count','fans_count'):
                if k in d:
                    fc=n(d.get(k)); key=k; break
            if fc is None: continue
            name=str(d.get('name') or d.get('media_name') or d.get('screen_name') or d.get('user_name') or d.get('uname') or '')
            tok=str(d.get('token') or d.get('user_auth_info') or '')
            candidates.append({'followers':fc,'name':name,'key':key,'token_hint':tok[:120],'response_url':resp.url[:500]})
    page.on('response',on_resp)
    out=dict(rec); out.update({'profile_url':url,'http_status':0,'final_url':'','followers_count':0,'followers_source':'','followers_confidence':'unresolved','profile_title':'','dom_followers_text':'','network_candidates_json':'[]','error':''})
    try:
        resp=await page.goto(url,wait_until='domcontentloaded',timeout=50000)
        out['http_status']=resp.status if resp else 0
        await page.wait_for_timeout(3500)
        await page.mouse.wheel(0,1200); await page.wait_for_timeout(1200)
        out['final_url']=page.url
        try: out['profile_title']=await page.title()
        except:pass
        body=''
        try: body=await page.locator('body').inner_text(timeout=5000)
        except:pass
        # DOM patterns around 粉丝.
        dom=[]
        for pat in [r'([0-9]+(?:\.[0-9]+)?\s*万?)\s*粉丝',r'粉丝\s*([0-9]+(?:\.[0-9]+)?\s*万?)']:
            dom += re.findall(pat,body[:5000])
        if dom:
            out['dom_followers_text']='|'.join(dom[:5]); val=max(parse_compact_num(x) for x in dom)
            if val>=0:
                out['followers_count']=val; out['followers_source']='dom'; out['followers_confidence']='high'
        # Prefer exact-name network candidate, then a single unique candidate value.
        if not out['followers_count'] and candidates:
            exact=[x for x in candidates if expected and x['name']==expected]
            pool=exact if exact else candidates
            vals=[x['followers'] for x in pool if x['followers']>=0]
            if vals:
                # profile feeds may repeat the same profile object; mode by frequency.
                from collections import Counter
                val=Counter(vals).most_common(1)[0][0]
                out['followers_count']=int(val); out['followers_source']='network_exact_name' if exact else 'network_profile_page'
                out['followers_confidence']='high' if exact else ('medium' if len(set(vals))==1 else 'low')
        out['network_candidates_json']=json.dumps(candidates[:30],ensure_ascii=False)
    except Exception as e:
        out['error']=repr(e)[:500]
    page.remove_listener('response',on_resp)
    await page.close()
    return out

async def main():
    all_top=load_top(); mine=[r for i,r in enumerate(all_top) if i%TOTAL==SHARD]
    rows=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        ctx=await browser.new_context(locale='zh-CN',user_agent=UA)
        for i,rec in enumerate(mine,1):
            row=await profile_one(ctx,rec); rows.append(row)
            print(json.dumps({'shard':SHARD,'i':i,'name':rec['media_name'],'followers':row['followers_count'],'source':row['followers_source'],'confidence':row['followers_confidence'],'status':row['http_status']},ensure_ascii=False),flush=True)
            await asyncio.sleep(1.8)
        await browser.close()
    fields=sorted({k for r in rows for k in r.keys()}) if rows else ['author_token']
    with (OUT/f'profile_top_{SHARD}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    summary={'shard':SHARD,'assigned':len(mine),'rows':len(rows),'resolved':sum(1 for r in rows if r.get('followers_source')),'high_confidence':sum(1 for r in rows if r.get('followers_confidence')=='high'),'medium_confidence':sum(1 for r in rows if r.get('followers_confidence')=='medium'),'max_followers':max([r.get('followers_count',0) for r in rows] or [0])}
    (OUT/f'profile_top_{SHARD}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__': asyncio.run(main())
