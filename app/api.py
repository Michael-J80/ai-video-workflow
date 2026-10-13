import asyncio
import hashlib
import io
import json
import os
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .agents import CodexDesigner, HermesPlanner, validate_design
from .engine import Engine
from .store import Store, BUSY

PROJECT = Path(__file__).resolve().parents[1]


def create_app(root=None, engine=None):
    root = Path(root or os.environ.get('VIDEO_WORKFLOW_DATA', PROJECT/'data')).resolve()
    store = engine.store if engine else Store(root)
    config = {}
    if (PROJECT/'config.local.json').exists():
        config = json.loads((PROJECT/'config.local.json').read_text(encoding='utf-8-sig'))
    if engine is None:
        from .browser import Browser
        from .media import Analyzer
        profile_path = PROJECT / 'browser.local.json'
        if not profile_path.exists():
            profile_path = PROJECT/'browser.example.json'
        profile = json.loads(profile_path.read_text(encoding='utf-8-sig'))
        if profile.get('test_mode'):
            raise ValueError('正式应用不允许测试浏览器配置')
        engine = Engine(store, Browser(root, profile), CodexDesigner(config.get('codex', 'codex')),
                        HermesPlanner(config.get('hermes', 'hermes')), Analyzer(config))
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        await engine.shutdown()

    app = FastAPI(title='AI 视频工作流', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine

    @app.middleware('http')
    async def local_only(request, call_next):
        host = request.headers.get('host', '')
        if host not in ('127.0.0.1:8765', 'localhost:8765'):
            return JSONResponse({'error': '只允许本机固定端口访问'}, 403)
        origin = request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:8765', 'http://localhost:8765'):
            return JSONResponse({'error': '拒绝跨站请求'}, 403)
        if request.url.path.startswith('/api/') and request.url.path != '/api/session':
            if not secrets.compare_digest(request.cookies.get('workflow_session', ''), token):
                return JSONResponse({'error': '请刷新本地页面建立会话'}, 403)
        if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), token):
            return JSONResponse({'error': '请求校验失败，请刷新页面'}, 403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({'error': str(exc)}, 400)

    @app.exception_handler(RuntimeError)
    async def bad_runtime(request, exc):
        return JSONResponse({'error': str(exc)}, 400)

    @app.get('/api/session')
    async def session():
        response = JSONResponse({'csrf_token': token})
        response.set_cookie('workflow_session', token, httponly=True, samesite='strict')
        return response

    @app.get('/api/health')
    async def health():
        found = {name: ('已找到' if shutil.which(config.get(name, name)) else '未安装或不在PATH') for name in ('codex', 'hermes', 'ffmpeg', 'ffprobe')}
        if found['codex'] == '已找到' and not engine.lock.locked():
            try:
                result = await asyncio.wait_for(engine.designer.check(root), 20)
                found['codex'] = 'ChatGPT登录已确认' if result['authenticated'] else '请使用 codex login 登录ChatGPT'
            except Exception:
                found['codex'] = '账户/协议检查失败，请检查Codex版本与登录'
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                found['browser'] = '已安装' if Path(pw.chromium.executable_path).is_file() else '请运行安装脚本安装Chromium'
        except Exception:
            found['browser'] = 'Playwright不可用'
        return dict(found, live_verified=False)

    @app.post('/api/browser/login')
    async def login():
        if engine.lock.locked():
            raise ValueError('任务运行时不能重新打开登录页')
        await engine.browser.start()
        return {'message': '请在专用浏览器手动登录；登录数据只保存在本机'}

    @app.get('/api/tasks')
    async def tasks():
        return store.list()

    @app.get('/api/browser/inspect')
    async def inspect_browser():
        if engine.lock.locked():
            raise ValueError('请在没有运行任务时检查网页适配')
        return await engine.browser.inspect()

    @app.post('/api/tasks')
    async def create(request: Request):
        return store.create(await request.json())

    @app.get('/api/tasks/{task_id}')
    async def task(task_id: str):
        return store.get(task_id)

    @app.post('/api/tasks/{task_id}/materials')
    async def materials(task_id: str, files: list[UploadFile] = File(...)):
        t = store.get(task_id)
        if t['state'] != 'NEW' or t['design'] or t['attempted']:
            raise ValueError('素材仅在设计前上传；需要修改请新建任务')
        if not 1 <= len(files) <= 10:
            raise ValueError('第一版支持1–10张图片')
        pending = []
        for index, f in enumerate(files):
            raw = await f.read(10*1024*1024+1)
            if len(raw) > 10*1024*1024:
                raise ValueError('每张图片不得超过10MB')
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 25_000_000:
                        raise ValueError('图片像素过大')
                    image.load()
                    image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
                    output = io.BytesIO()
                    image.save(output, format='PNG')
            except Exception as exc:
                raise ValueError('请选择有效图片文件') from exc
            name = f'{index+1:02d}_'+re.sub(r'[^\w.-]', '_', Path(f.filename or 'image').stem)[:50]+'.png'
            content = output.getvalue()
            pending.append((name, content))
        # Upload decoding yields to other requests; recheck state before writing anything.
        if store.get(task_id)['state'] != 'NEW' or engine.active(task_id):
            raise ValueError('任务已开始，不能再上传素材')
        folder = store.directory(task_id)/'references'
        folder.mkdir(exist_ok=True)
        records = []
        for index, (name, content) in enumerate(pending):
            (folder/name).write_bytes(content)
            records.append(dict(id=str(index+1), name=name, path='references/'+name, sha256=hashlib.sha256(content).hexdigest()))
        return store.update(task_id, materials=records)

    def available(task_id):
        if any(not j.done() for j in engine.jobs.values()):
            raise ValueError('已有任务运行，请等待或暂停后再操作')
        return store.get(task_id)

    @app.post('/api/tasks/{task_id}/start')
    async def start(task_id: str):
        t = available(task_id)
        if t['attempted'] or t['design'] or t['state'] not in ('NEW', 'BLOCKED'):
            raise ValueError('请使用修改设计、准备或恢复操作')
        store.update(task_id, paused=False)
        engine.launch(task_id, engine.start)
        return store.get(task_id)

    @app.post('/api/tasks/{task_id}/design')
    async def design(task_id: str, request: Request):
        t = available(task_id)
        d = validate_design(await request.json(), t['duration_seconds'])
        t = store.design(task_id, d)
        engine.handoff(t)
        return t

    @app.post('/api/tasks/{task_id}/prepare')
    async def prepare(task_id: str):
        t = available(task_id)
        if t['attempted'] or not t['design']:
            raise ValueError('缺少设计或已尝试提交')
        store.update(task_id, paused=False)
        engine.launch(task_id, engine.prepare)
        return store.get(task_id)

    @app.post('/api/tasks/{task_id}/approve')
    async def approve(task_id: str, request: Request):
        available(task_id)
        t = store.approve(task_id, (await request.json()).get('fingerprint', ''))
        engine.launch(task_id, engine.submit)
        return t

    @app.post('/api/tasks/{task_id}/pause')
    async def pause(task_id: str):
        t = store.get(task_id)
        if t['state'] == 'DELIVERED':
            raise ValueError('已交付任务不需要暂停')
        return store.update(task_id, paused=True, state=t['state'] if engine.active(task_id) else 'PAUSED',
                            error='暂停已请求，将在当前步骤完成后停止；不会取消已提交的官网任务')

    @app.post('/api/tasks/{task_id}/resume')
    async def resume(task_id: str):
        t = available(task_id)
        if t['state'] not in ('PAUSED', 'BLOCKED', 'SUBMISSION_UNCERTAIN'):
            raise ValueError('此任务不需要恢复')
        engine.launch(task_id, engine.resume)
        return t

    @app.get('/api/tasks/{task_id}/events')
    async def events(task_id: str, request: Request):
        store.get(task_id)
        async def stream():
            previous = None
            while not await request.is_disconnected():
                current = json.dumps(store.get(task_id), ensure_ascii=False)
                if current != previous:
                    yield 'data: '+current+'\n\n'
                    previous = current
                else:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.get('/api/tasks/{task_id}/files/{name:path}')
    async def artifact(task_id: str, name: str):
        t = store.get(task_id)
        allowed = set(t['artifacts'])
        if t['technical_status'] != 'NOT_RUN':
            allowed.add('SHA256SUMS.txt')
        if t.get('quote'):
            allowed.add(t['quote'].get('evidence', ''))
        folder = store.directory(task_id).resolve()
        path = (folder/name).resolve()
        if name not in allowed or not path.is_relative_to(folder) or not path.is_file():
            return JSONResponse({'error': '文件不存在或未开放'}, 404)
        # HTML reviews are downloaded, never executed under the app origin.
        return FileResponse(path, filename=path.name if path.suffix == '.html' else None)

    app.mount('/static', StaticFiles(directory=PROJECT/'app/static'), name='static')

    @app.get('/')
    async def index():
        return FileResponse(PROJECT/'app/static/index.html')

    return app
