import csv
import json
import math
import re
from collections import Counter,defaultdict
from pathlib import Path

IN=Path('harvest_merged/candidates.csv')
OUT=Path('harvest_analysis'); OUT.mkdir(exist_ok=True)

ORG_MARKERS=['日报','晚报','时报','电视台','广播','融媒体','新闻网','新闻社','新闻客户端','官方','发布','观察网','环球网','光明网','新华','央视','人民网','澎湃','界面新闻','中新','中国网','证券报','财经网','都市报']
TOPIC_RULES={
 '美食':['美食','菜','餐','烘焙','早餐','晚餐','火锅','外卖','咖啡','茶','小吃','水果','厨房'],
 '职场创业':['职场','打工','工资','加薪','跳槽','面试','辞职','失业','同事','领导','副业','创业','摆摊','开店','销售'],
 '家庭情感':['家庭','夫妻','婚姻','婆媳','亲子','育儿','宝妈','相亲','恋爱','分手','情感','朋友','独居'],
 '教育成长':['教育','学习','作业','中考','高考','大学','考研','毕业','教师','家长','读书','写作'],
 '消费居家':['省钱','消费','网购','退货','快递','二手','维权','超市','租房','买房','装修','收纳','家务','物业','邻居','家电','维修'],
 '科技数码':['手机','电脑','平板','耳机','AI','人工智能','大模型','机器人','无人机','摄影','软件','APP','智能'],
 '汽车出行':['汽车','新能源车','电动车','充电','停车','驾照','司机','自驾','保养','二手车','打车','公交','地铁','骑行'],
 '旅行本地':['旅行','旅游','酒店','民宿','景区','博物馆','公园','夜市','城市漫步','本地生活','小城','县城','街头'],
 '宠物兴趣':['宠物','猫','狗','养花','绿植','种菜','钓鱼','手工','收藏','非遗'],
 '健康运动':['跑步','健身','散步','减肥','体重','瑜伽','羽毛球','乒乓球','睡眠','健康'],
 '三农乡村':['农村','返乡','农民','种地','果农','菜农','养殖','赶集','乡村','农产品','丰收'],
 '普通人故事':['普通人','真实经历','故事','奇闻','暖心','经历','网友热议','生活观察']
}

def num(v):
 try:return int(float(v)) if v not in ('',None,'None') else 0
 except:return 0

def topic(text):
 scores={k:sum(text.count(w) for w in ws) for k,ws in TOPIC_RULES.items()}
 k=max(scores,key=scores.get)
 return k if scores[k]>0 else '其他生活'

def pct_ranks(vals):
 order=sorted(range(len(vals)), key=lambda i: vals[i])
 out=[0.0]*len(vals)
 n=max(1,len(vals)-1)
 for rank,i in enumerate(order):out[i]=rank/n
 return out

with IN.open('r',encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
for r in rows:
 text=(r.get('title','')+' '+r.get('abstract','')).strip()
 r['topic']=topic(text)
 r['likely_individual']='1' if not any(m in (r.get('media_name') or '') for m in ORG_MARKERS) else '0'
 r['title_chars']=str(len(r.get('title','')))
 r['abstract_chars']=str(len(r.get('abstract','')))
 r['title_has_number']='1' if re.search(r'\d',r.get('title','')) else '0'
 r['title_question']='1' if re.search(r'[？?]',r.get('title','')) else '0'
 r['title_exclaim']='1' if re.search(r'[！!]',r.get('title','')) else '0'
 r['title_colon']='1' if re.search(r'[：:]',r.get('title','')) else '0'
 r['title_quote']='1' if re.search(r'[“”《》「」]',r.get('title','')) else '0'
 r['first_person']='1' if any(x in text for x in ['我','我们','本人','自己']) else '0'
 r['second_person']='1' if any(x in text for x in ['你','你们','大家']) else '0'
 r['emotion_markers']=str(sum(text.count(x) for x in ['没想到','后悔','崩溃','开心','感动','心酸','离谱','惊讶','太难','值得','千万别','一定要','终于','竟然']))
 r['engagement_total']=str(num(r.get('digg_count'))+num(r.get('comment_count'))+num(r.get('forward_count')))

# Percentile composite prevents huge read counts from dominating.
for field,weight in [('read_count',0.15),('digg_count',0.35),('comment_count',0.30),('forward_count',0.20)]:
 vals=[num(r.get(field)) for r in rows]; ranks=pct_ranks(vals)
 for r,p in zip(rows,ranks): r['_score_'+field]=p*weight
for r in rows:
 r['interaction_score']=f"{sum(float(r[k]) for k in r if k.startswith('_score_')):.6f}"
 for k in list(r):
  if k.startswith('_score_'):del r[k]

rows.sort(key=lambda r:float(r['interaction_score']), reverse=True)
fields=list(rows[0].keys()) if rows else []
with (OUT/'ranked_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
individual=[r for r in rows if r['likely_individual']=='1']
with (OUT/'likely_individual_top.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(individual[:3000])

bytopic=defaultdict(list)
for r in individual: bytopic[r['topic']].append(r)
summary={
 'total_candidates':len(rows),'likely_individual':len(individual),
 'nonzero_digg':sum(num(r.get('digg_count'))>0 for r in rows),
 'nonzero_comment':sum(num(r.get('comment_count'))>0 for r in rows),
 'nonzero_forward':sum(num(r.get('forward_count'))>0 for r in rows),
 'topics':{k:len(v) for k,v in sorted(bytopic.items(),key=lambda kv:len(kv[1]),reverse=True)},
 'title_features':{
  'number_rate':sum(r['title_has_number']=='1' for r in individual)/max(1,len(individual)),
  'question_rate':sum(r['title_question']=='1' for r in individual)/max(1,len(individual)),
  'exclaim_rate':sum(r['title_exclaim']=='1' for r in individual)/max(1,len(individual)),
  'colon_rate':sum(r['title_colon']=='1' for r in individual)/max(1,len(individual)),
 },
 'top20':[ {k:r.get(k) for k in ['title','media_name','topic','read_count','digg_count','comment_count','forward_count','image_count','interaction_score','article_url']} for r in individual[:20] ]
}
(OUT/'analysis_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
