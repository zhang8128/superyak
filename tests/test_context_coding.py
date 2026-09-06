import json
from pathlib import Path

import pytest

from context_compile import Budget, ContextCapacityError
from context_provider import ProviderError
from context_store import ContextStore, StoreConflict
from context_coding import CodingRuntime


def checkpoint(status='continue', summary='Implemented parser; tests still needed.'):
    return {'status': status, 'summary': summary, 'decisions': ['Keep public API stable'],
            'next_steps': ['Run parser tests'] if status == 'continue' else [], 'checks': []}


class Provider:
    model = 'fixture'
    capabilities = {'strict': False, 'budget_scope': 'episode', 'count_kind': 'estimate', 'billing': 'test'}

    def __init__(self, cwd, results):
        self.cwd = Path(cwd)
        self.results = list(results)
        self.requests = []
        self.observer = None
        self.output = 'one test passed'

    def count(self, payload):
        return len(json.dumps(payload).encode()) // 3

    def episode(self, payload, on_event, tool_handler=None):
        self.requests.append(payload)
        if self.observer:
            self.observer(payload)
        on_event({'method': 'item/completed', 'params': {'item': {
            'id': 'cmd', 'type': 'commandExecution', 'command': 'pytest',
            'status': 'completed', 'exitCode': 0, 'aggregatedOutput': self.output}}})
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        pass


def completed(status='complete', summary='Finished and tested parser.'):
    return {'status': 'completed', 'checkpoint': checkpoint(status, summary), 'usage': {'last': {'inputTokens': 100}}, 'reason': None}


def runtime(tmp_path, results, **kwargs):
    repo = tmp_path / 'repo'
    repo.mkdir(exist_ok=True)
    store = ContextStore(tmp_path / 'archive' / 'context.db')
    provider = Provider(repo, results)
    return CodingRuntime(store, provider, Budget(), **kwargs)


def test_two_episodes_restore_goal_checkpoint_and_observed_output(tmp_path):
    r = runtime(tmp_path, [completed('continue', 'Parser added to parse.py'), completed()])
    r.provider.observer = lambda _: assert_running(r.store)
    result = r.run('task', 'Implement a parser and test it')
    assert result['status'] == 'complete'
    assert result['episodes'] == 2
    second = json.dumps(r.provider.requests[1])
    assert 'Implement a parser and test it' in second
    assert 'Parser added to parse.py' in second
    assert 'one test passed' in second
    assert r.store.state('task') == []
    assert r.store.latest_event('task', 'coding_task')['role'] == 'user'
    assert r.store.latest_event('task', 'coding_event')['role'] == 'tool'
    assert r.store.manifest('task')['coding']['episode'] == 2
    r.close()


def assert_running(store):
    assert json.loads(store.latest_event('task', 'coding_progress')['content'])['status'] == 'running'


def test_episode_cap_pauses_then_resume_after_reopen(tmp_path):
    r = runtime(tmp_path, [completed('continue')], max_episodes=1)
    assert r.run('task', 'Fix parser')['status'] == 'paused'
    r.close()
    r = runtime(tmp_path, [completed()])
    result = r.run('task', resume=True)
    assert result['status'] == 'complete'
    assert result['episodes'] == 2
    assert len(r.provider.requests) == 1
    assert r.run('task', resume=True) == result
    assert len(r.provider.requests) == 1
    r.close()


@pytest.mark.parametrize('failure', [ProviderError('transport ended'), KeyboardInterrupt(),
    {'status': 'interrupted', 'checkpoint': None, 'usage': None, 'reason': 'hard context threshold'}])
def test_uncertain_episode_pauses_without_automatic_replay(tmp_path, failure):
    r = runtime(tmp_path, [failure, completed()])
    result = r.run('task', 'Change parser')
    assert result['status'] == 'paused'
    assert result['uncertain'] is True
    assert len(r.provider.requests) == 1
    with pytest.raises(StoreConflict):
        r.run('task', 'Change parser')
    result = r.run('task', resume=True)
    assert result['status'] == 'complete'
    assert 'uncertain' in json.dumps(r.provider.requests[1]).lower()
    assert 'inspect' in json.dumps(r.provider.requests[1]).lower()
    r.close()


def test_crash_marker_is_restored_and_original_goal_is_not_replaced(tmp_path):
    r = runtime(tmp_path, [completed('continue')], max_episodes=1)
    r.run('task', 'Original goal')
    progress = json.loads(r.store.latest_event('task', 'coding_progress')['content'])
    progress['status'] = 'running'
    r.store.append('task', 'system', json.dumps(progress), kind='coding_progress')
    r.close()
    r = runtime(tmp_path, [completed()])
    with pytest.raises(ValueError):
        r.run('task', 'Different goal', resume=True)
    r.run('task', resume=True)
    request = json.dumps(r.provider.requests[-1])
    assert 'Original goal' in request and 'uncertain' in request
    r.close()


def test_repo_identity_rejects_different_or_replaced_directory(tmp_path):
    r = runtime(tmp_path, [completed('continue')], max_episodes=1)
    r.run('task', 'Fix bug')
    (tmp_path / 'repo').rename(tmp_path / 'old-repo')
    (tmp_path / 'repo').mkdir()
    with pytest.raises(StoreConflict, match='repository'):
        r.run('task', resume=True)
    r.close()


def test_pins_preserve_user_provenance_and_required_capacity(tmp_path):
    r = runtime(tmp_path, [completed()])
    # Corrections may be added before a new coding task.
    pin = r.store.record_state('task', 'constraint', 'Do not change the public API')
    r.run('task', 'Add a parser')
    request = r.provider.requests[0]
    assert 'Do not change the public API' in json.dumps(request)
    assert r.store.state('task')[0]['source_id'] == pin['source_id']
    r.close()


def test_required_overflow_prevents_dispatch_and_leaves_resumable_task(tmp_path):
    r = runtime(tmp_path, [completed()])
    r.compiler.budget = Budget(input_ceiling=100, soft_target=50, context_window=1000, output_reserve=100, margin=0)
    result = r.run('task', 'x' * 2000)
    assert result['status'] == 'paused'
    assert result['uncertain'] is False
    assert not r.provider.requests
    r.close()


@pytest.mark.parametrize('field,value', [('summary', 42), ('status', []), ('status', {})])
def test_malformed_checkpoint_cannot_claim_completion(tmp_path, field, value):
    bad = completed()
    bad['checkpoint'][field] = value
    r = runtime(tmp_path, [bad])
    assert r.run('task', 'Fix bug')['status'] == 'paused'
    r.close()


def test_older_observations_recalled_with_original_links(tmp_path):
    r = runtime(tmp_path, [completed()])
    original = r.store.append('task', 'tool', 'Original exact failure output', kind='coding_event')
    r.store.append('task', 'tool', 'ZEBRA_FAILURE on package abc', kind='coding_observation', metadata={'event_id': original['id']})
    for _ in range(12):
        r.store.append('task', 'tool', 'Other test passed', kind='coding_observation')
    r.run('task', 'Fix ZEBRA_FAILURE')
    request = json.dumps(r.provider.requests[0])
    assert original['id'] in request
    assert 'ZEBRA_FAILURE on package abc' in request
    assert len(r.store.search('task', 'ZEBRA_FAILURE')) == 0  # Chat search remains isolated.
    read = r.memory.call('task', 'archive_read', {'id': original['id']})
    assert read['text'] == 'Original exact failure output'
    assert 'error' in r.memory.call('other', 'archive_read', {'id': original['id']})
    r.close()


def test_archive_tools_bound_pages_search_and_reject_private_artifacts(tmp_path):
    r = runtime(tmp_path, [completed()])
    event = r.store.append('task', 'tool', 'a' * 20000, kind='coding_event')
    assert len(r.memory.call('task', 'archive_read', {'id': event['id'], 'offset': 4000, 'limit': 4096})['text']) == 4096
    assert 'error' in r.memory.call('task', 'archive_read', {'id': event['id'], 'limit': 5000})
    private = r.store.put_artifact('other', b'private')
    assert 'error' in r.memory.call('task', 'archive_read', {'id': private})
    r.store.append('task', 'tool', 'Needle failure', kind='coding_observation', metadata={'event_id': event['id']})
    search = r.memory.call('task', 'archive_search', {'query': 'Needle'})
    assert search['results'][0]['metadata']['event_id'] == event['id']
    r.close()


def test_forgetting_task_removes_coding_records_and_artifacts(tmp_path):
    r = runtime(tmp_path, [completed()])
    r.provider.output = 'Large original output: ' + 'x' * 12000
    r.run('task', 'Fix bug')
    event = r.store.latest_event('task', 'coding_event')
    artifact = event['metadata']['artifact_id']
    assert r.store.read_artifact('task', artifact)
    r.store.forget_thread('task')
    assert r.store.latest_event('task', 'coding_task') is None
    assert r.store.latest_event('task', 'coding_progress') is None
    with pytest.raises(KeyError):
        r.store.read_artifact('task', artifact)
    r.close()


def test_bounded_long_run_keeps_goal_and_latest_checkpoint(tmp_path):
    r = runtime(tmp_path, [completed('continue', f'Completed step {i}') for i in range(19)] + [completed()], max_episodes=20)
    result = r.run('task', 'Finish all twenty parser migration steps')
    assert result['status'] == 'complete'
    assert len(r.provider.requests) == 20
    assert 'Completed step 18' in json.dumps(r.provider.requests[-1])
    assert all('Finish all twenty parser migration steps' in p['input'][-1]['content'] for p in r.provider.requests)
    assert all(len(json.dumps(p).encode()) < 24000 * 3 for p in r.provider.requests)
    assert all(len(p['input']) < 25 for p in r.provider.requests)
    r.close()


def test_external_source_is_removed_if_revoked_during_count(tmp_path):
    from context_compile import Candidate
    class Source:
        mode = 'fixture'
        def search(self, query, limit):
            return [Candidate('external', 'user', ('REVOKED_ACCOUNT',), score=10, version='v1')]
        def valid(self, candidate):
            return False
    r = runtime(tmp_path, [completed()], sources=(Source(),))
    r.run('task', 'Fix parser')
    assert 'REVOKED_ACCOUNT' not in json.dumps(r.provider.requests)
    r.close()


def test_interrupted_episode_records_current_usage_not_previous_usage(tmp_path):
    r = runtime(tmp_path, [completed('continue'), {'status': 'interrupted', 'checkpoint': None,
        'usage': {'input_tokens': 48001}, 'reason': 'hard context threshold'}])
    result = r.run('task', 'Fix parser')
    assert result['status'] == 'paused'
    assert result['episodes'] == 2
    assert result['usage'] == {'input_tokens': 48001}
    assert result['usage_episode'] == 2
    r.close()


def test_failed_episode_does_not_report_previous_usage_as_current(tmp_path):
    r = runtime(tmp_path, [completed('continue'), ProviderError('transport ended')])
    result = r.run('task', 'Fix parser')
    assert result['status'] == 'paused'
    assert result['usage'] is None
    assert result['usage_episode'] is None
    r.close()
