"""Single worker. Agents prepare data; only this service can claim a submission."""
import asyncio
import hashlib
import json
import time
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class Engine:
    def __init__(self, store, browser, designer, planner, analyzer, poll_seconds=15, monitor_timeout=1800):
        self.store, self.browser, self.designer = store, browser, designer
        self.planner, self.analyzer = planner, analyzer
        self.poll_seconds, self.monitor_timeout = poll_seconds, monitor_timeout
        self.lock = asyncio.Lock()
        self.jobs = {}

    def launch(self, task_id, method):
        if any(not job.done() for job in self.jobs.values()):
            raise ValueError('已有任务运行，请等待完成或暂停')
        job = asyncio.create_task(method(task_id))
        self.jobs[task_id] = job
        return job

    def active(self, task_id):
        job = self.jobs.get(task_id)
        return job is not None and not job.done()

    def check_pause(self, task_id):
        t = self.store.get(task_id)
        if t['paused']:
            self.store.update(task_id, state='PAUSED')
            raise InterruptedError('任务已暂停；已提交的官网任务不会取消')
        return t

    def fail(self, task_id, exc):
        t = self.store.get(task_id)
        if isinstance(exc, InterruptedError):
            return
        uncertain = t['attempted'] and not t['provider_task_id']
        self.store.update(task_id, state='SUBMISSION_UNCERTAIN' if uncertain else 'BLOCKED', error=str(exc)[:1200])

    def material_integrity(self, t):
        for m in t['materials']:
            p = self.store.directory(t['id']) / m['path']
            if hashlib.sha256(p.read_bytes()).hexdigest() != m['sha256']:
                raise ValueError('参考素材已改变，请新建任务重新核价')

    def agent_task(self, t):
        result = dict(t)
        result['materials'] = [dict(m, path=str((self.store.directory(t['id']) / m['path']).resolve())) for m in t['materials']]
        return result

    def handoff(self, t):
        d = self.store.directory(t['id'])
        design = t['design']
        (d / 'prompt.txt').write_text(design['prompt'], encoding='utf-8')
        (d / 'design.md').write_text(design['design'], encoding='utf-8')
        write_json(d / 'shots.json', design['shots'])
        write_json(d / 'task_card.json', dict(schema_version=1, is_template=False, task_id=t['id'], version='v1',
                   kind='generated', design_version=t['design_version'], generation=t['generation'],
                   desired_generation=t['desired_generation'], materials=self.agent_task(t)['materials'], shots=design['shots'],
                   output_root=str(d/'results'), review_criteria=[],
                   expected={'duration_seconds': t['duration_seconds'], 'ratio': t['ratio'], 'require_audio': t['require_audio']},
                   prompt_file=str(d/'prompt.txt'), submission_record=str(d/'submission_record.json')))
        write_json(d/'handoff.json', {'schema_version': 1, 'task_id': t['id'], 'design_version': t['design_version'],
                    'handoff_phase': 'READY_FOR_EXECUTION', 'fee_approval': 'PENDING_ACTUAL_QUOTE',
                    'files': {key: str(d/name) for key, name in {'design': 'design.md', 'shots': 'shots.json',
                             'prompt': 'prompt.txt', 'task_card': 'task_card.json', 'submission_record': 'submission_record.json'}.items()}})

    async def start(self, task_id):
        async with self.lock:
            try:
                t = self.check_pause(task_id)
                if t['attempted'] or t['design']:
                    raise ValueError('不能重新设计已有设计或已提交任务；修改设计或新建任务')
                self.material_integrity(t)
                self.store.update(task_id, state='DESIGNING', error='')
                design = await self.designer.design(self.agent_task(t), self.store.directory(task_id))
                self.check_pause(task_id)
                t = self.store.design(task_id, design)
                self.handoff(t)
                await self._prepare(task_id)
            except Exception as exc:
                self.fail(task_id, exc)

    async def _prepare(self, task_id):
        t = self.check_pause(task_id)
        if t['attempted'] or not t['design']:
            raise ValueError('已尝试提交或设计缺失，不能重新准备')
        self.material_integrity(t)
        self.store.update(task_id, state='PREPARING', error='', approval=None, quote=None)
        task = self.agent_task(t)
        actions = await self.planner.plan(task, self.store.directory(task_id))
        if actions != ['verify_generation', 'upload_references', 'fill_prompt', 'read_quote']:
            raise ValueError('Hermes 输出了未授权动作')
        self.check_pause(task_id)
        await self.browser.prepare(task)
        self.check_pause(task_id)
        q = await self.browser.quote(task)
        self.store.quote(task_id, q)

    async def prepare(self, task_id):
        async with self.lock:
            try:
                await self._prepare(task_id)
            except Exception as exc:
                self.fail(task_id, exc)

    async def submit(self, task_id):
        async with self.lock:
            try:
                t = self.check_pause(task_id)
                self.material_integrity(t)
                live = await self.browser.quote(self.agent_task(t))
                self.check_pause(task_id)
                # Atomic DB intent is committed BEFORE any browser input. Never reset attempted.
                t = self.store.claim(task_id, live)
                write_json(self.store.directory(task_id)/'submission_record.json', t['submission'])
                await self.browser.submit(self.agent_task(t))
                await asyncio.sleep(2)
                await self._reconcile(task_id)
            except Exception as exc:
                self.fail(task_id, exc)

    async def _reconcile(self, task_id):
        t = self.check_pause(task_id)
        result = await self.browser.reconcile(self.agent_task(t))
        if result.get('state') != 'confirmed':
            self.store.update(task_id, state='SUBMISSION_UNCERTAIN', error='提交证据不足：只允许继续查询，不会重新提交。')
            return
        t = self.store.update(task_id, provider_task_id=result['provider_task_id'], state='MONITORING',
                              submission=dict(t['submission'], **result), error='')
        write_json(self.store.directory(task_id)/'submission_record.json', t['submission'])
        write_json(self.store.directory(task_id)/'cost_record.json', {'website_credits_charged': result['credits_charged'],
                   'balance_before': t['submission']['balance_before'], 'balance_after': result['balance_after'], 'model_api_cost': 'UNKNOWN'})
        await self._monitor(task_id)

    async def _monitor(self, task_id):
        deadline = time.monotonic() + self.monitor_timeout
        while time.monotonic() < deadline:
            t = self.check_pause(task_id)
            result = await self.browser.monitor(self.agent_task(t))
            if result['state'] == 'failed':
                raise RuntimeError('官网生成失败，保留费用记录；不会自动重试')
            if result['state'] == 'done':
                self.store.update(task_id, state='DOWNLOADING')
                path = await self.browser.download(self.agent_task(t))
                self.check_pause(task_id)
                self.store.update(task_id, state='ANALYZING')
                receipt = await self.analyzer.analyze(t, path, self.store.directory(task_id))
                self.store.update(task_id, technical_status=receipt['technical_status'],
                                  content_status=receipt['content_status'], artifacts=receipt['artifacts'], error='')
                self.check_pause(task_id)
                self.store.update(task_id, state='DELIVERED')
                return
            await asyncio.sleep(self.poll_seconds)
        raise TimeoutError('监控达到30分钟上限；可恢复查询，不会重复生成')

    async def resume(self, task_id):
        async with self.lock:
            try:
                t = self.store.update(task_id, paused=False, error='')
                if t['state'] == 'PAUSED' and t['technical_status'] in ('PASS', 'PARTIAL'):
                    receipt_path = self.store.directory(task_id)/'task_run.json'
                    original = self.store.directory(task_id)/'original.mp4'
                    if receipt_path.is_file() and original.is_file():
                        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                        with original.open('rb') as file:
                            same = hashlib.file_digest(file, 'sha256').hexdigest() == receipt.get('input_sha256')
                        if same:
                            self.store.update(task_id, state='DELIVERED')
                            return
                if t['attempted']:
                    if t['provider_task_id']:
                        self.store.update(task_id, state='MONITORING')
                        await self._monitor(task_id)
                    else:
                        await self._reconcile(task_id)
                elif t['design']:
                    await self._prepare(task_id)
                else:
                    self.store.update(task_id, state='NEW')
            except Exception as exc:
                self.fail(task_id, exc)

    async def shutdown(self):
        for job in self.jobs.values():
            if not job.done():
                job.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)
        if self.browser:
            await self.browser.close()
