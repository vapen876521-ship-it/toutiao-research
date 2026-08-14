import csv
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from harvest_first_pages import HEADERS, parse_html

OUT = Path('viral_output')
OUT.mkdir(exist_ok=True)

# Broad non-political/non-military topic universe. Search results are filtered again by
# harvest_first_pages.parse_html(), then by recency and interaction threshold below.
CORES = [
'装修','装修避坑','水电','卫生间','厨房装修','家装','收纳','收纳整理','断舍离','家务','小户型','租房','租房避坑','买房','搬家','物业','邻居','小区生活','家居','家电','空调','冰箱','洗衣机','智能家居','维修','漏水',
'大学生活','大学生','准大一','毕业生','高考','中考','初中','高中','学习方法','家长','家长必读','家庭教育','亲子','育儿','爸爸带娃','宝妈','二胎','儿童成长','老师','教师','作业','英语学习','数学学习','考研','就业',
'家庭','夫妻','婚姻','婆媳','情感','恋爱','相亲','分手','成年人的世界','情感共鸣','中年生活','中年夫妻','中年感悟','老年生活','退休生活','养老','独生子女','独居','人情世故','朋友关系','女性成长','男性成长','普通人生活','生活感悟','真实生活',
'美食','家常菜','早餐','午餐','晚餐','面食','小吃','火锅','烧烤','餐厅','外卖','买菜','菜市场','农贸市场','食品安全','咖啡','奶茶','水果','烘焙','厨艺','空气炸锅','减脂餐','探店','地方美食','夜市美食','街头美食','乡村美食',
'职场','办公室','打工人','工资','加薪','跳槽','面试','辞职','失业','同事关系','领导','销售','创业','副业','摆摊','小生意','个体户','开店','餐饮创业','合伙开店','赚钱','攒钱','省钱','消费观','性价比','网购','快递','二手','购物避坑','维权','服务体验','消费体验',
'猫','狗','萌宠','宠物','养猫','养狗','宠物医院','小狗','小猫','流浪猫','动物','养花','绿植','种菜','阳台种菜','钓鱼','跑步','健身','散步','瑜伽','羽毛球','乒乓球','骑行','徒步','露营','马拉松','体育生',
'旅游','旅行','自驾游','亲子游','酒店','民宿','景区','旅游攻略','旅行避坑','城市漫步','周末去哪玩','行李收纳','本地生活','城市生活','县城生活','小城生活','农村生活','返乡','农民','赶集','村里生活','街头见闻','社区生活','普通人故事','暖心故事','真实采访',
'手机','电脑','平板','耳机','数码','数码分享','AI','人工智能','大模型','机器人','软件','APP','摄影','拍照','短视频','短视频创业','自媒体','自媒体创业','口播视频','办公效率','网络安全','游戏','手游','电竞','直播','主播',
'汽车','新能源车','电动车','新手司机','停车','高速出行','汽车保养','二手车','车主','买车','用车','自驾','摩托车','骑车',
'搞笑','段子','搞笑段子','内容过于真实','一人分饰多角','日常vlog','第一视角vlog','生活vlog','真实生活vlog','记录真实生活','真实生活分享计划','生活记录','日常生活','反差','名场面','高情商','口才','人生哲理','干货','干货分享','实用技巧','生活妙招','避坑指南','真实测评','使用体验',
'音乐','音乐分享','音乐推荐','影视','电影','电视剧','综艺','演员','歌手','舞蹈','国风','穿搭','化妆','护肤','发型','女生变美','男生穿搭','母婴','婚礼','摄影技巧','手工','非遗','传统文化','读书','写作','兴趣爱好'
]

VIRAL = [
'网友热议','全网热议','火了','爆火','突然火了','爆款','上热门','十万点赞','10万赞','百万点赞','高赞','点赞破万','收藏起来','建议收藏','值得收藏','干货分享','经验分享','真实经历','亲身经历','真实感受','真实现状','真实生活','记录真实生活','内容过于真实','第一视角','vlog','日常vlog','避坑','避坑指南','踩坑','踩坑经历','后悔了','别踩坑','没想到','万万没想到','第一次','终于明白','看完破防','破防了','笑不活了','太真实了','反差太大','普通人','过来人','真心话','忠告','必看','必读','一定要记住','一定要知道','千万别','别再','实测','测评','对比','真实测评','现场','名场面','高情商','神回复','教程','方法','技巧','攻略'
]

RECENT = ['2026','2026年','8月','暑假','最近','这几天','今天','刚刚','今年','近期']
PERSONAS = ['普通人','上班族','打工人','大学生','毕业生','宝妈','奶爸','中年人','年轻人','退休人','独居女生','租房党','新手小白','过来人','00后','90后','95后','新手司机','创业者','店主','房东','租客','家长','学生']
SCENES = ['真实经历','真实生活','一天','一个月','第一次','最后','结果','后续','前后对比','真实感受','经验分享','避坑','省钱','踩坑','实测','挑战','日常','现场','vlog','反差']
CITIES = ['北京','上海','广州','深圳','杭州','南京','成都','重庆','武汉','西安','苏州','天津','长沙','郑州','青岛','济南','合肥','昆明','大理','厦门','福州','泉州','宁波','无锡','佛山','东莞','珠海','南昌','南宁','贵阳','哈尔滨','沈阳','大连','石家庄','太原','兰州','乌鲁木齐','海口','三亚','洛阳','徐州','温州','绍兴','常州','扬州','烟台','威海','临沂','阜阳']
LOCAL = ['租房','美食','探店','菜市场','夜市','打工生活','生活成本','周末去哪玩','旅游','自驾','小吃','本地生活','街头见闻','买房','通勤']
SEED_TAGS = [
'家长必读','教育','装修避坑','经验分享','大学生活','宇倩学姐','家长必看','南京租房','避坑指南','记录真实生活','干货分享','短视频创业','真实生活分享计划','情感','内容过于真实','中年感悟','晚年生活','装修细节','装修知识','情感共鸣','二胎辣妈','收纳整理','收纳','销售技巧','女性成长','数码分享','准大一','视频流量提升','记录工地生活','社区火锅','成都美食','口播视频','传递正能量','租房vlog','第一视角','家庭教育','生活小妙招','旅游攻略','学习规划','学霸秘籍','提分技巧','真实采访','普通人的生活状态','养老现实','真实生活分享vlog','家装避坑知识分享'
]

BLOCK = ['习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端','国际局势','外交','国防']


def all_keywords():
    out=[]; seen=set()
    def add(q):
        q=' '.join(q.split()).strip()
        if q and q not in seen and not any(x in q for x in BLOCK):
            seen.add(q); out.append(q)
    # Every core gets high-yield viral modifiers and a recency bias set.
    for c in CORES:
        add(c)
        for v in VIRAL:
            add(f'{c} {v}')
        for r in RECENT:
            add(f'{r} {c}')
        # deterministic persona/scene variants without full Cartesian explosion
        for i,p in enumerate(PERSONAS):
            if (hash(c+p) & 7) == 0:
                add(f'{p} {c}')
        for i,s in enumerate(SCENES):
            if (hash(c+s) & 7) == 1:
                add(f'{c} {s}')
    for tag in SEED_TAGS:
        add(tag); add('#'+tag); add(f'{tag} 高赞'); add(f'{tag} 2026'); add(f'{tag} 8月')
    for city in CITIES:
        for loc in LOCAL:
            add(f'{city} {loc}')
            add(f'{city} {loc} 真实生活')
            if loc in ('租房','美食','探店','菜市场','夜市','生活成本'):
                add(f'{city} {loc} 避坑')
    # Extra high-intent viral discovery phrases.
    for p in PERSONAS:
        for s in SCENES:
            add(f'{p} {s}')
            add(f'{p} {s} 内容过于真实')
    return out


def num(v):
    try: return int(float(v or 0))
    except Exception: return 0


def gid_ts(gid):
    try:
        n=int(str(gid).split('.')[0])
        if n >= 10**18:
            x=n >> 32
            if 1600000000 <= x <= 2000000000:
                return x
    except Exception:
        pass
    return None


def effective_ts(row):
    p=num(row.get('publish_time'))
    if p: return p
    return gid_ts(row.get('group_id'))


def qualifying(row, cutoff, now):
    text=(str(row.get('title') or '')+' '+str(row.get('abstract') or ''))
    if any(x in text for x in BLOCK): return False
    ts=effective_ts(row)
    if not ts or ts < cutoff or ts > now + 86400: return False
    mx=max(num(row.get('digg_count')),num(row.get('comment_count')),num(row.get('forward_count')),num(row.get('repin_count')))
    return mx >= 10000


def main():
    shard=int(os.environ.get('SHARD_INDEX','0')); total=int(os.environ.get('TOTAL_SHARDS','1'))
    kws=[q for i,q in enumerate(all_keywords()) if i % total == shard]
    sess=requests.Session(); sess.headers.update(HEADERS)
    now=int(datetime.now(timezone.utc).timestamp())
    cutoff=int((datetime.now(timezone.utc)-timedelta(days=31)).timestamp())
    rows=[]; reports=[]
    for i,q in enumerate(kws,1):
        parsed=[]
        for attempt in range(2):
            try:
                r=sess.get('https://www.toutiao.com/search/?keyword='+quote(q),timeout=25,allow_redirects=True)
                parsed=parse_html(r.text,q) if r.status_code==200 else []
                reports.append({'query':q,'attempt':attempt+1,'status':r.status_code,'bytes':len(r.content),'parsed':len(parsed),'viral_recent':sum(qualifying(x,cutoff,now) for x in parsed)})
                if parsed: break
            except Exception as e:
                reports.append({'query':q,'attempt':attempt+1,'status':'ERROR','error':repr(e),'parsed':0,'viral_recent':0})
                time.sleep(0.8)
        for x in parsed:
            if qualifying(x,cutoff,now):
                x=dict(x)
                x['effective_publish_time']=effective_ts(x)
                metrics={k:num(x.get(k)) for k in ['digg_count','comment_count','forward_count','repin_count']}
                x['max_interaction']=max(metrics.values())
                x['qualifying_metrics']='|'.join(k for k,v in metrics.items() if v>=10000)
                rows.append(x)
        time.sleep(0.30)
        if i % 50 == 0:
            print(json.dumps({'shard':shard,'progress':f'{i}/{len(kws)}','viral_rows':len(rows)},ensure_ascii=False),flush=True)
    # dedupe within shard, keeping richest/highest interaction occurrence
    best={}
    for x in rows:
        gid=str(x['group_id'])
        rank=(num(x.get('max_interaction')),sum(x.get(k) not in (None,'') for k in ['media_name','media_url','article_url','abstract','image_count']))
        if gid not in best or rank>best[gid][0]: best[gid]=(rank,x)
    uniq=[v[1] for v in best.values()]
    fields=['query','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','effective_publish_time','read_count','digg_count','comment_count','forward_count','repin_count','max_interaction','qualifying_metrics','image_count','content_schema_type','has_video','has_gallery']
    with (OUT/f'viral_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(uniq)
    (OUT/f'report_{shard}.json').write_text(json.dumps(reports,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'shard':shard,'total_shards':total,'all_keywords':len(all_keywords()),'queries':len(kws),'viral_raw':len(rows),'viral_unique':len(uniq)},ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
