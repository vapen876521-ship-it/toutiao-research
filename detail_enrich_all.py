import asyncio,csv,json,os,re
from pathlib import Path
from playwright.async_api import async_playwright

IN=Path('detail_input/toutiao_recent_native_posts.csv')
OUT=Path('detail_output');OUT.mkdir(exist_ok=True)
SHARD=int(os.getenv('SHARD_INDEX','0'));SHARDS=int(os.getenv('SHARD_COUNT','12'))
WAIT_MS=int(os.getenv('DETAIL_WAIT_MS','1800'));DELAY_MS=int(os.getenv('DETAIL_DELAY_MS','700'))

METRIC_KEYS=['digg_count','comment_count','forward_count','repin_count','read_count','user_id','media_name','author_token','followers_count','follower_count']

def num(v):
 try:return int(float(v or 0))
 except:return 0

def cnnum(s):
 s=str(s or '').strip().replace(',','')
 m=re.search(r'(\d+(?:\.\d+)?)\s*(万|亿)?',s)
 if not m:return 0
 x=float(m.group(1));u=m.group(2)
 if u=='万':x*=10000
 if u=='亿':x*=100000000
 return int(x)

def walk(obj,gid,out):
 if isinstance(obj,dict):
  vals=[str(obj.get(k) or '') for k in ['group_id','id','item_id']]
  if gid in vals:
   out.append({k:obj.get(k) for k in METRIC_KEYS if k in obj})
  for v in obj.values():walk(v,gid,out)
 elif isinstance(obj,list):
  for v in obj:walk(v,gid,out)

def best_net(items):
 if not items:return {}
 return max(items,key=lambda d:sum(k in d and d.get(k) not in (None,'') for k in METRIC_KEYS))

async def capture(resp,gid,items):
 try:
  if 'toutiao.com' not in resp.url:return
  ct=(resp.headers or {}).get('content-type','')
  if 'json' not in ct and '/api/' not in resp.url:return
  body=await resp.json();walk(body,gid,items)
 except:pass

async def extract(page):
 js="""() => {
 const sels=['article','[class*="article-content"]','[class*="syl-page-article"]','main'];
 let best=null;
 for (const s of sels){for(const e of document.querySelectorAll(s)){const t=(e.innerText||'').trim();if(t.length>200&&(!best||t.length>best.t.length))best={e:e,t:t,s:s};}}
 const root=best?best.e:document.body;
 const ps=[...root.querySelectorAll('p')].map(e=>(e.innerText||'').trim().replace(/\s+/g,' ')).filter(Boolean);
 const imgs=[...root.querySelectorAll('img')].map(e=>e.currentSrc||e.src||'').filter(x=>/^https?:/.test(x));
 const attrs=[...document.querySelectorAll('[aria-label],[title]')].map(e=>({aria:e.getAttribute('aria-label')||'',title:e.getAttribute('title')||'',text:(e.innerText||e.textContent||'').trim().slice(0,80)}));
 const links=[...document.querySelectorAll('a[href]')].map(a=>({href:a.href,text:(a.innerText||a.textContent||'').trim().replace(/\s+/g,' ').slice(0,80)})).filter(x=>/toutiao\.com\/(?:c\/user|user|profile)/.test(x.href));
 return {selector:best?best.s:'body',text:(best?best.t:(document.body.innerText||'')).slice(0,20000),paragraphs:ps.slice(0,160),images:[...new Set(imgs)].slice(0,100),attrs:attrs.slice(0,1800),links:links.slice(0,30)};
 }"""
 return await page.evaluate(js)

def semantic_candidates(attrs):
 likes=[];comments=[]
 for x in attrs:
  for s in [x.get('aria',''),x.get('title',''),x.get('text','')]:
   if not s:continue
   for p in [r'点赞\s*([\d.,]+(?:万|亿)?)',r'([\d.,]+(?:万|亿)?)\s*赞']:
    m=re.search(p,s)
    if m:
     v=cnnum(m.group(1))
     if 0<v<=10000000:likes.append(v)
   for p in [r'评论\s*([\d.,]+(?:万|亿)?)',r'([\d.,]+(?:万|亿)?)\s*(?:条)?评论']:
    m=re.search(p,s)
    if m:
     v=cnnum(m.group(1))
     if 0<v<=10000000:comments.append(v)
 return sorted(set(likes)),sorted(set(comments))

def anchored(cands,expected):
 if not cands:return 0
 expected=num(expected)
 if expected>0:
  # Engagement can drift between feed capture and detail visit; choose the semantic number closest to the trusted feed anchor.
  return min(cands,key=lambda x:(abs(x-expected)/max(expected,1),abs(x-expected)))
 return min(cands)

async def main():
 rows=list(csv.DictReader(IN.open(encoding='utf-8-sig',newline='')))
 mine=[r for i,r in enumerate(rows) if i%SHARDS==SHARD]
 fields=list(rows[0].keys())+['http_status','final_url','detail_verified','page_title','content_selector','content_chars','paragraph_count','paragraphs_json','first_3_paragraphs','last_3_paragraphs','content_text','detail_image_count','detail_image_urls','semantic_digg_count','semantic_comment_count','semantic_digg_delta','semantic_comment_delta','net_digg_count','net_comment_count','net_forward_count','net_repin_count','net_read_count','detail_media_name','detail_user_id','detail_author_token','detail_followers_count','author_links','detail_error']
 output=[]
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True)
  ctx=await b.new_context(locale='zh-CN',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36')
  for j,r in enumerate(mine,1):
   gid=str(r.get('group_id') or '');url=r.get('post_url') or f'https://www.toutiao.com/article/{gid}/';rec=dict(r);net=[];page=await ctx.new_page()
   page.on('response',lambda resp,gid=gid,net=net: asyncio.create_task(capture(resp,gid,net)))
   try:
    resp=await page.goto(url,wait_until='domcontentloaded',timeout=45000);await page.wait_for_timeout(WAIT_MS)
    d=await extract(page);lc,cc=semantic_candidates(d['attrs']);sl=anchored(lc,r.get('digg_count'));sc=anchored(cc,r.get('comment_count'));bn=best_net(net)
    final=page.url;status=resp.status if resp else 0;ps=d['paragraphs']
    rec.update({'http_status':status,'final_url':final,'detail_verified':bool(status==200 and gid in final and len(d['text'])>200),'page_title':await page.title(),'content_selector':d['selector'],'content_chars':len(d['text']),'paragraph_count':len(ps),'paragraphs_json':json.dumps(ps,ensure_ascii=False),'first_3_paragraphs':'\n'.join(ps[:3]),'last_3_paragraphs':'\n'.join(ps[-3:]),'content_text':d['text'],'detail_image_count':len(d['images']),'detail_image_urls':json.dumps(d['images'],ensure_ascii=False),'semantic_digg_count':sl,'semantic_comment_count':sc,'semantic_digg_delta':sl-num(r.get('digg_count')) if sl else 0,'semantic_comment_delta':sc-num(r.get('comment_count')) if sc else 0,'net_digg_count':num(bn.get('digg_count')),'net_comment_count':num(bn.get('comment_count')),'net_forward_count':num(bn.get('forward_count')),'net_repin_count':num(bn.get('repin_count')),'net_read_count':num(bn.get('read_count')),'detail_media_name':bn.get('media_name') or '','detail_user_id':bn.get('user_id') or '','detail_author_token':bn.get('author_token') or '','detail_followers_count':num(bn.get('followers_count') or bn.get('follower_count')),'author_links':json.dumps(d['links'],ensure_ascii=False),'detail_error':''})
   except Exception as e:
    rec.update({'http_status':0,'final_url':page.url,'detail_verified':False,'page_title':'','content_selector':'','content_chars':0,'paragraph_count':0,'paragraphs_json':'[]','first_3_paragraphs':'','last_3_paragraphs':'','content_text':'','detail_image_count':0,'detail_image_urls':'[]','semantic_digg_count':0,'semantic_comment_count':0,'semantic_digg_delta':0,'semantic_comment_delta':0,'net_digg_count':0,'net_comment_count':0,'net_forward_count':0,'net_repin_count':0,'net_read_count':0,'detail_media_name':'','detail_user_id':'','detail_author_token':'','detail_followers_count':0,'author_links':'[]','detail_error':repr(e)[:500]})
   output.append(rec);await page.close();await asyncio.sleep(DELAY_MS/1000)
   if j%25==0:print(json.dumps({'shard':SHARD,'done':j,'total':len(mine),'verified':sum(bool(x.get('detail_verified')) for x in output)},ensure_ascii=False))
  await b.close()
 path=OUT/f'detail_enriched_{SHARD:02d}.csv'
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(output)
 summary={'shard':SHARD,'rows':len(output),'verified':sum(bool(x.get('detail_verified')) for x in output),'failed':sum(not bool(x.get('detail_verified')) for x in output),'body_ge_1000':sum(num(x.get('content_chars'))>=1000 for x in output),'semantic_like_resolved':sum(num(x.get('semantic_digg_count'))>0 for x in output),'semantic_comment_resolved':sum(num(x.get('semantic_comment_count'))>0 for x in output),'semantic_like_close_20pct':sum(num(x.get('semantic_digg_count'))>0 and abs(num(x.get('semantic_digg_delta')))<=max(5,int(num(x.get('digg_count'))*.2)) for x in output),'semantic_comment_close_20pct':sum(num(x.get('semantic_comment_count'))>0 and abs(num(x.get('semantic_comment_delta')))<=max(5,int(num(x.get('comment_count'))*.2)) for x in output),'net_metrics_resolved':sum(any(num(x.get(k))>0 for k in ['net_digg_count','net_comment_count','net_forward_count','net_repin_count']) for x in output),'author_link_resolved':sum(x.get('author_links') not in ('','[]') for x in output),'followers_resolved':sum(num(x.get('detail_followers_count'))>0 for x in output)}
 (OUT/f'summary_{SHARD:02d}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
