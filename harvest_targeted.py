import csv
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

from harvest_first_pages import HEADERS, parse_html

OUT = Path('harvest_output')
OUT.mkdir(exist_ok=True)

# Topics selected from the first 1,583-post union plus adjacent everyday-life themes.
# Politics/military are still filtered inside harvest_first_pages.parse_html().
CORES = [
    '餐厅','早餐','晚餐','面食','家常菜','外卖','买菜','菜市场','食品安全','小吃','火锅','咖啡','水果','厨艺','减脂餐',
    '省钱','性价比','消费','网购','退货','快递','二手','闲置','超市','优惠券','购物避坑','服务体验','消费体验','维修经历',
    '办公室','职场','打工人','工资','加薪','跳槽','面试','辞职','失业','同事关系','领导','毕业生','求职','销售','摆摊','小生意','个体户','开店','副业',
    '夫妻','婚姻','婆媳','亲子','育儿','爸爸带娃','二胎','独生子女','家庭教育','家长','中考','高考','大学生活','教师','学习方法',
    '买房','租房','装修','物业','邻居','小区生活','搬家','家务','收纳','断舍离','厨房','卫生间','维修','水电','空调','睡眠','通勤',
    '农村生活','返乡','农民','赶集','村里生活','乡村美食','农产品','县城生活','小城生活','本地生活','街头见闻','社区生活','邻里故事','普通人故事',
    '中年生活','老年生活','退休生活','养老','独居','相亲','恋爱','分手','朋友关系','人情世故','女性成长','男性成长','情绪管理','家庭故事',
    '旅行','自驾游','酒店','民宿','景区','旅游攻略','亲子游','周末去哪玩','城市漫步','夜市','地方小吃','旅行避坑','酒店体验','民宿体验',
    '手机','电脑','AI','人工智能','大模型','机器人','数码','软件','APP','智能家居','摄影','办公效率','网络安全','隐私保护',
    '汽车','新能源车','电动车','停车','新手司机','汽车保养','二手车','打车','公交','地铁','骑行',
    '猫','狗','养猫','养狗','宠物医院','养花','绿植','阳台种菜','钓鱼','跑步','健身','散步','羽毛球',
    '实用技巧','生活妙招','生活常识','真实测评','使用体验','普通人生活','生活变化','生活观察','真实经历','暖心故事'
]

# Experience / debate modifiers performed materially better on comments in the first two rounds.
SUFFIXES = [
    '真实经历','亲身经历','网友热议','经验分享','踩坑经历','避坑','后悔了','没想到','第一次','真实感受'
]
PREFIXES = ['普通人','中年人','退休后','上班族']


def all_keywords():
    out=[]; seen=set()
    # Keep the bare term for baseline, then high-yield experience/debate variants.
    for core in CORES:
        candidates=[core]
        candidates += [f'{core} {s}' for s in SUFFIXES]
        # Prefixes only on life/work/consumer topics; broad enough for discovery but still non-political.
        candidates += [f'{p} {core}' for p in PREFIXES]
        for q in candidates:
            q=' '.join(q.split())
            if q not in seen:
                seen.add(q); out.append(q)
    return out


def engagement(r):
    def n(v):
        try: return int(float(v or 0))
        except Exception: return 0
    return n(r.get('read_count')) + 10*n(r.get('digg_count')) + 20*n(r.get('comment_count')) + 20*n(r.get('forward_count'))


def main():
    shard=int(os.environ.get('SHARD_INDEX','0'))
    total=int(os.environ.get('TOTAL_SHARDS','1'))
    kws=[q for i,q in enumerate(all_keywords()) if i % total == shard]
    sess=requests.Session(); sess.headers.update(HEADERS)
    rows=[]; reports=[]
    for i,q in enumerate(kws,1):
        for attempt in range(2):
            try:
                url='https://www.toutiao.com/search/?keyword='+quote(q)
                r=sess.get(url,timeout=25,allow_redirects=True)
                parsed=parse_html(r.text,q) if r.status_code==200 else []
                reports.append({'query':q,'attempt':attempt+1,'status':r.status_code,'bytes':len(r.content),'parsed':len(parsed),'final_url':r.url})
                if parsed:
                    rows.extend(parsed)
                    break
            except Exception as e:
                reports.append({'query':q,'attempt':attempt+1,'status':'ERROR','error':repr(e),'parsed':0})
            time.sleep(0.8)
        time.sleep(0.25)
        if i % 25 == 0:
            print(f'shard={shard} progress={i}/{len(kws)} rows={len(rows)}')

    best={}
    for r in rows:
        gid=r['group_id']
        sc=engagement(r)
        richness=sum(r.get(k) not in (None,'') for k in ['article_url','media_name','media_url','publish_time','abstract','image_count'])
        if gid not in best or (sc,richness)>best[gid][0]:
            best[gid]=((sc,richness),r)
    uniq=[v[1] for v in best.values()]
    fields=['query','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','image_count','content_schema_type','has_video','has_gallery']
    with (OUT/f'shard_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(uniq)
    (OUT/f'shard_{shard}_report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'shard':shard,'total_shards':total,'all_keywords':len(all_keywords()),'queries':len(kws),
        'successful_queries':len({x['query'] for x in reports if x.get('parsed',0)>0}),
        'raw_rows':len(rows),'unique_rows':len(uniq)
    },ensure_ascii=False))

if __name__=='__main__':
    main()
