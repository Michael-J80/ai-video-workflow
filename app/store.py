"""Durable, transactional submission intent. Never infer permission from a restart."""
import copy
import hashlib
import json
import math
import sqlite3
import time
import uuid
from pathlib import Path

DEFAULT = dict(model='Seedance 2.5', mode='样片模式', resolution='480P', count=1)
BUSY = {'DESIGNING', 'PREPARING', 'APPROVED', 'SUBMITTING', 'MONITORING', 'DOWNLOADING', 'ANALYZING'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(task, quote):
    fields = {k: task.get(k) for k in ('design', 'generation', 'duration_seconds', 'ratio', 'materials', 'design_version')}
    fields['credits'] = quote['credits']
    return hashlib.sha256(canonical(fields).encode()).hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'workflow.sqlite3'
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def connect(self):
        c = sqlite3.connect(self.db, timeout=15)
        c.execute('PRAGMA synchronous=FULL')
        return c

    def directory(self, task_id):
        if not isinstance(task_id, str) or not task_id.isalnum() or len(task_id) != 32:
            raise ValueError('无效任务ID')
        return self.root / 'tasks' / task_id

    def get(self, task_id):
        with self.connect() as c:
            row = c.execute('SELECT body FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        return json.loads(row[0])

    def list(self):
        with self.connect() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT body FROM tasks ORDER BY rowid DESC')]

    def mutate(self, task_id, fn):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT body FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ValueError('任务不存在')
            task = json.loads(row[0])
            fn(task)
            task['updated_at'] = time.time()
            c.execute('UPDATE tasks SET body=? WHERE id=?', (canonical(task), task_id))
        return task

    def update(self, task_id, **values):
        return self.mutate(task_id, lambda t: t.update(values))

    def create(self, data):
        req = str(data.get('requirements', '')).strip()
        if not req or len(req) > 12000:
            raise ValueError('需求需为1–12000字')
        generation = dict(DEFAULT)
        if data.get('generation'):
            if not data.get('override_source', '').strip():
                raise ValueError('修改默认参数须填写明确覆盖依据')
            if set(data['generation']) - set(DEFAULT):
                raise ValueError('未知生成参数')
            generation.update(data['generation'])
        if generation['count'] != 1 or not all(isinstance(generation[k], str) and 0 < len(generation[k]) < 100 for k in ('model', 'mode', 'resolution')):
            raise ValueError('第一版仅支持每任务1条，模型/模式/分辨率必须有效')
        seconds = data.get('duration_seconds', 15)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 3 <= seconds <= 30:
            raise ValueError('时长须为3–30秒，实际可用范围以网页为准')
        ratio = data.get('ratio', '9:16')
        if ratio not in ('9:16', '16:9', '1:1', '4:3', '3:4'):
            raise ValueError('画幅不支持')
        if data.get('device', 'cuda') not in ('cpu', 'cuda'):
            raise ValueError('设备须为cpu或cuda')
        for name in ('require_audio', 'skip_speech'):
            if name in data and type(data[name]) is not bool:
                raise ValueError('音频选项必须为布尔值')
        task_id = uuid.uuid4().hex
        task = dict(id=task_id, schema_version=1, requirements=req, generation=generation,
                    desired_generation=data.get('desired_generation', {}), override_source=data.get('override_source', ''),
                    duration_seconds=seconds, ratio=ratio, require_audio=bool(data.get('require_audio', True)),
                    device=data.get('device', 'cuda'), skip_speech=bool(data.get('skip_speech', False)),
                    state='NEW', materials=[], design=None, design_version=0, quote=None, approval=None,
                    attempted=False, intent_id=None, provider_task_id=None, error='', paused=False,
                    technical_status='NOT_RUN', content_status='UNVERIFIED', artifacts=[], created_at=time.time(), updated_at=time.time())
        self.directory(task_id).mkdir(parents=True)
        with self.connect() as c:
            c.execute('INSERT INTO tasks VALUES (?,?)', (task_id, canonical(task)))
        return task

    def design(self, task_id, design):
        def change(t):
            if t['attempted'] or t['state'] in BUSY - {'DESIGNING'}:
                raise ValueError('执行中或已提交，不能修改设计；请新建任务')
            t.update(design=copy.deepcopy(design), design_version=t['design_version'] + 1,
                     state='DESIGNED', quote=None, approval=None, error='')
        return self.mutate(task_id, change)

    def quote(self, task_id, quote):
        def change(t):
            if t['attempted'] or not t['design']:
                raise ValueError('当前任务不能报价')
            for name in ('credits', 'balance'):
                if type(quote.get(name)) not in (int, float) or not math.isfinite(quote[name]) or quote[name] < 0:
                    raise ValueError('报价和余额必须有真实数值')
            q = copy.deepcopy(quote)
            q.update(fingerprint=fingerprint(t, q), captured_at=time.time())
            t.update(quote=q, approval=None, state='QUOTED', error='')
        return self.mutate(task_id, change)

    def approve(self, task_id, expected):
        def change(t):
            if t['state'] != 'QUOTED' or t['attempted'] or t['paused'] or not t['quote'] or expected != t['quote']['fingerprint']:
                raise ValueError('批准已失效、已使用或任务不在待报价状态')
            if time.time() - t['quote']['captured_at'] > 600:
                raise ValueError('报价超过10分钟，请重新准备')
            t.update(approval={'fingerprint': expected, 'at': time.time()}, state='APPROVED')
        return self.mutate(task_id, change)

    def claim(self, task_id, live):
        def change(t):
            if t['attempted'] or t['paused'] or t['state'] != 'APPROVED' or not t['approval']:
                raise ValueError('禁止重复提交或未经批准提交')
            if fingerprint(t, live) != t['approval']['fingerprint'] or time.time()-t['approval']['at'] > 600:
                raise ValueError('页面报价、任务内容或批准时效已变化，不能提交')
            if live['balance'] < live['credits']:
                raise ValueError('余额不足')
            t.update(attempted=True, intent_id=uuid.uuid4().hex, state='SUBMITTING',
                     submission={'balance_before': live['balance'], 'quote_credits': live['credits'],
                                 'credits_charged': 'UNKNOWN', 'submit_action': 'prompt.Enter', 'attempted_at': time.time(),
                                 'before_ids': list(live.get('before_ids', [])), 'quote_evidence': live.get('evidence')})
        return self.mutate(task_id, change)

    def recover(self):
        for task in self.list():
            if task['state'] in BUSY:
                state = 'SUBMISSION_UNCERTAIN' if task['attempted'] and not task['provider_task_id'] else 'PAUSED'
                self.update(task['id'], state=state, paused=True, error='程序重启，已保留提交记录。请恢复查询；不会再次提交。')
