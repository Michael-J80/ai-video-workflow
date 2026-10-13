import asyncio
import importlib.util
import pytest
from app.store import Store


def test_engine_exists():
    assert importlib.util.find_spec('app.engine'), 'orchestration missing'


class Browser:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def quote(self, task):
        return dict(credits=12, balance=100, evidence='evidence/q.png', before_ids=[])

    async def submit(self, task):
        self.calls += 1
        if self.fail:
            raise RuntimeError('window closed after Enter')

    async def reconcile(self, task):
        return dict(state='uncertain')


def test_exception_after_submission_does_not_retry(tmp_path):
    from app.engine import Engine
    s = Store(tmp_path)
    t = s.create({'requirements': 'test'})
    s.design(t['id'], dict(design='x', prompt='test', shots=[]))
    t = s.quote(t['id'], dict(credits=12, balance=100, evidence='evidence/q.png'))
    s.approve(t['id'], t['quote']['fingerprint'])
    b = Browser(fail=True)
    engine = Engine(s, b, None, None, None)
    asyncio.run(engine.submit(t['id']))
    assert s.get(t['id'])['state'] == 'SUBMISSION_UNCERTAIN'
    asyncio.run(engine.resume(t['id']))
    assert b.calls == 1


def test_pause_before_commit_does_not_submit(tmp_path):
    from app.engine import Engine
    s = Store(tmp_path)
    t = s.create({'requirements': 'test'})
    s.update(t['id'], paused=True, state='PAUSED')
    b = Browser()
    asyncio.run(Engine(s, b, None, None, None).submit(t['id']))
    assert b.calls == 0
