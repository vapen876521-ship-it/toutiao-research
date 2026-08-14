import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT = Path('output_pagination')
OUT.mkdir(exist_ok=True)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6',
    'Referer': 'https://so.toutiao.com/',
}
KEYWORDS = ['职场', '美食']
PAGES = [0, 1, 2, 3]


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def extract(text, keyword, endpoint, page_num):
    soup = BeautifulSoup(text, 'lxml')
    candidates = []
    rawdata_blocks = 0
    for script in soup.find_all('script'):
        body = (script.string or script.get_text() or '').strip()
        if not body:
            continue
        payloads = []
        if body.startswith('{') or body.startswith('['):
            payloads.append(body)
        # Search-page server payload sometimes appears as a JSON object embedded in a script tag.
        if '"extraData"' in body and not (body.startswith('{') or body.startswith('[')):
            m = re.search(r'(\{"extraData".*\})', body, flags=re.S)
            if m:
                payloads.append(m.group(1))
        for payload in payloads:
            try:
                obj = json.loads(payload.rstrip(';'))
            except Exception:
                continue
            if isinstance(obj, dict) and 'rawData' in obj:
                rawdata_blocks += 1
            for d in walk(obj):
                if not isinstance(d, dict) or 'group_id' not in d:
                    continue
                gid = d.get('group_id')
                title = d.get('title') or d.get('abstract') or ''
                if not gid or not title:
                    continue
                candidates.append({
                    'keyword': keyword,
                    'endpoint': endpoint,
                    'page_num': page_num,
                    'group_id': str(gid),
                    'title': str(title)[:300],
                    'article_url': d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or '',
                    'media_name': d.get('media_name') or d.get('source') or '',
                    'media_url': d.get('media_url') or d.get('user_source_url') or '',
                    'user_id': str(d.get('user_id') or d.get('media_creator_id') or ''),
                    'publish_time': d.get('publish_time') or d.get('create_time') or d.get('behot_time') or '',
                    'read_count': d.get('read_count'),
                    'digg_count': d.get('digg_count'),
                    'comment_count': d.get('comment_count'),
                    'forward_count': d.get('forward_count'),
                    'repin_count': d.get('repin_count'),
                    'image_count': d.get('image_count'),
                    'content_schema_type': d.get('content_schema_type'),
                })
    # Stable fallback directly from returned public HTML.
    gids = set(re.findall(r'"group_id"\s*:\s*"?(\d{10,25})', text))
    gids |= set(re.findall(r'"item_id"\s*:\s*"?(\d{10,25})', text))
    return candidates, sorted(gids), rawdata_blocks


session = requests.Session()
session.headers.update(HEADERS)
results = []
all_candidates = []

for keyword in KEYWORDS:
    for page_num in PAGES:
        tests = [
            ('so', 'https://so.toutiao.com/search', {
                'dvpf': 'pc', 'source': 'pagination', 'keyword': keyword,
                'page_num': str(page_num), 'pd': 'information',
                'action_type': 'pagination', 'from': 'news', 'cur_tab_title': 'news',
            }),
            ('www', 'https://www.toutiao.com/search/', {
                'keyword': keyword, 'page_num': str(page_num), 'pd': 'information',
                'source': 'pagination', 'from': 'news',
            }),
        ]
        for endpoint, url, params in tests:
            started = time.time()
            try:
                r = session.get(url, params=params, timeout=30, allow_redirects=True)
                text = r.text
                candidates, gids, rawdata_blocks = extract(text, keyword, endpoint, page_num)
                seen = set()
                uniq = []
                for c in candidates:
                    key = (c['group_id'], c['title'])
                    if key in seen:
                        continue
                    seen.add(key)
                    uniq.append(c)
                all_candidates.extend(uniq)
                logid = ''
                m = re.search(r"logId:\s*['\"]([^'\"]+)", text)
                if m:
                    logid = m.group(1)
                results.append({
                    'keyword': keyword,
                    'endpoint': endpoint,
                    'page_num': page_num,
                    'status': r.status_code,
                    'bytes': len(r.content),
                    'elapsed_s': round(time.time() - started, 2),
                    'final_url': r.url,
                    'title': BeautifulSoup(text, 'lxml').title.get_text(strip=True) if BeautifulSoup(text, 'lxml').title else '',
                    'candidate_count': len(uniq),
                    'regex_gid_count': len(gids),
                    'candidate_gids': [x['group_id'] for x in uniq[:30]],
                    'regex_gids': gids[:30],
                    'rawdata_blocks': rawdata_blocks,
                    'log_id_present': bool(logid),
                    'contains_captcha': any(x in text.lower() for x in ['captcha', '验证码', 'verify']),
                    'contains_login': '登录' in text,
                })
            except Exception as e:
                results.append({
                    'keyword': keyword, 'endpoint': endpoint, 'page_num': page_num,
                    'status': 'ERROR', 'bytes': 0, 'elapsed_s': round(time.time() - started, 2),
                    'error': repr(e),
                })
            time.sleep(1.5)

# Deduplicate global content items while preserving evidence of the page that exposed them.
seen = set()
uniq_all = []
for c in all_candidates:
    key = c['group_id']
    if key in seen:
        continue
    seen.add(key)
    uniq_all.append(c)

(OUT / 'pagination_report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'pagination_candidates.json').write_text(json.dumps(uniq_all, ensure_ascii=False, indent=2), encoding='utf-8')
summary = {
    'requests': len(results),
    'http_200': sum(x.get('status') == 200 for x in results),
    'unique_candidate_items': len(uniq_all),
    'rows': [
        {
            'keyword': x.get('keyword'), 'endpoint': x.get('endpoint'), 'page': x.get('page_num'),
            'status': x.get('status'), 'bytes': x.get('bytes'), 'candidates': x.get('candidate_count'),
            'regex_gids': x.get('regex_gid_count'), 'rawdata_blocks': x.get('rawdata_blocks'),
            'log_id_present': x.get('log_id_present')
        } for x in results
    ]
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
