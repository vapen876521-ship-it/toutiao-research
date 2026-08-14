import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

OUT = Path('output_browser')
OUT.mkdir(exist_ok=True)
KEYWORDS = ['职场', '美食']

async def main():
    report = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale='zh-CN',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        for keyword in KEYWORDS:
            net = []
            response_bodies = []

            async def on_response(resp):
                url = resp.url
                rt = resp.request.resource_type
                if rt not in ('xhr', 'fetch', 'document'):
                    return
                if 'toutiao.com' not in url:
                    return
                ct = (resp.headers.get('content-type') or '').lower()
                rec = {
                    'url': url,
                    'status': resp.status,
                    'resource_type': rt,
                    'content_type': ct,
                }
                net.append(rec)
                if ('json' in ct or 'search' in url) and len(response_bodies) < 20:
                    try:
                        txt = await resp.text()
                    except Exception as e:
                        txt = f'__ERROR__ {e!r}'
                    response_bodies.append({
                        **rec,
                        'body_prefix': txt[:4000],
                        'body_length': len(txt),
                    })

            page.on('response', on_response)
            url = f'https://www.toutiao.com/search/?keyword={quote(keyword)}'
            nav_error = ''
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                await page.wait_for_timeout(5000)
                initial_title = await page.title()
                initial_url = page.url
                body_text = (await page.locator('body').inner_text())[:12000]
                # Scroll like a normal reader; stop if a login/captcha wall appears.
                for _ in range(6):
                    current = (await page.locator('body').inner_text())[:5000]
                    if any(x in current for x in ['验证码', '请登录后', '安全验证']):
                        break
                    await page.mouse.wheel(0, 1800)
                    await page.wait_for_timeout(2500)
                links = await page.locator('a').evaluate_all("els => els.map(a => ({t:(a.innerText||'').trim(), h:a.href})).filter(x => x.h)")
                content_links = [x for x in links if re.search(r'toutiao\.com/(article|group)/\d+', x.get('h',''))]
                texts = [x for x in links if x.get('t')]
                report.append({
                    'keyword': keyword,
                    'initial_url': initial_url,
                    'title': initial_title,
                    'body_prefix': body_text[:3000],
                    'network_requests': net,
                    'response_bodies': response_bodies,
                    'content_links': content_links[:100],
                    'link_text_samples': texts[:100],
                })
            except Exception as e:
                nav_error = repr(e)
                report.append({'keyword': keyword, 'error': nav_error, 'network_requests': net, 'response_bodies': response_bodies})
            finally:
                page.remove_listener('response', on_response)

        await browser.close()

    (OUT / 'browser_probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = []
    for x in report:
        urls = [r['url'] for r in x.get('network_requests', [])]
        interesting = []
        for u in urls:
            if any(k in u for k in ['search', 'api/', 'feed', 'list']):
                if u not in interesting:
                    interesting.append(u)
        summary.append({
            'keyword': x.get('keyword'),
            'error': x.get('error',''),
            'network_count': len(x.get('network_requests', [])),
            'response_bodies': len(x.get('response_bodies', [])),
            'content_links': len(x.get('content_links', [])),
            'interesting_urls': interesting[:30],
        })
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
