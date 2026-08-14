import csv
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT = Path('historical_hot_output')
OUT.mkdir(exist_ok=True)

START = date(2026, 7, 15)
END = date(2026, 8, 14)
START_TS = int(datetime(2026, 7, 14, 16, 0, tzinfo=timezone.utc).timestamp())  # 2026-07-15 00:00 China
END_TS = int(datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc).timestamp())    # 2026-08-15 00:00 China
ARCHIVE_RAW = 'https://raw.githubusercontent.com/lornshrimp/Lorn.TechProductManagerContentCreatorSkill/main/hotspot/%E6%A6%9C%E5%8D%95/{day}/%E5%A4%B4%E6%9D%A1%E7%83%AD%E6%A6%9C.md'

BLOCK = [
    '习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','俄罗斯','乌克兰','以色列','加沙','伊朗','特朗普','普京','泽连斯基','拜登','选举','总统','总理','首相','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防','北约','美军','空军','海军','陆军','领土','藏南','中美','美日','美国政府','联合国','侵略','制裁'
]
VIDEO_BAD = ['awemevideo','xiaoshipin','hotsoon_video','sslocal://aweme','short_video']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


def to_int(v):
    try:
        if v in (None, ''): return 0
        return int(float(v))
    except Exception:
        return 0


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from walk(v)
            elif isinstance(v, str):
                s=v.strip()
                if s[:1] in '[{':
                    try: yield from walk(json.loads(s))
                    except Exception: pass
    elif isinstance(obj, list):
        for v in obj: yield from walk(v)


def political(text):
    return any(k in text for k in BLOCK)


def parse_archive_day(sess, day):
    url = ARCHIVE_RAW.format(day=day.isoformat())
    try:
        r = sess.get(url, timeout=20)
    except Exception:
        return []
    if r.status_code != 200: return []
    titles=[]
    for line in r.text.splitlines():
        line=line.strip()
        if not line.startswith('|') or line.startswith('|---') or '标题' in line or '热搜词' in line or '来源' in line:
            continue
        parts=[p.strip() for p in line.strip('|').split('|')]
        if len(parts) < 2: continue
        # Supported archive shapes: rank|title|heat and title|source.
        if parts[0].isdigit() and len(parts) >= 2:
            title=parts[1]
        else:
            title=parts[0]
        title=re.sub(r'^[0-9]+[\.、 ]*','',title).strip()
        if len(title) < 4 or title in ('-', '—') or political(title): continue
        titles.append(title)
    return titles


def all_topics(sess):
    out=[];seen=set();day=START; available=[]
    while day <= END:
        ts=parse_archive_day(sess,day)
        if ts: available.append({'date':day.isoformat(),'count':len(ts)})
        for title in ts:
            key=re.sub(r'\s+','',title)
            if key not in seen:
                seen.add(key);out.append((day.isoformat(),title))
        day += timedelta(days=1)
    (OUT/'archive_coverage.json').write_text(json.dumps(available,ensure_ascii=False,indent=2),encoding='utf-8')
    return out,available


def provenance(d):
    vals=[]
    for k,v in d.items():
        lk=str(k).lower()
        if any(x in lk for x in ['url','schema','type','source','display','detail']):
            if isinstance(v,(str,int,float,bool)): vals.append(str(v))
    joined=' '.join(vals).lower()
    if any(b in joined for b in VIDEO_BAD): return None
    urls=[]
    for k in ['article_url','ttsearch_msite_url','seo_url','share_url','source_url','display_url','url']:
        v=d.get(k)
        if isinstance(v,str) and v: urls.append(v)
    native_url=''
    for u in urls:
        lu=u.lower()
        if 'toutiao.com/article/' in lu or 'toutiao.com/w/' in lu or 'm.toutiao.com/i' in lu:
            native_url=u;break
    if not native_url:
        for k in ['detail_schema','schema','open_url','article_url']:
            v=str(d.get(k) or '')
            if 'sslocal://thread_detail' in v:
                native_url=v;break
    if not native_url: return None
    return native_url


def normalize(d, topic_date, query, tab):
    if not isinstance(d,dict): return None
    gid=d.get('group_id') or d.get('groupId') or d.get('item_id')
    title=d.get('title') or d.get('abstract') or d.get('description') or ''
    if not gid or not title: return None
    title=re.sub(r'\s+',' ',str(title)).strip()
    abstract=re.sub(r'\s+',' ',str(d.get('abstract') or d.get('description') or '')).strip()
    if political(title+' '+abstract): return None
    native_url=provenance(d)
    if not native_url: return None
    publish=to_int(d.get('publish_time') or d.get('create_time') or d.get('behot_time'))
    if not publish or not (START_TS <= publish < END_TS): return None
    has_video=bool(d.get('has_video') or d.get('video_id') or d.get('video_duration'))
    # Article or micro-headline only; discard video objects even if they have a Toutiao wrapper URL.
    if has_video: return None
    digg=to_int(d.get('digg_count') or d.get('like_count'))
    comment=to_int(d.get('comment_count') or d.get('comments_count'))
    forward=to_int(d.get('forward_count') or d.get('share_count'))
    repin=to_int(d.get('repin_count') or d.get('favorite_count') or d.get('collect_count'))
    read=to_int(d.get('read_count'))
    if max(digg,comment,forward,repin,read)==0: return None
    media=d.get('media_name') or d.get('source') or ''
    if not media and isinstance(d.get('media_info'),dict):
        media=d['media_info'].get('name') or d['media_info'].get('user_name') or ''
    return {
        'topic_date':topic_date,'query':query,'tab':tab,'group_id':str(gid),'title':title[:500],
        'abstract':abstract[:3000],'url':native_url,'media_name':str(media),
        'media_url':str(d.get('media_url') or d.get('user_source_url') or ''),
        'user_id':str(d.get('user_id') or d.get('media_creator_id') or ''),
        'publish_time':publish,'read_count':read,'digg_count':digg,'comment_count':comment,
        'forward_count':forward,'repin_count':repin,
        'max_interaction':max(digg,comment,forward,repin),
        'interaction_sum':digg+comment+forward+repin,
        'image_count':to_int(d.get('image_count')),
        'content_schema_type':str(d.get('content_schema_type') or ''),
    }


def parse_html(text, topic_date, query, tab):
    soup=BeautifulSoup(text,'lxml'); rows=[]
    for script in soup.find_all('script'):
        body=(script.string or script.get_text() or '').strip()
        if not body: continue
        payloads=[]
        if body[:1] in '[{': payloads.append(body.rstrip(';'))
        if '"extraData"' in body and not payloads:
            m=re.search(r'(\{"extraData\".*\})',body,re.S)
            if m: payloads.append(m.group(1))
        for payload in payloads:
            try: obj=json.loads(payload)
            except Exception: continue
            for d in walk(obj):
                r=normalize(d,topic_date,query,tab)
                if r: rows.append(r)
    best={}
    for r in rows:
        rank=(r['max_interaction'],r['interaction_sum'],sum(bool(r[k]) for k in ['url','media_name','publish_time']))
        if r['group_id'] not in best or rank>best[r['group_id']][0]:best[r['group_id']]=(rank,r)
    return [x[1] for x in best.values()]


def main():
    shard=int(os.environ.get('SHARD_INDEX','0')); total=int(os.environ.get('TOTAL_SHARDS','20'))
    sess=requests.Session();sess.headers.update(HEADERS)
    topics,coverage=all_topics(sess)
    mine=[x for i,x in enumerate(topics) if i%total==shard]
    rows=[];log=[]
    tabs=[('information','information'),('weitoutiao','weitoutiao')]
    for i,(topic_date,q) in enumerate(mine,1):
        for label,pd in tabs:
            url='https://www.toutiao.com/search/?keyword='+quote(q)+'&pd='+pd
            parsed=[];status='ERROR';size=0
            try:
                r=sess.get(url,timeout=28,allow_redirects=True);status=r.status_code;size=len(r.content)
                if r.status_code==200:parsed=parse_html(r.text,topic_date,q,label)
                if r.status_code in (401,403,429):
                    log.append({'query':q,'topic_date':topic_date,'tab':label,'status':status,'bytes':size,'parsed':0,'stopped':True});break
            except Exception as e:
                log.append({'query':q,'topic_date':topic_date,'tab':label,'status':'ERROR','error':repr(e),'parsed':0});time.sleep(1.0);continue
            rows.extend(parsed)
            log.append({'query':q,'topic_date':topic_date,'tab':label,'status':status,'bytes':size,'parsed':len(parsed)})
            time.sleep(0.75)
        if i%10==0: print(f'shard={shard} progress={i}/{len(mine)} raw={len(rows)}')
    best={}
    for r in rows:
        rank=(r['max_interaction'],r['interaction_sum'])
        if r['group_id'] not in best or rank>best[r['group_id']][0]:best[r['group_id']]=(rank,r)
    uniq=[x[1] for x in best.values()]
    fields=['topic_date','query','tab','group_id','title','abstract','url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','interaction_sum','image_count','content_schema_type']
    with (OUT/f'historical_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(uniq,key=lambda x:(x['max_interaction'],x['read_count']),reverse=True))
    (OUT/f'historical_{shard}_requests.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={
      'shard':shard,'total_shards':total,'archive_days':len(coverage),'all_nonpolitical_topics':len(topics),'queries_in_shard':len(mine),'raw_rows':len(rows),'unique_rows':len(uniq),
      'viral10k':sum(x['max_interaction']>=10000 for x in uniq),
      'viral3k':sum(x['max_interaction']>=3000 for x in uniq),
      'max':{k:max([x[k] for x in uniq] or [0]) for k in ['read_count','digg_count','comment_count','forward_count','repin_count','max_interaction']}
    }
    (OUT/f'historical_{shard}_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
