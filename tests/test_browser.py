from __future__ import annotations

import pytest
import asyncio
import base64
import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.browser import Browser, BrowserError

TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='
)


def browser_available() -> bool:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return False
    import asyncio

    async def _check():
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                return True
            except Exception:
                return False

    try:
        return asyncio.run(_check())
    except Exception:
        return False


_HAS_BROWSER = browser_available()

HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>mock</title></head>
<body>
<div id="app">
  <div id="controls">
    <select id="model-select"><option>v1</option><option>v2</option></select>
    <select id="mode-select"><option>standard</option><option>pro</option></select>
    <select id="resolution-select"><option>720p</option><option>1080p</option></select>
    <select id="ratio-select"><option>16:9</option><option>9:16</option></select>
    <select id="duration-select"><option>5s</option><option>15s</option></select>
    <select id="count-select"><option>1</option><option>3</option></select>
  </div>
  <div id="upload-wrap"><input id="upload" type="file" multiple style="display:none"></div>
  <div id="refs"></div>
  <div id="refcount">0</div>
  <div id="prompt" contenteditable="true" style="min-height:40px;border:1px solid #ccc"></div>
  <div id="credits">3 credits</div>
  <div id="balance">100.00</div>
  <div id="collapse" style="display:none">collapse</div>
  <div id="cards"></div>
</div>
<script>
let balance = 100.00;
function renderRefs(){
  const refs = document.getElementById('refs');
  refs.innerHTML = '';
  window.__refs.forEach((n, i) => {
    const d = document.createElement('div');
    d.setAttribute('data-filename', n);
    d.textContent = n;
    refs.appendChild(d);
  });
  document.getElementById('refcount').textContent = String(window.__refs.length + ' 张');
}
window.__refs = [];
window.__cards = [];
window.__balance = balance;
window.__credits = 3;
document.getElementById('upload').addEventListener('change', (e) => {
  const files = e.target.files;
  for (const f of files) {
    window.__refs.push(f.name);
  }
  renderRefs();
  e.target.value = '';
});
document.getElementById('prompt').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const text = document.getElementById('prompt').innerText.trim();
    window.__cards.push({id: 'task-' + Date.now(), prompt: text, status: '待处理'});
    window.__balance = window.__balance - 3.00;
    window.__credits = 3.00;
    renderCards();
  }
});
function renderCards(){
  const cards = document.getElementById('cards');
  cards.innerHTML = '';
  window.__cards.forEach(c => {
    const d = document.createElement('div');
    d.setAttribute('data-task-id', c.id);
    const p = document.createElement('div');
    p.className = 'card-prompt';
    p.textContent = c.prompt;
    d.appendChild(p);
    const s = document.createElement('div');
    s.className = 'card-status';
    s.textContent = c.status;
    d.appendChild(s);
    const dl = document.createElement('button');
    dl.className = 'download';
    dl.textContent = '下载';
    dl.addEventListener('click', () => {
      const blob = new Blob(['video'], {type: 'video/mp4'});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'original.mp4';
      a.click();
    });
    d.appendChild(dl);
    cards.appendChild(d);
  });
  document.getElementById('balance').textContent = window.__balance.toFixed(2);
  document.getElementById('credits').textContent = window.__credits.toFixed(2) + ' credits';
}
setInterval(() => {
  const bal = document.getElementById('balance');
  if (bal) bal.textContent = window.__balance.toFixed(2);
  const cr = document.getElementById('credits');
  if (cr) cr.textContent = window.__credits.toFixed(2) + ' credits';
}, 200);
</script>
</body></html>'''


def make_profile(url: str) -> dict:
    return {
        'url': url,
        'test_mode': True,
        'timeout_ms': 3000,
        'controls': {
            'model': {'read': '#model-select', 'trigger': '#model-select', 'option': '#model-select option[value="{value}"]'},
            'mode': {'read': '#mode-select', 'trigger': '#mode-select', 'option': '#mode-select option[value="{value}"]'},
            'resolution': {'read': '#resolution-select', 'trigger': '#resolution-select', 'option': '#resolution-select option[value="{value}"]'},
            'ratio': {'read': '#ratio-select', 'trigger': '#ratio-select', 'option': '#ratio-select option[value="{value}"]'},
            'duration_seconds': {'read': '#duration-select', 'trigger': '#duration-select', 'option': '#duration-select option[value="{value}"]'},
            'count': {'read': '#count-select', 'trigger': '#count-select', 'option': '#count-select option[value="{value}"]'},
        },
        'upload': '#upload',
        'reference_items': '#refs > div',
        'reference_name_attribute': 'data-filename',
        'reference_count': '#refcount',
        'prompt': '#prompt',
        'credits': '#credits',
        'balance': '#balance',
        'collapse': '#collapse',
        'cards': '#cards > div',
        'card_id_attribute': 'data-task-id',
        'card_prompt': '.card-prompt',
        'card_status': '.card-status',
        'download': 'button.download',
    }


class FixtureServer:
    def __init__(self) -> None:
        self._html = HTML

    def start(self) -> str:
        html = self._html
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                video = self.path == '/fixture.mp4' and hasattr(fixture, 'video')
                body = fixture.video if video else html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4' if video else 'text/html; charset=utf-8')
                if video:
                    self.send_header('Content-Disposition', 'attachment; filename=original.mp4')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f'http://127.0.0.1:{self.port}/'

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass


def base_task(tmp: Path, prompt: str = 'a cat') -> dict:
    return {
        'id': 't1',
        'generation': {
            'model': 'v1',
            'mode': 'standard',
            'resolution': '1080p',
            'ratio': '16:9',
            'duration_seconds': 15,
            'count': 1,
        },
        'duration_seconds': 15,
        'ratio': '16:9',
        'materials': [],
        'design': {'prompt': prompt},
    }


async def run_case(tmp: Path, prompt: str = 'a cat'):
    server = FixtureServer()
    url = server.start()
    browser = Browser(tmp, make_profile(url))
    try:
        await browser.start(headless=True)
        task = base_task(tmp, prompt)
        await browser.prepare(task)
        quote = await browser.quote(task)
        task['submission'] = {
            'before_ids': quote['before_ids'],
            'balance_before': quote['balance'],
            'quote_credits': quote['credits'],
        }
        task.update(attempted=True, intent_id='test-intent')
        await browser.submit(task)
        return browser, task, server
    except Exception:
        server.stop()
        await browser.close()
        raise


def test_default_params_and_count(tmp_path: Path) -> None:
    if not _HAS_BROWSER:
        pytest.skip("Playwright Chromium missing")
    async def main():
        server = FixtureServer()
        url = server.start()
        browser = Browser(tmp_path, make_profile(url))
        try:
            await browser.start(headless=True)
            task = base_task(tmp_path)
            paths = [tmp_path/'one.png', tmp_path/'two.png']
            for p in paths: p.write_bytes(TINY_PNG)
            task['materials'] = [{'path': str(p), 'name': p.name} for p in paths]
            await browser.prepare(task)
            assert await browser._page.locator('#refcount').inner_text() == '2 张'
            assert await browser._page.locator('#refs > div').all_text_contents() == ['one.png', 'two.png']
            assert await browser._page.locator('#resolution-select').input_value() == '1080p'
        finally:
            await browser.close()
            server.stop()
    asyncio.run(main())


def test_prepare_quote_submit_reconcile(tmp_path: Path) -> None:
    if not _HAS_BROWSER:
        pytest.skip("Playwright Chromium missing")
    async def main():
        browser, task, server = await run_case(tmp_path, 'hello world')
        try:
            result = await browser.reconcile(task)
            assert result['state'] == 'confirmed', result
            assert result['provider_task_id']
        finally:
            await browser.close()
            server.stop()
    asyncio.run(main())


def test_session_expired_selector_missing(tmp_path: Path) -> None:
    if not _HAS_BROWSER:
        pytest.skip("Playwright Chromium missing")
    async def main():
        server = FixtureServer()
        url = server.start()
        profile = make_profile(url)
        profile['credits'] = '#nonexistent-credits'
        browser = Browser(tmp_path, profile)
        try:
            await browser.start(headless=True)
            task = base_task(tmp_path)
            try:
                await browser.quote(task)
            except BrowserError:
                return
            raise AssertionError('expected BrowserError for missing selector')
        finally:
            await browser.close()
            server.stop()
    asyncio.run(main())


def test_missing_download_button_raises(tmp_path: Path) -> None:
    if not _HAS_BROWSER:
        pytest.skip("Playwright Chromium missing")
    async def main():
        browser, task, server = await run_case(tmp_path, 'download me')
        try:
            task['provider_task_id'] = 'nope'
            try:
                await browser.download(task)
            except BrowserError:
                return
            raise AssertionError('expected BrowserError for missing card')
        finally:
            await browser.close()
            server.stop()
    asyncio.run(main())
