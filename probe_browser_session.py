import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

OUT = Path('output_session')
OUT.mkdir(exist_ok=True)

AUTHORS = ['馋嘴屋', '陆弃', '美猴王海门光明南路']
POSTS = ['7673466869773287977', '7673356385198883347', '1873448253700099']

FAN_KEYS = [
    'fans_count', 'fansCount', 'follower_count', 'followerCount', 'followers_count',
    'follow_count', 'following_count', '粉丝', '获赞'
]

async def collect_network(page, bag):
    async def on_response(resp):
        if 'toutiao.com' not in resp.url:
            return
        if resp.request.resource_type not in ('xhr', 'fetch', 'document'):
            return
        ct = (resp.headers.get('content-type') or '').lower()
        rec = {
            'url': resp.url,
            'status': resp.status,
            'type': resp.request.resource_type,
            'content_type': ct,
        }
        if ('json' in ct or any(k in resp.url for k in ['api/', 'search', 'user', 'profile', 'article', 'group'])) and len(bag) < 80:
            try:
                txt = await resp.text()
            except Exception as e:
                txt = f'__ERROR__ {e!r}'
            rec['body_length'] = len(txt)
            rec['body_prefix'] = txt[:5000]
            rec['fan_key_hits'] = {k: txt.count(k) for k in FAN_KEYS if k in txt}
            rec['content_hits'] = {k: txt.count(k) for k in ['article-content','content','group_id','digg_count','comment_count','image_list'] if k in txt}
        bag.append(rec)
    page.on('response', on_response)
    return on_response


def find_fan_snippets(text):
    out = []
    for pat in [
        r'.{0,120}(?:fans_count|fansCount|follower_count|followerCount|followers_count).{0,160}',
        r'.{0,80}粉丝.{0,120}',
        r'.{0,80}获赞.{0,120}',
    ]:
        for m in re.finditer(pat, text, re.I | re.S):
            s = re.sub(r'\s+', ' ', m.group(0))
            if s not in out:
                out.append(s[:500])
            if len(out) >= 20:
                return out
    return out


async def inspect_page(page, label, requested, wait_ms=4000):
    rec = {'label': label, 'requested': requested}
    try:
        response = await page.goto(requested, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(wait_ms)
        rec['status'] = response.status if response else None
        rec['final_url'] = page.url
        rec['title'] = await page.title()
        body = await page.locator('body').inner_text()
        html = await page.content()
        rec['body_chars'] = len(body)
        rec['html_chars'] = len(html)
        rec['body_prefix'] = re.sub(r'\s+', ' ', body[:4000])
        rec['has_access_wall'] = any(x in body for x in ['验证码', '安全验证', '请登录后'])
        rec['fan_snippets_body'] = find_fan_snippets(body)
        rec['fan_snippets_html'] = find_fan_snippets(html)
        rec['term_counts_html'] = {k: html.count(k) for k in FAN_KEYS + ['article-content','group_id','digg_count','comment_count','image_list']}
        rec['links'] = await page.locator('a').evaluate_all("els => els.slice(0,300).map(a => ({t:(a.innerText||'').trim(), h:a.href})).filter(x=>x.h)")
        rec['images'] = await page.locator('img').evaluate_all("els => els.slice(0,80).map(i => ({src:i.src, alt:i.alt||''})).filter(x=>x.src)")
    except Exception as e:
        rec['error'] = repr(e)
    return rec


async def main():
    report = {'bootstrap': None, 'authors': [], 'posts': [], 'network': []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale='zh-CN',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        handler = await collect_network(page, report['network'])

        # Bootstrap a normal public search session first so the browser receives ordinary site cookies.
        report['bootstrap'] = await inspect_page(page, 'bootstrap_search', 'https://so.toutiao.com/search/?dvpf=pc&keyword=%E7%BE%8E%E9%A3%9F', 3000)
        report['cookies_after_bootstrap'] = [
            {'name': c['name'], 'domain': c['domain'], 'path': c['path']} for c in await context.cookies()
        ]

        for name in AUTHORS:
            # Try direct user-result mode first; if the site ignores pd=user, click the visible 用户 tab.
            search_url = f'https://so.toutiao.com/search/?dvpf=pc&keyword={quote(name)}&pd=user'
            item = await inspect_page(page, f'user_search:{name}', search_url, 3000)
            body_now = ''
            try:
                body_now = await page.locator('body').inner_text()
                tab = page.get_by_text('用户', exact=True)
                if await tab.count() and await tab.first.is_visible() and '粉丝' not in body_now:
                    old = page.url
                    await tab.first.click()
                    try:
                        await page.wait_for_url(lambda u: str(u) != old, timeout=15000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2500)
                    item['after_user_tab'] = await inspect_page(page, f'user_tab:{name}', page.url, 1500)
            except Exception as e:
                item['tab_error'] = repr(e)
            report['authors'].append(item)

        for gid in POSTS:
            # Use normal public group redirect inside the established browser context.
            report['posts'].append(await inspect_page(page, f'post:{gid}', f'https://www.toutiao.com/group/{gid}/', 5000))

        page.remove_listener('response', handler)
        await browser.close()

    (OUT / 'session_probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    summary = {
        'bootstrap_status': report.get('bootstrap', {}).get('status'),
        'cookie_count': len(report.get('cookies_after_bootstrap', [])),
        'authors': [],
        'posts': [],
        'interesting_network': [],
    }
    for a in report['authors']:
        target = a.get('after_user_tab') or a
        summary['authors'].append({
            'label': a.get('label'),
            'status': target.get('status'),
            'final_url': target.get('final_url'),
            'body_chars': target.get('body_chars'),
            'fan_snippets': (target.get('fan_snippets_body') or target.get('fan_snippets_html') or [])[:8],
            'term_counts_html': {k:v for k,v in (target.get('term_counts_html') or {}).items() if v},
        })
    for x in report['posts']:
        summary['posts'].append({
            'label': x.get('label'), 'status': x.get('status'), 'final_url': x.get('final_url'),
            'title': x.get('title'), 'body_chars': x.get('body_chars'), 'images': len(x.get('images') or []),
            'term_counts_html': {k:v for k,v in (x.get('term_counts_html') or {}).items() if v},
            'body_prefix': (x.get('body_prefix') or '')[:800],
        })
    for n in report['network']:
        if n.get('fan_key_hits') or n.get('content_hits') or any(k in n.get('url','') for k in ['user', 'profile', 'article', 'group']):
            summary['interesting_network'].append({
                'url': n.get('url'), 'status': n.get('status'), 'type': n.get('type'),
                'body_length': n.get('body_length'), 'fan_key_hits': n.get('fan_key_hits'),
                'content_hits': n.get('content_hits'), 'body_prefix': (n.get('body_prefix') or '')[:1200],
            })
            if len(summary['interesting_network']) >= 30:
                break
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
