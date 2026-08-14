import asyncio
import csv
import json
import re
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

OUT = Path('output_collect')
OUT.mkdir(exist_ok=True)
KEYWORDS = ['美食', '职场', '家庭']
MAX_PAGES = 3


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def normalize(d, keyword, page_no, page_url):
    if not isinstance(d, dict) or 'group_id' not in d:
        return None
    gid = d.get('group_id')
    title = d.get('title') or d.get('abstract') or ''
    if not gid or not title:
        return None
    return {
        'keyword': keyword,
        'page_no': page_no,
        'page_url': page_url,
        'group_id': str(gid),
        'title': re.sub(r'\s+', ' ', str(title)).strip()[:500],
        'article_url': d.get('article_url') or d.get('ttsearch_msite_url') or d.get('seo_url') or d.get('share_url') or d.get('source_url') or '',
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
        'abstract': re.sub(r'\s+', ' ', str(d.get('abstract') or '')).strip()[:1500],
    }


def extract_from_html(html, keyword, page_no, page_url):
    soup = BeautifulSoup(html, 'lxml')
    rows = []
    for script in soup.find_all('script'):
        body = (script.string or script.get_text() or '').strip()
        if not body:
            continue
        payloads = []
        if body.startswith('{') or body.startswith('['):
            payloads.append(body.rstrip(';'))
        # Handle JSON embedded in wrappers conservatively.
        if '\"extraData\"' in body and not payloads:
            m = re.search(r'(\{"extraData".*\})', body, flags=re.S)
            if m:
                payloads.append(m.group(1))
        for payload in payloads:
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            for d in walk(obj):
                r = normalize(d, keyword, page_no, page_url)
                if r:
                    rows.append(r)
    # De-dupe exact content objects on page.
    seen = set()
    out = []
    for r in rows:
        k = (r['group_id'], r['title'])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


async def main():
    collected = []
    page_reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale='zh-CN',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        for keyword in KEYWORDS:
            start = f'https://www.toutiao.com/search/?keyword={quote(keyword)}'
            await page.goto(start, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(2500)
            visited = set()
            for page_no in range(1, MAX_PAGES + 1):
                current_url = page.url
                if current_url in visited:
                    page_reports.append({'keyword': keyword, 'page_no': page_no, 'url': current_url, 'status': 'duplicate_url_stop'})
                    break
                visited.add(current_url)
                body = (await page.locator('body').inner_text())[:8000]
                if any(x in body for x in ['验证码', '安全验证', '请登录后']):
                    page_reports.append({'keyword': keyword, 'page_no': page_no, 'url': current_url, 'status': 'access_wall'})
                    break
                html = await page.content()
                rows = extract_from_html(html, keyword, page_no, current_url)
                collected.extend(rows)
                page_reports.append({
                    'keyword': keyword, 'page_no': page_no, 'url': current_url,
                    'status': 'ok', 'structured_rows': len(rows),
                    'body_has_next': '下一页' in body,
                    'body_prefix': re.sub(r'\s+', ' ', body[:600]),
                })
                if page_no >= MAX_PAGES:
                    break
                nxt = page.get_by_text('下一页', exact=True)
                try:
                    if await nxt.count() == 0 or not await nxt.first.is_visible():
                        page_reports[-1]['next_click'] = 'not_found'
                        break
                    old_url = page.url
                    await nxt.first.click()
                    try:
                        await page.wait_for_url(lambda u: str(u) != old_url, timeout=20000)
                    except Exception:
                        pass
                    await page.wait_for_load_state('domcontentloaded', timeout=30000)
                    await page.wait_for_timeout(1800)
                    page_reports[-1]['next_click'] = 'clicked'
                except Exception as e:
                    page_reports[-1]['next_click'] = f'error:{type(e).__name__}'
                    break

        await browser.close()

    # Global de-dupe by group_id; keep the richest row.
    best = {}
    def richness(r):
        return sum(v not in (None, '', 0, '0', []) for k,v in r.items() if k not in ('keyword','page_no','page_url'))
    for r in collected:
        gid = r['group_id']
        if gid not in best or richness(r) > richness(best[gid]):
            best[gid] = r
    rows = list(best.values())

    fields = ['keyword','page_no','page_url','group_id','title','article_url','media_name','media_url','user_id','publish_time','read_count','digg_count','comment_count','forward_count','repin_count','image_count','content_schema_type','abstract']
    with (OUT / 'sample.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    (OUT / 'sample.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'page_reports.json').write_text(json.dumps(page_reports, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'keywords': KEYWORDS,
        'max_pages': MAX_PAGES,
        'page_reports': page_reports,
        'raw_rows': len(collected),
        'unique_group_ids': len(rows),
        'with_read': sum(r.get('read_count') not in (None, '') for r in rows),
        'with_digg': sum(r.get('digg_count') not in (None, '') for r in rows),
        'with_comment': sum(r.get('comment_count') not in (None, '') for r in rows),
        'with_forward': sum(r.get('forward_count') not in (None, '') for r in rows),
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
