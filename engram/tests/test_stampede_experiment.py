import json
import shutil
import threading
from pathlib import Path

import pytest

from deploy.stampede.experiment import build_cells, run_cell
from sharing import list_shares
from storage import Storage


class FixtureProvider:
    def __init__(self, mode='publish'):
        self.packets = []
        self.mode = mode

    def generate(self, messages, **kwargs):
        p = json.loads(messages[-1]['content'])
        self.packets.append(p)
        publication = {'action': 'none'}
        if self.mode == 'publish' and p['agent_id'] == 'agent-0000' and p['turn'] == 0:
            publication = {'action': 'publish', 'content': 'Selected evidence only',
                           'source_ids': [p['sources'][0]['id']], 'audience': p['audience']}
        if self.mode == 'denied':
            publication = {'action': 'publish', 'content': 'Not exposed',
                           'source_ids': ['sealed-calibration'], 'audience': p['audience']}
        if self.mode == 'withdraw' and p['turn'] == 1:
            own = [s for s in p['shared_memory'] if s['author'] == p['agent_id']]
            if own:
                publication = {'action': 'withdraw', 'share_id': own[0]['share_id']}
        if self.mode == 'withdraw' and p['turn'] == 0:
            publication = {'action': 'publish', 'content': 'Withdraw me',
                           'source_ids': [p['sources'][0]['id']], 'audience': p['audience']}
        content = {'answer': 'engineering assessment', 'memory': 'private-' + p['agent_id'],
                   'publication': publication}
        return {'text': 'bad json' if self.mode == 'bad' else json.dumps(content),
                'input_tokens': 10, 'output_tokens': 8, 'model': 'fixture'}


def config(**kwargs):
    return dict(max_turns=2, cell_seconds=20, request_timeout_s=2,
                max_output_tokens=128, data_mode='synthetic', **kwargs)


def cell(individual=True, shared=True):
    return dict(id='test-cell', population=2, individual=individual, shared=shared,
                concurrency=2, seed=17, kind='factorial')


def test_matrix():
    cells = build_cells({})
    assert len(cells) == 20
    assert len({c['id'] for c in cells}) == 20
    assert len([c for c in cells if c['kind'] == 'serial']) == 4
    assert all(c['concurrency'] == 1 for c in cells if c['kind'] == 'serial')
    assert cells == build_cells({})


def test_serial_reference_receives_both_evidence_cohorts(tmp_path):
    reference = next(c for c in build_cells({}) if c['kind'] == 'serial')
    provider = FixtureProvider('none')
    result = run_cell(reference, config(), tmp_path/'local', tmp_path/'durable', provider)
    assert result['status'] == 'complete'
    exposed = {s['id'] for packet in provider.packets for s in packet['sources']}
    assert exposed == {'intake-log', 'bench-log', 'gauge-correction', 'firmware-note'}


def test_export_snapshot_lock_blocks_checkpoint_mutation(tmp_path):
    import concurrent.futures
    import fcntl
    durable = tmp_path/'durable'/'test-cell'
    durable.mkdir(parents=True)
    provider = FixtureProvider('none')
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with (durable/'snapshot.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            future = pool.submit(run_cell, cell(), config(), tmp_path/'local', tmp_path/'durable', provider)
            try:
                with pytest.raises(concurrent.futures.TimeoutError):
                    future.result(timeout=.5)
                assert not (durable/'CURRENT').exists()
                assert not provider.packets
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        assert future.result(timeout=10)['status'] == 'complete'


@pytest.mark.parametrize('individual,shared', [(False, False), (True, False), (False, True), (True, True)])
def test_real_memory_isolation_resume(tmp_path, individual, shared):
    p = FixtureProvider()
    local, durable = tmp_path/'local', tmp_path/'durable'
    result = run_cell(cell(individual, shared), config(), local, durable, p)
    assert result['status'] == 'complete'
    assert result['completed_turns'] == 4
    assert result['usage']['input_tokens'] == 40
    later = [x for x in p.packets if x['turn'] == 1]
    for packet in later:
        memory = json.dumps(packet['individual_memory'])
        assert (('private-' + packet['agent_id']) in memory) == individual
        assert ('private-agent-0001' if packet['agent_id'] == 'agent-0000' else 'private-agent-0000') not in memory
        assert bool(packet['shared_memory']) == shared
        assert 'private-agent' not in json.dumps(packet['shared_memory'])
    stores = list((local/'test-cell'/'stores').glob('agent-*.sqlite'))
    assert len(stores) == 2
    published = Storage(str(local/'test-cell'/'stores'/'published.sqlite'))
    try:
        shares = list_shares(published_storage=published)
        assert len(shares) == int(shared)
        if shared:
            assert shares[0].source_instance.endswith('/agent-0000')
    finally:
        published.close()
    shutil.rmtree(local)
    again = run_cell(cell(individual, shared), config(), local, durable, p)
    assert again['completed_turns'] == 4
    assert len(p.packets) == 4
    assert len(list((local/'test-cell'/'stores').glob('agent-*.sqlite'))) == 2


@pytest.mark.parametrize('mode', ['bad', 'denied'])
def test_invalid_publication_and_malformed_output(tmp_path, mode):
    result = run_cell(cell(), config(), tmp_path/'local', tmp_path/'durable', FixtureProvider(mode))
    assert result['errors']
    assert result['completed_turns'] == 4
    store = Storage(str(tmp_path/'local'/'test-cell'/'stores'/'published.sqlite'))
    try:
        assert list_shares(published_storage=store) == []
    finally:
        store.close()


def test_withdrawal_real_storage(tmp_path):
    result = run_cell(cell(), config(), tmp_path/'local', tmp_path/'durable', FixtureProvider('withdraw'))
    assert result['status'] == 'complete'
    store = Storage(str(tmp_path/'local'/'test-cell'/'stores'/'published.sqlite'))
    try:
        assert list_shares(published_storage=store) == []
    finally:
        store.close()
    assert sum(e['action'] == 'withdraw' for e in result['publication_events']) == 2


def test_interruption_resume_and_ignore_incomplete_generation(tmp_path):
    stop = threading.Event()
    stop.set()
    p = FixtureProvider()
    local, durable = tmp_path/'local', tmp_path/'durable'
    result = run_cell(cell(), config(), local, durable, p, stop_event=stop)
    assert result['status'] == 'interrupted'
    assert not p.packets
    (durable/'test-cell'/'generations'/'incomplete').mkdir()
    shutil.rmtree(local)
    stop.clear()
    result = run_cell(cell(), config(), local, durable, p, stop_event=stop)
    assert result['status'] == 'complete'
    assert len(p.packets) == 4


def test_unshared_peer_source_cannot_be_published(tmp_path):
    class Leak(FixtureProvider):
        def generate(self, messages, **kwargs):
            result = super().generate(messages, **kwargs)
            p = self.packets[-1]
            data = json.loads(result['text'])
            if p['agent_id'] == 'agent-0001' and p['turn'] == 0:
                data['publication'] = dict(action='publish', content='Guessed peer data',
                    source_ids=['intake-log'], audience=p['audience'])
                result['text'] = json.dumps(data)
            return result
    result = run_cell(cell(), config(), tmp_path/'l', tmp_path/'d', Leak('none'))
    assert len(result['errors']) == 1
    assert 'unexposed' in result['errors'][0]['error']


def test_deadline_bounded_concurrency_and_call_budget(tmp_path):
    import time
    class Slow(FixtureProvider):
        def generate(self, messages, **kwargs):
            time.sleep(.5)
            return super().generate(messages, **kwargs)
    cfg = config()
    cfg['cell_seconds'] = .25
    start = time.monotonic()
    result = run_cell(cell(), cfg, tmp_path/'l', tmp_path/'d', Slow())
    assert time.monotonic() - start < 1
    assert result['status'] == 'deadline'
    assert result['completed_turns'] == 0
    assert result['usage']['requests'] == 2
    assert result['usage']['missing_usage_requests'] == 2
    cfg = config(max_calls_per_cell=1)
    p = FixtureProvider()
    result = run_cell(cell(), cfg, tmp_path/'l2', tmp_path/'d2', p)
    assert result['status'] == 'call_budget'
    assert len(p.packets) == 1
    assert result['completed_turns'] == 1
    again = run_cell(cell(), cfg, tmp_path/'l2', tmp_path/'d2', p)
    assert again['status'] == 'call_budget'
    assert len(p.packets) == 1


def test_partial_resume_skips_completed_turns_and_cell_lock(tmp_path):
    stop = threading.Event()
    class StopAfterOne(FixtureProvider):
        def generate(self, messages, **kwargs):
            response = super().generate(messages, **kwargs)
            stop.set()
            return response
    c = cell()
    c['concurrency'] = 1
    p = StopAfterOne()
    local, durable = tmp_path/'l', tmp_path/'d'
    result = run_cell(c, config(), local, durable, p, stop_event=stop)
    assert result['completed_turns'] == 1
    shutil.rmtree(local)
    q = FixtureProvider()
    result = run_cell(c, config(), local, durable, q)
    assert result['status'] == 'complete'
    assert len(q.packets) == 3
    import fcntl
    with (durable/'test-cell'/'owner.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match='already owned'):
            run_cell(c, config(), local, durable, q)


def test_prompt_ceiling_preserves_exposure_record(tmp_path):
    class HugeMemory(FixtureProvider):
        def generate(self, messages, **kwargs):
            r = super().generate(messages, **kwargs)
            d = json.loads(r['text'])
            d['memory'] = 'x' * 5000
            r['text'] = json.dumps(d)
            return r
    p = HugeMemory('none')
    result = run_cell(cell(), config(max_prompt_chars=2000), tmp_path/'l', tmp_path/'d', p)
    assert result['status'] == 'complete'
    assert all(len(json.dumps(packet)) <= 2000 for packet in p.packets)


def test_publication_ancestry_and_withdrawal_visibility(tmp_path):
    class Derived(FixtureProvider):
        def generate(self, messages, **kwargs):
            response = super().generate(messages, **kwargs)
            p = json.loads(messages[-1]['content'])
            data = json.loads(response['text'])
            if p['agent_id'] == 'agent-0001' and p['turn'] == 1:
                data['publication'] = dict(action='publish', content='Attributed secondary review',
                    source_ids=['intake-log'], audience=p['audience'])
            response['text'] = json.dumps(data)
            return response
    result = run_cell(cell(), config(), tmp_path/'l', tmp_path/'d', Derived())
    derived = [e for e in result['publication_events'] if e.get('author') == 'agent-0001'][0]
    assert derived['parent_shares'][0]['author'] == 'agent-0000'
    cfg = config()
    cfg['max_turns'] = 3
    p = FixtureProvider('withdraw')
    result = run_cell(cell(), cfg, tmp_path/'l2', tmp_path/'d2', p)
    assert result['status'] == 'complete'
    assert all(not x['shared_memory'] for x in p.packets if x['turn'] == 2)


def test_missing_usage_is_not_fabricated_and_corrupt_snapshot_rejected(tmp_path):
    class NoUsage(FixtureProvider):
        def generate(self, messages, **kwargs):
            r = super().generate(messages, **kwargs)
            r['input_tokens'] = None
            r['output_tokens'] = None
            return r
    local, durable = tmp_path/'l', tmp_path/'d'
    result = run_cell(cell(), config(), local, durable, NoUsage())
    assert result['usage']['input_tokens'] == 0
    assert result['usage']['missing_usage_requests'] == 4
    pointer = json.loads((durable/'test-cell'/'CURRENT').read_text())
    snapshot = durable/'test-cell'/'generations'/pointer['generation']/'agent-0000.sqlite'
    with snapshot.open('ab') as f:
        f.write(b'corruption')
    shutil.rmtree(local)
    with pytest.raises(RuntimeError, match='integrity'):
        run_cell(cell(), config(), local, durable, FixtureProvider())


def test_concurrency_is_a_real_request_cap(tmp_path):
    import time
    class Concurrent(FixtureProvider):
        def __init__(self):
            super().__init__('none')
            self.lock = threading.Lock()
            self.active = self.peak = 0
        def generate(self, messages, **kwargs):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(.01)
            response = super().generate(messages, **kwargs)
            with self.lock:
                self.active -= 1
            return response
    p = Concurrent()
    c = cell()
    c['population'] = 5
    result = run_cell(c, config(), tmp_path/'l', tmp_path/'d', p)
    assert result['status'] == 'complete'
    assert p.peak == 2
    assert result['completed_turns'] == 10
    assert all(n == 2 for n in result['agent_completed_turns'].values())


def test_community_session_budget_resumes_stable_identity(tmp_path):
    c = build_cells({'community_population': 2})[-1]
    assert c['kind'] == 'community'
    cfg = config(session_seconds=.00001)
    local, durable = tmp_path/'l', tmp_path/'d'
    p = FixtureProvider()
    first = run_cell(c, cfg, local, durable, p)
    assert first['status'] == 'deadline'
    assert first['deadline_scope'] == 'session'
    assert first['completed_turns'] == 0
    assert not p.packets
    cfg['session_seconds'] = 10
    resumed = run_cell(c, cfg, local, durable, p)
    assert resumed['status'] == 'complete'
    assert resumed['completed_turns'] == 4
    assert len(p.packets) == 4
