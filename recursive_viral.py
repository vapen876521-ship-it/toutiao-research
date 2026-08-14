import csv, json, os, re, time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from harvest_first_pages import HEADERS, parse_html

OUT=Path('recursive_output');OUT.mkdir(exist_ok=True)
SEEDS=['vlog','vlog日常','日常vlog','记录真实生活','内容过于真实','一人分饰多角','夫妻日常','装修','大学生','打工人','搞笑','装修避坑','收纳整理','真实生活分享计划','生活小妙招','摩托车','租房','涨知识','准大一','准大一新生','剧情','游戏解说','万万没想到','空调','干货分享','美食','第一视角','生活小技巧','搬家','情侣日常','美食vlog','处世法则','职场避坑指南','高情商','说话技巧','第一视角vlog','收纳','校园','短视频创业','实用小技巧','自媒体创业','测评','正能量','新手上路','大学生活','经验分享','装修日记vlog','游戏怪谈','家庭','家电小常识','摩旅','情感共鸣','法律科普','数码科技','旅游攻略','租房攻略','小技巧','暑假工','实用干货分享','电动车','年轻人','机车','骑行安全','装修干货','装修设计','家长必读','家庭教育','亲子','育儿','宝妈','二胎','中年生活','退休生活','养老','独居','人情世故','女性成长','男性成长','家常菜','早餐','晚餐','外卖','菜市场','食品安全','探店','地方美食','职场','工资','跳槽','面试','辞职','失业','副业','摆摊','开店','省钱','消费体验','猫','狗','宠物','养猫','养狗','跑步','健身','骑行','徒步','露营','旅行','自驾游','酒店','民宿','景区','城市漫步','县城生活','农村生活','街头见闻','手机','电脑','AI','人工智能','机器人','摄影','短视频','自媒体','口播视频','汽车','新能源车','新手司机','二手车','搞笑段子','真实生活vlog','生活记录','反差','名场面','人生哲理','生活妙招','避坑指南','真实测评','音乐分享','影视','电影','电视剧','综艺','舞蹈','穿搭','护肤','母婴','读书','写作']
MODS=['高赞','点赞破万','十万点赞','爆火','上热门','网友热议','内容过于真实','真实生活','真实经历','第一视角','vlog','避坑','教程','经验分享','实测','反差']
BLOCK=['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']

def n(v):
    try:return int(float(v or 0))
    except:return 0

def gid_ts(gid):
    try:
        x=int(str(gid))>>32
        return x if 1600000000<=x<=2000000000 else None
    except:return None

def ts(r):return n(r.get('publish_time')) or gid_ts(r.get('group_id'))
def viral(r,cutoff,now):
    text=(r.get('title') or '')+' '+(r.get('abstract') or '')
    if any(x in text for x in BLOCK):return False
    t=ts(r)
    if not t or t<cutoff or t>now+86400:return False
    return max(n(r.get('digg_count')),n(r.get('comment_count')),n(r.get('forward_count')),n(r.get('repin_count')))>=10000

def tags(text):
    out=[]
    for h in re.findall(r'#([^#\s，。！？,;；:：]{2,28})',text or ''):
        h=h.strip('[]【】()（）,.，。!?！？;；:：')
        if 2<=len(h)<=25 and not any(x in h for x in BLOCK):out.append(h)
    return out

def main():
    shard=int(os.environ.get('SHARD_INDEX','0'));total=int(os.environ.get('TOTAL_SHARDS','1'));limit=int(os.environ.get('QUERY_LIMIT','700'))
    initial=[]
    expanded=[]
    for s in SEEDS:
        expanded.append(s)
        for m in MODS:
            if (hash(s+m)&15)==shard%16:expanded.append(f'{s} {m}')
    for i,q in enumerate(expanded):
        if i%total==shard:initial.append(q)
    q=deque(initial);seen=set();queued=set(initial);rows=[];reports=[]
    sess=requests.Session();sess.headers.update(HEADERS)
    now=int(datetime.now(timezone.utc).timestamp());cutoff=int((datetime.now(timezone.utc)-timedelta(days=31)).timestamp())
    while q and len(seen)<limit:
        term=q.popleft();queued.discard(term)
        if term in seen:continue
        seen.add(term);parsed=[];status=''
        try:
            r=sess.get('https://www.toutiao.com/search/?keyword='+quote(term),timeout=25,allow_redirects=True)
            status=r.status_code;parsed=parse_html(r.text,term) if r.status_code==200 else []
        except Exception as e:status='ERROR:'+repr(e)
        hit=0
        for x in parsed:
            if viral(x,cutoff,now):
                hit+=1;x=dict(x);x['effective_publish_time']=ts(x)
                vals={k:n(x.get(k)) for k in ['digg_count','comment_count','forward_count','repin_count']};x['max_interaction']=max(vals.values());x['qualifying_metrics']='|'.join(k for k,v in vals.items() if v>=10000);rows.append(x)
            # Use moderately popular cards only as navigation to discover fresh hashtags; they never enter final output.
            if max(n(x.get('digg_count')),n(x.get('comment_count')),n(x.get('forward_count')),n(x.get('repin_count')))>=1000:
                text=(x.get('title') or '')+' '+(x.get('abstract') or '')
                for h in tags(text):
                    if h not in seen and h not in queued and len(queued)<2000:
                        q.append(h);queued.add(h)
                        if (hash(h)&3)==shard%4:
                            for m in ['高赞','爆火','真实生活','内容过于真实']:
                                z=f'{h} {m}'
                                if z not in seen and z not in queued:q.append(z);queued.add(z)
        reports.append({'query':term,'status':status,'parsed':len(parsed),'viral_recent':hit,'queue':len(q)})
        if len(seen)%50==0:print(json.dumps({'shard':shard,'queries':len(seen),'queue':len(q),'viral_raw':len(rows)},ensure_ascii=False),flush=True)
        time.sleep(0.28)
    best={}
    for x in rows:
        gid=str(x['group_id']);rank=(n(x.get('max_interaction')),len(x.get('title') or '')+len(x.get('abstract') or ''))
        if gid not in best or rank>best[gid][0]:best[gid]=(rank,x)
    out=[v[1] for v in best.values()];out.sort(key=lambda r:n(r.get('max_interaction')),reverse=True)
    fields=['query','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','effective_publish_time','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','qualifying_metrics','image_count','content_schema_type','has_video','has_gallery']
    with (OUT/f'recursive_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    (OUT/f'report_{shard}.json').write_text(json.dumps(reports,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'shard':shard,'queries':len(seen),'viral_raw':len(rows),'viral_unique':len(out),'remaining_queue':len(q)},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
