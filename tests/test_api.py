import importlib.util
from fastapi.testclient import TestClient


def test_api_module_exists():
    assert importlib.util.find_spec('app.api'), 'local HTTP interface missing'


def client(tmp_path):
    from app.api import create_app
    c = TestClient(create_app(tmp_path), base_url='http://127.0.0.1:8765')
    token = c.get('/api/session').json()['csrf_token']
    return c, {'X-CSRF-Token': token}


def test_csrf_and_cross_origin(tmp_path):
    c, headers = client(tmp_path)
    assert c.post('/api/tasks', json={'requirements': 'hello'}).status_code == 403
    assert c.post('/api/tasks', headers={**headers, 'Origin': 'https://evil.example'}, json={'requirements': 'hello'}).status_code == 403
    assert c.post('/api/tasks', headers=headers, json={'requirements': 'hello'}).status_code == 200


def test_task_edit_validation_and_files(tmp_path):
    c, h = client(tmp_path)
    t = c.post('/api/tasks', headers=h, json={'requirements': 'hello'}).json()
    assert c.post('/api/tasks/'+t['id']+'/design', headers=h, json={'prompt': 'x'}).status_code == 400
    assert c.get('/api/tasks/'+t['id']+'/files/workflow.sqlite3').status_code == 404
    assert c.post('/api/tasks/'+t['id']+'/approve', headers=h, json={'fingerprint': 'guess'}).status_code == 400


def test_upload_rejects_non_image(tmp_path):
    c, h = client(tmp_path)
    t = c.post('/api/tasks', headers=h, json={'requirements': 'hello'}).json()
    response = c.post('/api/tasks/'+t['id']+'/materials', headers=h, files={'files': ('evil.png', b'not png', 'image/png')})
    assert response.status_code == 400
