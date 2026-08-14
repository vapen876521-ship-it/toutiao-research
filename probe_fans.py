import json
import re
import time
from pathlib import Path

import requests

OUT = Path('output_fans')
OUT.mkdir(exist_ok=True)

AUTHORS = [
    ('光明网', 'http://toutiao.com/m5806115967/'),
    ('馋嘴屋', 'http://toutiao.com/m1824382144865289/'),
    ('美猴王海门光明南路', 'http://toutiao.com/m1738225326104576/'),
    ('陆弃', 'http://toutiao.com/m50650238814/'),
    ('权谋家', 'http://toutiao.com/m3517249816/'),
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.toutiao.com/',
}


def token_from_url(url):
    m = re.search(r'/m([^/]+)/?', url)
    return m.group(1) if m else url.rstrip('/').split('/')[-1]

session = requests.Session()
session.headers.update(HEADERS)
rows = []

for name, media_url in AUTHORS:
    token = token_from_url(media_url)
    for method in ('post_form', 'post_query', 'get_query'):
        started = time.time()
        try:
            url = 'https://www.toutiao.com/api/pc/user/fans_stat'
            if method == 'post_form':
                r = session.post(url, data={'token': token}, timeout=20)
            elif method == 'post_query':
                r = session.post(url, params={'token': token}, timeout=20)
            else:
                r = session.get(url, params={'token': token}, timeout=20)
            text = r.text
            try:
                js = r.json()
            except Exception:
                js = None
            rows.append({
                'name': name,
                'media_url': media_url,
                'token': token,
                'method': method,
                'status': r.status_code,
                'content_type': r.headers.get('content-type',''),
                'elapsed_s': round(time.time()-started,2),
                'json': js,
                'body_prefix': text[:1000],
            })
            if isinstance(js, dict) and js.get('data'):
                break
        except Exception as e:
            rows.append({'name':name,'media_url':media_url,'token':token,'method':method,'status':'ERROR','error':repr(e)})
        time.sleep(1.0)

(OUT/'fans_probe.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(rows, ensure_ascii=False, indent=2))
