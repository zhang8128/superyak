"""Guard tests; no installed model calls."""
import json
import pytest
from superyak_peer.common import Problem

APPROVED = {'model': 'superyak-clinical-gemma4-balanced:q4_k_m', 'publisher': 'HauhauCS',
            'base_publisher': 'Google', 'eligibility_basis': 'explicit_user_selection',
            'digest': '964dccf2e808c93bda5236b30231b1e72cadd9f12336fb505471f49add9810c4',
            'endpoint': 'http://127.0.0.1:11434'}

class NativeEndpoint:
    def __init__(self, digest=APPROVED['digest'], reply=None, failure=None):
        self.calls, self.digest, self.reply, self.failure = [], digest, reply, failure
    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == 'GET':
            return {'models': [{'name': APPROVED['model'], 'digest': self.digest}]}
        if self.failure:
            raise self.failure
        return self.reply or {'model': APPROVED['model'], 'done': True, 'response': 'A fictional private suggestion.'}

def adapter(endpoint=None, config=None):
    from superyak_peer.models import LocalGemma
    model = LocalGemma(APPROVED if config is None else config)
    endpoint = endpoint or NativeEndpoint()
    model._request = endpoint
    return model, endpoint

def test_disabled_default_manual_work(env):
    _, (patient, *_), _, _ = env
    assert patient.get('/api/assistant').json().get('enabled') is False
    assert patient.post('/api/assistant', json={'text': 'hello'}).status_code == 409
    assert patient.post('/api/layers', json={'body': 'manual draft'}).status_code == 201

@pytest.mark.parametrize('change', [{'model': 'gemma4:31b'}, {'model': 'qwen:latest'}, {'model': 'unknown'}, {'publisher': 'Unknown'}, {'digest': '0' * 64}, {'endpoint': 'https://third-party.example'}, {'fallback': 'gemma4:31b'}])
def test_unapproved_config_zero_dispatch(change):
    model, endpoint = adapter(config={**APPROVED, **change})
    with pytest.raises(Problem):
        model.suggest('fictional request', None)
    assert endpoint.calls == []

def test_mismatched_artifact_no_generation():
    model, endpoint = adapter(NativeEndpoint(digest='0' * 64))
    with pytest.raises(Problem):
        model.suggest('fictional request', None)
    assert [call[0] for call in endpoint.calls] == ['GET']

@pytest.mark.parametrize('endpoint', [NativeEndpoint(failure=TimeoutError()), NativeEndpoint(reply={'model': 'other', 'done': True, 'response': 'wrong'}), NativeEndpoint(reply={'model': APPROVED['model'], 'done': False, 'response': 'partial'}), NativeEndpoint(reply={'model': APPROVED['model'], 'done': True, 'response': 'x' * 17000})])
def test_unknown_outcome_disables_without_retry(endpoint):
    model, endpoint = adapter(endpoint)
    with pytest.raises(Problem):
        model.suggest('fictional request', None)
    with pytest.raises(Problem):
        model.suggest('second request', None)
    assert sum(call[0] == 'POST' for call in endpoint.calls) == 1
    assert model.status()['enabled'] is False

def test_owned_exact_saved_input_private_suggestion(env):
    app, (patient, doctor, *_), _, _ = env
    model, endpoint = adapter()
    app.state.assistant = model
    layer = patient.post('/api/layers', json={'title': 'Selected title', 'body': 'Selected body', 'public': True}).json()
    patient.post(f"/api/layers/{layer['id']}/activate", json={'version': 1})
    patient.post('/api/layers', json={'body': 'UNSELECTED SECRET'})
    request = {'text': 'Make this fictional text shorter', 'layer_id': layer['id'], 'version': 1}
    assert doctor.post('/api/assistant', json=request).status_code == 404
    assert patient.post('/api/assistant', json={**request, 'version': 2}).status_code == 409
    assert patient.post('/api/assistant', json={**request, 'model': 'other'}).status_code == 400
    assert endpoint.calls == []
    response = patient.post('/api/assistant', json=request)
    assert response.status_code == 200, response.text
    assert response.json()['suggestion'] == 'A fictional private suggestion.'
    assert response.json()['version'] == 1
    generated = endpoint.calls[-1][2]
    assert 'Selected body' in generated['prompt']
    assert 'UNSELECTED SECRET' not in json.dumps(generated)
    assert 'audience_users' not in generated['prompt']
    assert generated['stream'] is False and generated['options']['num_predict'] <= 1024
    assert patient.get(f"/api/layers/{layer['id']}").json()['body'] == 'Selected body'
    assert patient.get(f"/public/layers/{layer['id']}").json()['body'] == 'Selected body'

def test_input_bounds_before_dispatch():
    model, endpoint = adapter()
    with pytest.raises(Problem):
        model.suggest('x' * 8001, None)
    with pytest.raises(Problem):
        model.suggest('hello', {'title': 'title', 'body': 'x' * 32001})
    assert endpoint.calls == []


def test_truncated_completion_is_not_claimed_as_success():
    model, endpoint = adapter(NativeEndpoint(reply={'model': APPROVED['model'], 'done': True, 'done_reason': 'length', 'response': 'cut off'}))
    with pytest.raises(Problem):
        model.suggest('fictional request', None)
    assert sum(call[0] == 'POST' for call in endpoint.calls) == 1


def test_identity_is_rechecked_for_each_generation():
    model, endpoint = adapter()
    assert model.suggest('first fictional request', None)['private'] is True
    endpoint.digest = '0' * 64
    with pytest.raises(Problem):
        model.suggest('second fictional request', None)
    assert sum(call[0] == 'POST' for call in endpoint.calls) == 1


def test_native_http_has_total_deadline_even_for_trickling_headers(monkeypatch):
    """Break caught: socket inactivity timeouts permit an unbounded request."""
    import http.client
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time
    from superyak_peer import models
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            try:
                self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Pad: ')
                for _ in range(25):
                    self.connection.sendall(b'a')
                    time.sleep(.04)
                self.connection.sendall(b'\r\nContent-Length: 2\r\n\r\n{}')
            except OSError:
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection
    monkeypatch.setattr(models, 'GENERATION_TIMEOUT_SECONDS', .15, raising=False)
    monkeypatch.setattr(models.http.client, 'HTTPConnection', lambda *a, **kw: connection('127.0.0.1', server.server_port, timeout=.2))
    started = time.monotonic()
    failed = False
    try:
        try:
            models.LocalGemma(APPROVED)._request('POST', '/api/generate', {'fictional': 'deadline test'})
        except (OSError, ValueError, http.client.HTTPException):
            failed = True
        elapsed = time.monotonic() - started
        assert failed and elapsed < .6, f'failed={failed}, elapsed={elapsed}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_combined_prompt_budget_rejects_before_dispatch():
    model, endpoint = adapter()
    with pytest.raises(Problem):
        model.suggest('x' * 7000, {'title': 'Fiction', 'body': 'y' * 7000})
    assert endpoint.calls == []


def test_status_does_not_block_manual_home_while_first_request_checks_identity():
    import threading
    import time
    model, endpoint = adapter()
    entered = threading.Event()
    def delayed(method, path, payload=None):
        if method == 'GET':
            entered.set()
            time.sleep(.5)
        return endpoint(method, path, payload)
    model._request = delayed
    worker = threading.Thread(target=lambda: model.suggest('fictional request', None))
    worker.start()
    assert entered.wait(2)
    started = time.monotonic()
    model.status()
    elapsed = time.monotonic() - started
    worker.join(2)
    assert elapsed < .2
