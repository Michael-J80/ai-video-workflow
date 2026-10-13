"""Orchestrator + actual Chromium fixture + actual local media, no paid service."""
import asyncio
import json
import shutil
import subprocess
import pytest
from app.browser import Browser
from app.engine import Engine
from app.media import Analyzer
from app.store import Store
from test_browser import FixtureServer, make_profile, _HAS_BROWSER


def test_full_local_flow(tmp_path):
    if not _HAS_BROWSER or not shutil.which('ffmpeg'):
        pytest.skip('Chromium and FFmpeg required')
    async def main():
        server = FixtureServer()
        browser = Browser(tmp_path, make_profile(server.start()))
        class Designer:
            async def design(self, task, cwd):
                return {'design': 'test', 'shots': [{'start': 0, 'end': 15, 'description': 'shape'}], 'prompt': 'original geometric animation'}
        class Planner:
            async def plan(self, task, cwd):
                return ['verify_generation', 'upload_references', 'fill_prompt', 'read_quote']
        try:
            await browser.start(headless=True)
            store = Store(tmp_path)
            task = store.create({'requirements': 'original shape', 'generation': {'model': 'v1', 'mode': 'standard', 'resolution': '1080p'},
                                 'override_source': 'fixture only', 'duration_seconds': 15, 'ratio': '16:9', 'device': 'cpu', 'skip_speech': True, 'require_audio': False})
            engine = Engine(store, browser, Designer(), Planner(), Analyzer({}), poll_seconds=.01, monitor_timeout=2)
            await engine.start(task['id'])
            task = store.get(task['id'])
            assert task['state'] == 'QUOTED'
            assert not task['attempted']
            # This test uses a real local video through a fixture download, never the website.
            clip = tmp_path/'fixture.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=15','-c:v','libx264',str(clip)], check=True)
            server.video = clip.read_bytes()
            await browser._page.evaluate("""() => {
              const old = window.renderCards;
              window.renderCards = () => { old(); document.querySelectorAll('.card-status').forEach(x=>x.textContent='完成');
                document.querySelectorAll('button.download').forEach(x=>{const a=document.createElement('a'); a.className='download'; a.href='/fixture.mp4'; a.download='original.mp4'; a.textContent='下载'; x.replaceWith(a);}); };
            }""")
            browser.profile['download'] = 'a.download'
            store.approve(task['id'], task['quote']['fingerprint'])
            await engine.submit(task['id'])
            result = store.get(task['id'])
            assert result['state'] == 'DELIVERED', result.get('error')
            assert result['technical_status'] == 'PASS'
            assert result['content_status'] == 'UNVERIFIED'
            assert result['submission']['credits_charged'] == 3
            assert await browser._page.locator('[data-task-id]').count() == 1
            with pytest.raises(ValueError):
                store.approve(task['id'], task['quote']['fingerprint'])
        finally:
            await browser.close()
            server.stop()
    asyncio.run(main())
