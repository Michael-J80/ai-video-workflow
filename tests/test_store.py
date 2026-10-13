import importlib.util
import pytest


def test_store_module_exists():
    assert importlib.util.find_spec('app.store') is not None, 'persistent submission gate missing'


@pytest.fixture
def store(tmp_path):
    from app.store import Store
    return Store(tmp_path)


def ready(store):
    t = store.create({'requirements': '三秒原创几何动画', 'duration_seconds': 3, 'ratio': '9:16'})
    store.design(t['id'], {'design': '几何动画', 'prompt': '原创圆形跳跃', 'shots': [{'start': 0, 'end': 3}]})
    return store.quote(t['id'], {'credits': 12, 'balance': 100, 'evidence': 'evidence/quote.png'})


def test_defaults_and_final_target(store):
    t = store.create({'requirements': 'x', 'desired_generation': {'resolution': '1080P'}})
    assert t['generation'] == {'model': 'Seedance 2.5', 'mode': '样片模式', 'resolution': '480P', 'count': 1}
    assert t['desired_generation']['resolution'] == '1080P'


def test_override_requires_explicit_source(store):
    with pytest.raises(ValueError):
        store.create({'requirements': 'x', 'generation': {'resolution': '1080P'}})
    t = store.create({'requirements': 'x', 'generation': {'mode': '正片模式', 'resolution': '1080P'}, 'override_source': '用户要求正片'})
    assert t['generation']['resolution'] == '1080P'


def test_atomic_single_submission(store):
    t = ready(store)
    store.approve(t['id'], t['quote']['fingerprint'])
    store.claim(t['id'], t['quote'])
    with pytest.raises(ValueError):
        store.claim(t['id'], t['quote'])
    assert store.get(t['id'])['attempted'] is True


def test_changed_quote_cannot_charge(store):
    t = ready(store)
    store.approve(t['id'], t['quote']['fingerprint'])
    with pytest.raises(ValueError):
        store.claim(t['id'], dict(t['quote'], credits=13))
    assert not store.get(t['id'])['attempted']


def test_edit_invalidates_approval(store):
    t = ready(store)
    store.design(t['id'], {'design': 'new', 'shots': [{'start': 0, 'end': 3}], 'prompt': 'new'})
    with pytest.raises(ValueError):
        store.approve(t['id'], t['quote']['fingerprint'])


def test_restart_is_uncertain_never_resubmits(store):
    from app.store import Store
    t = ready(store)
    store.approve(t['id'], t['quote']['fingerprint'])
    store.claim(t['id'], t['quote'])
    reopened = Store(store.root)
    reopened.recover()
    assert reopened.get(t['id'])['state'] == 'SUBMISSION_UNCERTAIN'
    with pytest.raises(ValueError):
        reopened.approve(t['id'], t['quote']['fingerprint'])


def test_states_stay_separate(store):
    t = ready(store)
    store.update(t['id'], state='DELIVERED', technical_status='PASS', content_status='UNVERIFIED')
    t = store.get(t['id'])
    assert t['technical_status'] == 'PASS' and t['content_status'] == 'UNVERIFIED'
    assert t['generation']['resolution'] == '480P'


def test_claim_persists_reconciliation_snapshot_atomically(store):
    t = ready(store)
    store.approve(t['id'], t['quote']['fingerprint'])
    live = dict(t['quote'], before_ids=['old-task'], evidence='evidence/live.png')
    claimed = store.claim(t['id'], live)
    assert claimed['submission']['before_ids'] == ['old-task']
    assert claimed['submission']['quote_evidence'] == 'evidence/live.png'
