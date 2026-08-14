import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

OUT = Path('output_pagination_network')
OUT.mkdir(exist_ok=True)
KEYWORDS = ['餐厅', '职场']

CONTENT_HINTS = ('group_id', 'comment_count', 'digg_count', 'forward_count', 'publish_time')

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
            item = {'keyword': keyword, 'events': []}
            async def on_response(resp):
                if 'toutiao.com' not in resp.url:
                    return
                if resp.request.resource_type not in ('xhr','fetch','document'):
                    return
                rec = {
                    'url': resp.url,
                    'status': resp.status,
                    'type': resp.request.resource_type,
                    'content_type': resp.headers.get('content-type',''),
                }
                try:
                    txt = await resp.text()
                except Exception as e:
                    txt = ''
                    rec['read_error'] = repr(e)
                rec['body_length'] = len(txt)
                rec['hint_counts'] = {k: txt.count(k) for k in CONTENT_HINTS if k in txt}
                # Keep enough of content-like responses to identify the public pagination payload.
                if rec['hint_counts'] or any(x in resp.url.lower() for x in ['search','pagination','api/']):
                    rec['body_prefix'] = txt[:12000]
                    rec['body_suffix'] = txt[-3000:] if len(txt) > 3000 else ''
                item['events'].append(rec)
            page.on('response', on_response)

            start = f'https://so.toutiao.com/search/?dvpf=pc&keyword={quote(keyword)}'
            try:
                await page.goto(start, wait_until='domcontentloaded', timeout=60000)
                await page.wait_for_timeout(3000)
                item['page1_url'] = page.url
                item['page1_body_chars'] = len(await page.locator('body').inner_text())
                item['page1_next'] = await page.get_by_text('下一页', exact=True).count()
                # Clear startup traffic so we can isolate traffic caused by the next-page click.
                item['startup_events'] = item['events'][-20:]
                item['events'] = []
                nxt = page.get_by_text('下一页', exact=True)
                if await nxt.count() and await nxt.first.is_visible():
                    old = page.url
                    await nxt.first.click()
                    try:
                        await page.wait_for_url(lambda u: str(u) != old, timeout=15000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(7000)
                    item['page2_url'] = page.url
                    body = await page.locator('body').inner_text()
                    item['page2_body_chars'] = len(body)
                    item['page2_body_prefix'] = re.sub(r'\s+',' ',body[:2000])
                else:
                    item['click'] = 'next_not_found'
            except Exception as e:
                item['error'] = repr(e)
            finally:
                page.remove_listener('response', on_response)
            report.append(item)
        await browser.close()

    (OUT/'pagination_network.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[]
    for x in report:
        interesting=[]
        for e in x.get('events',[]):
            if e.get('hint_counts') or any(k in e.get('url','').lower() for k in ['search','pagination','api/']):
                interesting.append({
                    'url':e.get('url'),'status':e.get('status'),'type':e.get('type'),'body_length':e.get('body_length'),
                    'hint_counts':e.get('hint_counts'), 'body_prefix':(e.get('body_prefix') or '')[:1500]
                })
        summary.append({
            'keyword':x.get('keyword'),'error':x.get('error',''),'page1_url':x.get('page1_url'),
            'page2_url':x.get('page2_url'),'page2_body_chars':x.get('page2_body_chars'),
            'events_after_click':len(x.get('events',[])),'interesting':interesting[:20]
        })
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    asyncio.run(main())
