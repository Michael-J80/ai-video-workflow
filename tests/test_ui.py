import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from test_browser import _HAS_BROWSER
import pytest


def test_monitoring_can_pause_and_quote_evidence_is_linked():
    if not _HAS_BROWSER:
        pytest.skip('Chromium required')
    async def main():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            task = dict(id='a'*32, state='MONITORING', requirements='fixture', duration_seconds=15, ratio='9:16',
                        materials=[], generation={}, design=None, quote={'credits': 3, 'balance': 100, 'evidence': 'evidence/q.png', 'fingerprint': 'fixture'}, artifacts=[])
            root = Path(__file__).resolve().parents[1]/'app/static'
            async def route(r):
                path = urlparse(r.request.url).path
                if path == '/':
                    await r.fulfill(path=root/'index.html', content_type='text/html')
                elif path.startswith('/static/'):
                    await r.fulfill(path=root/path.removeprefix('/static/'), content_type='text/javascript' if path.endswith('.js') else 'text/css')
                elif path.endswith('/events'):
                    await r.fulfill(body='', content_type='text/event-stream')
                else:
                    value = {'csrf_token':'fixture'} if path.endswith('/session') else [task] if path == '/api/tasks' else task if path.startswith('/api/tasks/') else {}
                    await r.fulfill(body=json.dumps(value), content_type='application/json')
            await page.route('**/*', route)
            await page.goto('http://127.0.0.1:8765')
            await page.locator('#task-list li').first.click()
            await page.locator('#detail-panel').wait_for(state='visible')
            assert await page.locator('#btn-pause').is_enabled()
            assert await page.locator('#quote-meta a').get_attribute('href') == '/api/tasks/'+task['id']+'/files/evidence/q.png'
            await browser.close()
    asyncio.run(main())
