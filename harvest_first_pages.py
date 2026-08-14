import csv
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT = Path('harvest_output')
OUT.mkdir(exist_ok=True)

BASE_TOPICS = [
    '家常菜','早餐','晚餐','减脂餐','烘焙','面食','小吃','火锅','餐厅','外卖','买菜','厨艺','空气炸锅','电饭煲','冰箱收纳','食品安全','水果','咖啡','茶','饮食习惯',
    '职场','打工人','工资','加薪','跳槽','面试','辞职','失业','同事关系','领导','办公室','副业','自由职业','创业','小生意','摆摊','个体户','开店','客服','销售',
    '家庭','夫妻','婚姻','婆媳','亲子','育儿','宝妈','爸爸带娃','二胎','独生子女','家庭教育','学习方法','作业','中考','高考','大学生活','考研','毕业生','教师','家长',
    '租房','买房','装修','收纳','家务','断舍离','物业','邻居','小区生活','搬家','维修','水电','家电','空调','洗衣机','厨房','卫生间','睡眠','通勤','城市生活',
    '省钱','消费','网购','退货','快递','二手','闲置','维权','超市','菜市场','会员','优惠券','保险常识','养老金','退休生活','养老','存钱','记账','性价比','购物避坑',
    '手机','电脑','平板','耳机','智能家居','数码','AI','人工智能','大模型','机器人','无人机','摄影','拍照','短视频','软件','APP','网络安全','隐私保护','智能手表','办公效率',
    '汽车','新能源车','电动车','充电桩','停车','驾照','新手司机','高速出行','自驾游','汽车保养','二手车','打车','公交','地铁','骑行','露营','旅行','酒店','民宿','景区',
    '宠物','猫','狗','养猫','养狗','宠物医院','流浪猫','养花','绿植','种菜','阳台种菜','钓鱼','跑步','健身','散步','减肥','体重管理','瑜伽','羽毛球','乒乓球',
    '农村生活','返乡','农民','种地','果农','菜农','养殖','赶集','村里生活','乡村美食','农产品','丰收','夜市','县城生活','小城生活','本地生活','街头见闻','社区生活','普通人故事','真实经历',
    '情感','相亲','恋爱','分手','朋友关系','人情世故','中年生活','老年生活','独居','女性成长','男性成长','焦虑','情绪管理','读书','写作','兴趣爱好','手工','传统文化','非遗','收藏',
    '旅游攻略','亲子游','周末去哪玩','城市漫步','博物馆','公园','夜市美食','地方小吃','旅行避坑','酒店体验','民宿体验','服务体验','消费体验','维修经历','快递经历','网购经历','求职经历','租房经历','装修经历',
    '生活妙招','生活常识','实用技巧','避坑指南','真实测评','使用体验','省钱技巧','普通人生活','生活变化','生活观察','网友热议','奇闻经历','暖心故事','邻里故事','家庭故事','职场故事','创业故事','消费故事','旅行故事','宠物故事'
]
MODIFIERS = ['', ' 真实经历', ' 经验分享', ' 避坑', ' 网友热议']

POLITICAL_MILITARY = [
    '习近平','总书记','党中央','国务院','外交部','国防部','解放军','军队','军演','导弹','战机','航母','战争','俄乌','乌克兰','以色列','加沙','特朗普','普京','泽连斯基','选举','总统','总理','政治','两会','人大','政协','省委','市委书记','军方','军事','武器','台海','台湾当局','南海争端'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6',
}


def all_keywords():
    out=[]; seen=set()
    for t in BASE_TOPICS:
        for m in MODIFIERS:
            q=(t+m).strip()
            if q not in seen:
                seen.add(q); out.append(q)
    return out


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def as_int(v):
    try:
        if v in (None,''): return None
        return int(float(v))
    except Exception:
        return None


def normalize(d, query):
    if not isinstance(d, dict) or 'group_id' not in d:
        return None
    gid=d.get('group_id'); title=d.get('title') or d.get('abstract') or ''
    if not gid or not title: return None
    title=re.sub(r'\s+',' ',str(title)).strip()
    abstract=re.sub(r'\s+',' ',str(d.get('abstract') or d.get('description') or '')).strip()
    text=title+' '+abstract
    if any(k in text for k in POLITICAL_MILITARY):
        return None
    publish=as_int(d.get('publish_time') or d.get('create_time') or d.get('behot_time'))
    now=int(datetime.now(timezone.utc).timestamp())
    cutoff=int((datetime.now(timezone.utc)-timedelta(days=31)).timestamp())
    if publish and (publish < cutoff or publish > now + 86400):
        return None
    row={
        'query':query,'group_id':str(gid),'title':title[:500],
        'abstract':abstract[:2000],
        'article_url':d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or d.get('source_url') or '',
        'media_name':d.get('media_name') or d.get('source') or '',
        'media_url':d.get('media_url') or d.get('user_source_url') or '',
        'user_id':str(d.get('user_id') or d.get('media_creator_id') or ''),
        'publish_time':publish or '',
        'read_count':as_int(d.get('read_count')),
        'digg_count':as_int(d.get('digg_count')),
        'comment_count':as_int(d.get('comment_count')),
        'forward_count':as_int(d.get('forward_count')),
        'repin_count':as_int(d.get('repin_count')),
        'image_count':as_int(d.get('image_count')),
        'content_schema_type':d.get('content_schema_type') or '',
        'has_video':d.get('has_video'),
        'has_gallery':d.get('has_gallery'),
    }
    if all(row[k] is None for k in ('read_count','digg_count','comment_count','forward_count')):
        return None
    return row


def parse_html(text, query):
    soup=BeautifulSoup(text,'lxml'); rows=[]
    for script in soup.find_all('script'):
        body=(script.string or script.get_text() or '').strip()
        if not body: continue
        payloads=[]
        if body.startswith('{') or body.startswith('['): payloads.append(body.rstrip(';'))
        if '"extraData"' in body and not payloads:
            m=re.search(r'(\{"extraData".*\})', body, flags=re.S)
            if m: payloads.append(m.group(1))
        for payload in payloads:
            try: obj=json.loads(payload)
            except Exception: continue
            for d in walk(obj):
                r=normalize(d,query)
                if r: rows.append(r)
    best={}
    for r in rows:
        gid=r['group_id']
        score=sum(r.get(k) not in (None,'',0) for k in ['article_url','media_name','media_url','publish_time','read_count','digg_count','comment_count','forward_count','image_count'])
        if gid not in best or score>best[gid][0]: best[gid]=(score,r)
    return [v[1] for v in best.values()]


def main():
    shard=int(os.environ.get('SHARD_INDEX','0')); total=int(os.environ.get('TOTAL_SHARDS','1'))
    kws=[q for i,q in enumerate(all_keywords()) if i % total == shard]
    sess=requests.Session(); sess.headers.update(HEADERS)
    rows=[]; reports=[]
    for i,q in enumerate(kws,1):
        ok=False
        for attempt in range(2):
            try:
                url='https://www.toutiao.com/search/?keyword='+quote(q)
                r=sess.get(url,timeout=25,allow_redirects=True)
                parsed=parse_html(r.text,q) if r.status_code==200 else []
                reports.append({'query':q,'attempt':attempt+1,'status':r.status_code,'bytes':len(r.content),'parsed':len(parsed),'final_url':r.url})
                if parsed:
                    rows.extend(parsed); ok=True; break
            except Exception as e:
                reports.append({'query':q,'attempt':attempt+1,'status':'ERROR','error':repr(e),'parsed':0})
            time.sleep(1.2)
        time.sleep(0.6)
        if i % 20 == 0:
            print(f'shard={shard} progress={i}/{len(kws)} rows={len(rows)}')
    best={}
    for r in rows:
        gid=r['group_id']
        engagement=sum((r.get(k) or 0) for k in ['read_count','digg_count','comment_count','forward_count'])
        if gid not in best or engagement>best[gid][0]: best[gid]=(engagement,r)
    uniq=[v[1] for v in best.values()]
    fields=['query','group_id','title','abstract','article_url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','image_count','content_schema_type','has_video','has_gallery']
    with (OUT/f'shard_{shard}.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(uniq)
    (OUT/f'shard_{shard}_report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'shard':shard,'total_shards':total,'queries':len(kws),'successful_queries':sum(x.get('parsed',0)>0 for x in reports),'raw_rows':len(rows),'unique_rows':len(uniq)},ensure_ascii=False))

if __name__=='__main__': main()
