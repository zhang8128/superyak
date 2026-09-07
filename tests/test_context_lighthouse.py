"""Measure the provider boundary, including withdrawal during request counting."""
from copy import deepcopy
import json

import pytest

import neighbors
from context_compile import Budget, ContextCapacityError
from context_runtime import ContextRuntime
from context_store import ContextStore
from lighthouse_protocol import content_digest
from lighthouse_receipts import validate_receipt
from tests.test_context_runtime import RecordingProvider, answer
from tests.test_neighbors import ALLOW, policy


@pytest.fixture
def crossing(tmp_path, monkeypatch):
    from context_lighthouse import LighthouseSource
    instance = tmp_path / '.engram' / 'instances' / 'engram'
    instance.mkdir(parents=True)
    (instance / 'graph.db').touch()
    settings = instance / 'lighthouse-receiver.toml'
    settings.write_text('enabled = true\npublishers = ["why"]\nsocket_path = "s.sock"\npolicy_path = "policy.json"\n')
    policy_path = instance / 'policy.json'
    policy(policy_path)
    calls = []
    state = {'available': True, 'content': 'Shared bridge note: inspect the upstream support.'}

    def call(self, frame, *, deadline=None):
        calls.append(deepcopy(frame))
        if frame['kind'] == 'recall':
            return dict(protocolVersion='0.1', kind='recall_result', turnId='publisher-turn',
                        queryDigest=content_digest(frame['query']), context=frame['context'],
                        candidates=[dict(memoryId='m1', rank=1, layer='episode', lane='personal',
                                         audiences=['commons'], contentDigest=content_digest(state['content']))],
                        decision=ALLOW, disclosureId='trace')
        return dict(protocolVersion='0.1', kind='read_result', disclosureId='read', items=[
            dict(memoryId='m1', content=state['content'] if state['available'] else None,
                 audiences=['commons'], decision=ALLOW)])

    monkeypatch.setattr(neighbors.LighthouseClient, 'call', call)
    store = ContextStore(tmp_path / 'context.db')
    source = LighthouseSource(store, receiver='engram', instance_dir=instance,
                              context_id='memory/technical', purpose='session-recall')
    yield store, source, calls, state, settings, policy_path
    store.close()


def test_allowed_share_reaches_counted_payload_with_receipt_before_generation(crossing):
    store, source, calls, state, _, _ = crossing
    provider = RecordingProvider()
    generate = provider.generate
    def check(payload):
        receipts = store.recent_kind('t', 'lighthouse_receipt', 8)
        dispatch = [r['metadata']['receipt'] for r in receipts
                    if r['metadata']['stage'] == 'model_dispatch']
        assert len(dispatch) == 1
        validate_receipt(dispatch[0])
        assert dispatch[0]['payload']['injected'] is True
        assert state['content'] not in json.dumps(receipts)
        return generate(payload)
    provider.generate = check
    runtime = ContextRuntime(store, provider, Budget(), sources=[source])
    result = runtime.chat('t', 'What should we inspect?')
    assert state['content'] in json.dumps(provider.requests[0])
    manifest = store.manifest('t', result['manifest_id'])
    selected = next(x for x in manifest['selected'] if x['id'].startswith('lighthouse:'))
    assert selected['required'] is False and selected['version']
    assert manifest['source_dispatch'][0]['receipt_id']
    assert [x['kind'] for x in calls] == ['recall', 'read', 'read']
    assert not store.search('t', 'upstream support')


@pytest.mark.parametrize('withdraw', ['receiver', 'settings', 'publisher', 'content'])
def test_withdrawal_after_count_removes_share_and_recounts(crossing, withdraw):
    store, source, calls, state, settings, policy_path = crossing
    provider = RecordingProvider()
    count = provider.count
    changed = False
    def revoke(payload):
        nonlocal changed
        result = count(payload)
        if not changed:
            changed = True
            if withdraw == 'receiver': policy(policy_path, actions=('recall', 'read'))
            elif withdraw == 'settings': settings.write_text('enabled = false\n')
            elif withdraw == 'publisher': state['available'] = False
            else: state['content'] = 'Changed publisher content'
        return result
    provider.count = revoke
    runtime = ContextRuntime(store, provider, Budget(), sources=[source])
    runtime.chat('t', 'What should we inspect?')
    assert 'Shared bridge note' not in json.dumps(provider.requests)
    assert len(provider.counted) == 2


def test_active_tool_episode_stops_when_publisher_withdraws(crossing):
    store, source, calls, state, _, _ = crossing
    tool = {'type': 'function_call', 'name': 'archive_search', 'call_id': 'c',
            'arguments': json.dumps({'query': 'bridge'})}
    provider = RecordingProvider([{'status': 'completed', 'output': [tool]}])
    generate = provider.generate
    def revoke(payload):
        result = generate(payload)
        state['available'] = False
        return result
    provider.generate = revoke
    runtime = ContextRuntime(store, provider, Budget(), sources=[source])
    with pytest.raises(ContextCapacityError, match='Source'):
        runtime.chat('t', 'Inspect the bridge')
    assert len(provider.requests) == 1


def test_receipt_failure_prevents_neighbor_content_but_preserves_local_chat(crossing, monkeypatch):
    store, source, _, state, _, _ = crossing
    append = store.append
    def fail(*args, **kwargs):
        if kwargs.get('kind') == 'lighthouse_receipt': raise OSError('disk full')
        return append(*args, **kwargs)
    monkeypatch.setattr(store, 'append', fail)
    provider = RecordingProvider()
    ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'hello')
    assert state['content'] not in json.dumps(provider.requests)


def test_inspection_uses_thread_receipt_and_current_permissions(crossing):
    store, source, _, state, _, policy_path = crossing
    runtime = ContextRuntime(store, RecordingProvider(), Budget(), sources=[source])
    runtime.chat('a', 'bridge')
    source_id = 'lighthouse:why:m1'
    assert runtime.read_source('a', source_id)['text'] == state['content']
    assert 'error' in runtime.read_source('b', source_id)
    policy(policy_path, actions=())
    assert 'error' in runtime.read_source('a', source_id)


def test_unselected_share_has_no_model_dispatch_receipt(crossing):
    store, source, calls, state, _, _ = crossing
    # Mandatory request fits, but optional neighbor evidence cannot fit the soft target.
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget(soft_target=1), sources=[source])
    runtime.chat('t', 'hello')
    assert state['content'] not in json.dumps(provider.requests)
    assert all(r['metadata']['stage'] == 'source_preparation'
               for r in store.recent_kind('t', 'lighthouse_receipt', 8))
    assert [x['kind'] for x in calls] == ['recall', 'read']


def test_remote_tool_page_is_not_persisted_as_raw_tool_content(crossing):
    store, source, _, state, _, _ = crossing
    tool = {'type': 'function_call', 'name': 'archive_read', 'call_id': 'c',
            'arguments': json.dumps({'id': 'lighthouse:why:m1'})}
    provider = RecordingProvider([{'status': 'completed', 'output': [tool]}, answer('Inspected')])
    ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'bridge')
    assert state['content'] in json.dumps(provider.requests[-1])
    assert state['content'] not in json.dumps(store.recent_kind('t', 'tool'))
    assert store.manifest('t')['tool_source_snapshots']


def test_sessions_do_not_share_candidate_bodies(crossing):
    store, source, _, state, _, _ = crossing
    a, b = source.for_turn('a', 'a-turn'), source.for_turn('b', 'b-turn')
    candidates = a.search('bridge')
    assert candidates and not b.entries and not source.entries
    assert b.read(candidates[0].id) is None
    assert a.valid(candidates[0])


def test_dispatch_receipt_failure_removes_share_and_recounts(crossing, monkeypatch):
    store, source, _, state, _, _ = crossing
    append = store.append
    def fail(*args, **kwargs):
        if kwargs.get('metadata', {}).get('stage') == 'model_dispatch':
            raise OSError('disk full at dispatch')
        return append(*args, **kwargs)
    monkeypatch.setattr(store, 'append', fail)
    provider = RecordingProvider()
    ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'bridge')
    assert len(provider.counted) == 2
    assert state['content'] not in json.dumps(provider.requests)


def test_forget_removes_inspection_handles(crossing):
    store, source, _, _, _, _ = crossing
    runtime = ContextRuntime(store, RecordingProvider(), Budget(), sources=[source])
    runtime.chat('t', 'bridge')
    store.forget_thread('t')
    assert 'error' in runtime.read_source('t', 'lighthouse:why:m1')
    assert store.recent_kind('t', 'lighthouse_receipt') == []


@pytest.mark.parametrize('enabled', [False, None])
def test_missing_or_disabled_settings_never_contact_publisher(crossing, enabled):
    store, source, calls, _, settings, _ = crossing
    if enabled is None: settings.unlink()
    else: settings.write_text('enabled = false\n')
    runtime = ContextRuntime(store, RecordingProvider(), Budget(), sources=[source])
    runtime.chat('t', 'bridge')
    assert calls == []
    assert store.recent_kind('t', 'lighthouse_receipt') == []


def test_receiver_revoked_while_other_peer_is_read_is_removed(crossing, monkeypatch):
    store, source, calls, _, settings, policy_path = crossing
    settings.write_text(settings.read_text().replace('["why"]', '["why", "mike"]') + 'limit = 2\n')
    policy(policy_path, publisher='*')
    original = neighbors.LighthouseClient.call
    reads = 0
    def revoke(self, frame, **kwargs):
        nonlocal reads
        result = original(self, frame, **kwargs)
        if frame['kind'] == 'read':
            reads += 1
            if reads == 4: policy(policy_path, publisher='mike')
        return result
    monkeypatch.setattr(neighbors.LighthouseClient, 'call', revoke)
    provider = RecordingProvider()
    ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'bridge')
    assert store.manifest('t')['selected_ids'] == ['lighthouse:mike:m1']
    assert len(provider.counted) == 2


def test_tool_only_remote_dependency_stops_on_withdrawal(crossing, monkeypatch):
    store, source, _, state, _, _ = crossing
    runtime = ContextRuntime(store, RecordingProvider(), Budget(), sources=[source])
    runtime.chat('t', 'bridge')
    # A later turn may inspect an earlier authorized handle without selecting it.
    monkeypatch.setattr(type(source), 'search', lambda *args, **kwargs: [])
    tool = {'type': 'function_call', 'name': 'archive_read', 'call_id': 'c',
            'arguments': json.dumps({'id': 'lighthouse:why:m1'})}
    provider = RecordingProvider([{'status': 'completed', 'output': [tool]}])
    count = provider.count
    def revoke(payload):
        result = count(payload)
        if len(provider.counted) == 2: state['available'] = False
        return result
    provider.count = revoke
    runtime = ContextRuntime(store, provider, Budget(), sources=[source])
    with pytest.raises(ContextCapacityError, match='Source'):
        runtime.chat('t', 'Read that shared note')
    assert len(provider.requests) == 1


def test_historical_tool_handle_receipt_identifies_current_turn(crossing, monkeypatch):
    store, source, _, _, _, _ = crossing
    ContextRuntime(store, RecordingProvider(), Budget(), sources=[source]).chat('t', 'bridge')
    monkeypatch.setattr(type(source), 'search', lambda *args, **kwargs: [])
    tool = {'type': 'function_call', 'name': 'archive_read', 'call_id': 'c',
            'arguments': json.dumps({'id': 'lighthouse:why:m1'})}
    provider = RecordingProvider([{'status': 'completed', 'output': [tool]}, answer('Read it')])
    result = ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'Read that shared note')
    receipts = [r for r in store.recent_kind('t', 'lighthouse_receipt', 32)
                if r['turn_id'] == result['turn_id']]
    assert receipts and any(r['metadata']['stage'] == 'model_dispatch' for r in receipts)
    assert all(r['metadata']['receipt']['payload']['turnId'] == result['turn_id'] for r in receipts)


def test_malformed_dispatch_read_does_not_drop_healthy_peer(crossing, monkeypatch):
    store, source, _, _, settings, policy_path = crossing
    settings.write_text(settings.read_text().replace('["why"]', '["why", "mike"]') + 'limit = 2\n')
    policy(policy_path, publisher='*')
    original = neighbors.LighthouseClient.call
    read_counts = {}
    def fail(self, frame, **kwargs):
        if frame['kind'] == 'read':
            peer = frame['publisher']
            read_counts[peer] = read_counts.get(peer, 0) + 1
            if peer == 'mike' and read_counts[peer] >= 2:
                return {'protocolVersion': '0.1', 'kind': 'read_result', 'items': 'malformed'}
        return original(self, frame, **kwargs)
    monkeypatch.setattr(neighbors.LighthouseClient, 'call', fail)
    provider = RecordingProvider()
    ContextRuntime(store, provider, Budget(), sources=[source]).chat('t', 'bridge')
    assert store.manifest('t')['selected_ids'] == ['lighthouse:why:m1']
    assert len(provider.counted) == 2


def test_turn_deadline_caps_publisher_revalidation(crossing, monkeypatch):
    import time
    store, source, _, _, settings, _ = crossing
    settings.write_text(settings.read_text() + 'timeout_s = 10\n')
    deadline = time.monotonic() + 5
    session = source.for_turn('t', 'turn', deadline=deadline)
    candidates = session.search('bridge')
    observed = []
    original = neighbors.LighthouseClient.call
    def record(self, frame, **kwargs):
        observed.append(kwargs['deadline'])
        return original(self, frame, **kwargs)
    monkeypatch.setattr(neighbors.LighthouseClient, 'call', record)
    assert session.prepare_dispatch(candidates, 'digest')[0] == set()
    assert observed == [deadline]


def test_active_page_validation_stops_after_first_missing_source(crossing, monkeypatch):
    store, source, _, _, _, _ = crossing
    runtime = ContextRuntime(store, RecordingProvider(), Budget(), sources=[source])
    calls = []
    def missing(*args, **kwargs):
        calls.append(args)
        return {'error': 'unavailable'}
    monkeypatch.setattr(runtime, 'read_source', missing)
    reads = [{'id': 'lighthouse:why:m1', 'offset': i, 'limit': 1, 'digest': 'earlier'} for i in range(8)]
    with pytest.raises(ContextCapacityError):
        runtime._check_active_sources('t', {}, reads)
    assert len(calls) == 1


def test_real_socket_chat_and_withdrawal_after_count(tmp_path):
    import tempfile
    import threading
    from context_lighthouse import LighthouseSource
    from lighthouse_daemon import PublisherDaemon, PublisherStore
    from lighthouse_pilot import (ALLOWED_CONTENT, DENIED_CONTENT, PUBLISHER, RECEIVER,
                                  SyntheticEmbeddings, _seed_stores, _write_policy)
    stores = tmp_path / 'stores'
    stores.mkdir()
    _seed_stores(stores)
    instance = tmp_path / '.engram' / 'instances' / RECEIVER
    instance.mkdir(parents=True)
    memory = instance / 'graph.db'
    memory.write_bytes(b'existing receiver sentinel; never opened as Storage')
    before = memory.read_bytes()
    publisher_policy = tmp_path / 'publisher.json'
    receiver_policy = instance / 'policy.json'
    _write_policy(publisher_policy, issuer=PUBLISHER, peer=RECEIVER,
                  actions=('recall', 'read'), audiences=['commons'])
    _write_policy(receiver_policy, issuer=RECEIVER, peer=PUBLISHER,
                  actions=('recall', 'read', 'inject_context'))
    publisher = PublisherStore(PUBLISHER, stores / 'publisher.db', publisher_policy, stores / 'disclosures.db')
    store = ContextStore(tmp_path / 'context.db')
    try:
        with tempfile.TemporaryDirectory(prefix='lh-chat-', dir='/tmp') as socket_dir:
            from pathlib import Path
            daemon = PublisherDaemon({PUBLISHER: publisher}, Path(socket_dir) / 's.sock', SyntheticEmbeddings())
            worker = threading.Thread(target=daemon.serve_forever, daemon=True)
            worker.start()
            try:
                assert daemon.wait_ready(timeout=5)
                (instance / 'lighthouse-receiver.toml').write_text(
                    f'enabled = true\npublishers = ["{PUBLISHER}"]\nsocket_path = "{daemon.socket_path}"\npolicy_path = "policy.json"\n')
                source = LighthouseSource(store, receiver=RECEIVER, instance_dir=instance,
                                          context_id='memory/technical', purpose='session-recall')
                provider = RecordingProvider()
                runtime = ContextRuntime(store, provider, Budget(), sources=[source])
                runtime.chat('allowed', 'Synthetic bridge maintenance guidance')
                assert ALLOWED_CONTENT in json.dumps(provider.requests[-1])
                assert DENIED_CONTENT not in json.dumps(provider.requests)
                count = provider.count
                def withdraw(payload):
                    result = count(payload)
                    _write_policy(publisher_policy, issuer=PUBLISHER, peer=RECEIVER,
                                  actions=('recall', 'read'), effect='deny', audiences=['commons'])
                    return result
                provider.count = withdraw
                runtime.chat('withdrawn', 'Synthetic bridge maintenance guidance')
                assert ALLOWED_CONTENT not in json.dumps(provider.requests[-1])
                assert store.manifest('withdrawn')['count_attempts'] >= 1
                assert memory.read_bytes() == before
                for thread in ('allowed', 'withdrawn'):
                    for event in store.recent_kind(thread, 'lighthouse_receipt', 8):
                        validate_receipt(event['metadata']['receipt'])
                        assert ALLOWED_CONTENT not in json.dumps(event)
            finally:
                daemon.stop()
                worker.join(timeout=5)
    finally:
        store.close()
