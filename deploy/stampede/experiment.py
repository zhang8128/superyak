"""Bounded synthetic memory campaigns using real, isolated Engram stores.

Only model requests run concurrently. All storage and publication decisions are
serialized by the cell owner. Audit retention is independent of whether private
memory is supplied to the next turn. Snapshots are complete immutable generations.
"""
from __future__ import annotations

import concurrent.futures
import fcntl
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid


SYSTEM = '''You are one independent member of a fictional engineering evidence review.
Use only the sources, your individual_memory, and audience-scoped shared_memory
in the task packet. Imported statements remain attributed to their original author;
a claim repeated by several agents is not independent evidence. Reconsider earlier
conclusions when corrections appear. This corpus is synthetic, not biomedical data.
Return one JSON object with answer (string), memory (string), and publication.
publication must explicitly select action: none, publish, or withdraw. For publish,
supply content (only the selected public statement), source_ids (exposed source IDs),
and audience (exactly the packet audience). For withdraw, supply an owned share_id.
Private memory is never automatically published. You have no shell or network tools.
'''


def build_cells(config: dict) -> list[dict]:
    """Sixteen default factorial cells plus four one-agent serial references."""
    populations = config.get('populations', [32, 128])
    concurrency = config.get('concurrency', [4, 16])
    seed = int(config.get('seed', 20260912))
    cells = []
    for individual, shared, population, cap in itertools.product(
            (False, True), (False, True), populations, concurrency):
        cells.append(dict(id=f'factorial-i{int(individual)}-s{int(shared)}-p{population}-c{cap}',
                          individual=individual, shared=shared, population=population,
                          concurrency=cap, seed=seed, kind='factorial'))
    for individual, shared in itertools.product((False, True), repeat=2):
        cells.append(dict(id=f'serial-i{int(individual)}-s{int(shared)}',
                          individual=individual, shared=shared, population=1,
                          concurrency=1, seed=seed, kind='serial'))
    if config.get('community_population', 0) > 0:
        cells.append(dict(id='community-i1-s1', individual=True, shared=True,
                          population=config['community_population'],
                          concurrency=max(concurrency), seed=seed, kind='community'))
    return cells


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _restore(local: Path, durable: Path):
    pointer = durable / 'CURRENT'
    if not pointer.exists():
        return None, None
    name = json.loads(pointer.read_text())['generation']
    if not re.fullmatch(r'g-[0-9a-f]{32}', name):
        raise ValueError('invalid snapshot generation')
    generation = durable / 'generations' / name
    manifest = json.loads((generation / 'manifest.json').read_text())
    for filename, digest in manifest['files'].items():
        if Path(filename).name != filename or _digest(generation / filename) != digest:
            raise RuntimeError('snapshot integrity failure')
    # Uncheckpointed local work is discarded; only CURRENT is authoritative.
    stores_dir = local / 'stores'
    if stores_dir.exists():
        shutil.rmtree(stores_dir)
    stores_dir.mkdir(parents=True)
    for filename in manifest['files']:
        if filename.endswith('.sqlite'):
            shutil.copy2(generation / filename, stores_dir / filename)
    return json.loads((generation / 'state.json').read_text()), generation


def _checkpoint(state, local, durable, stores, dirty, previous):
    # Export holds this short lock while copying CURRENT and its complete generation.
    # Cell ownership remains separate and spans the entire experiment invocation.
    with (durable / 'snapshot.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _checkpoint_locked(state, local, durable, stores, dirty, previous)


def _checkpoint_locked(state, local, durable, stores, dirty, previous):
    generation = durable / 'generations' / ('g-' + uuid.uuid4().hex)
    generation.mkdir(parents=True)
    previous_manifest = json.loads((previous / 'manifest.json').read_text()) if previous else {'files': {}}
    files = {}
    for name, store in stores.items():
        filename = name + '.sqlite'
        destination = generation / filename
        if name not in dirty and filename in previous_manifest['files']:
            os.link(previous / filename, destination)
            files[filename] = previous_manifest['files'][filename]
        else:
            target = sqlite3.connect(destination)
            try:
                store.conn.backup(target)
            finally:
                target.close()
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
            files[filename] = _digest(destination)
    _atomic_json(generation / 'state.json', state)
    files['state.json'] = _digest(generation / 'state.json')
    _atomic_json(generation / 'manifest.json', {'version': 1, 'files': files})
    _atomic_json(durable / 'CURRENT', {'generation': generation.name})
    _atomic_json(durable / 'result.json', state)
    _atomic_json(local / 'result.json', state)
    # Two generations suffice for inspection; incomplete generations are ignored.
    for old in (durable / 'generations').iterdir():
        if old != generation and old != previous and old.name.startswith('g-'):
            shutil.rmtree(old)
    dirty.clear()
    return generation


def _shared_view(published, audience):
    from sharing import list_shares
    result = []
    for record in list_shares(published_storage=published, audience=audience):
        row = published.get_episode(record.memory_id)
        data = json.loads(row['content'])
        result.append(dict(data, share_id=record.share_id, audience=record.audience,
                           source_instance=record.source_instance, source_id=record.source_id,
                           content_digest=record.content_digest))
    return result[-32:]


def _private_view(store):
    rows = store.conn.execute(
        "SELECT content, context FROM episodes WHERE episode_type='private' ORDER BY rowid DESC LIMIT 8"
    ).fetchall()
    return [dict(content=r['content'], **json.loads(r['context'])) for r in reversed(rows)]


def _ancestry(packet):
    ancestry = {}
    for item in packet['individual_memory'] + packet['shared_memory']:
        parents = list(item.get('parent_shares', []))
        if 'share_id' in item:
            parents.append(dict(share_id=item['share_id'], author=item['author'],
                                source_ids=item['source_ids']))
        for parent in parents:
            ancestry[parent['share_id']] = parent
    return list(ancestry.values())


def _bound_packet(packet, limit):
    # Trim whole remembered entries so retained source ancestry stays truthful.
    while len(SYSTEM) + len(json.dumps(packet)) > limit:
        if packet['individual_memory']:
            packet['individual_memory'] = packet['individual_memory'][1:]
        elif packet['shared_memory']:
            packet['shared_memory'] = packet['shared_memory'][1:]
        else:
            raise ValueError('prompt ceiling too small for task and source packet')
    return packet


def _validate_output(raw):
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise ValueError('invalid model text')
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('answer'), str):
        raise ValueError('answer must be a string')
    if not isinstance(data.get('memory'), str) or not isinstance(data.get('publication'), dict):
        raise ValueError('memory and explicit publication required')
    if data['publication'].get('action') not in ('none', 'publish', 'withdraw'):
        raise ValueError('invalid publication action')
    return data


def _apply(data, packet, store, published, state, dirty, cell):
    from sharing import share, unshare, list_shares
    agent, turn = packet['agent_id'], packet['turn']
    visible = {s['id'] for s in packet['sources']}
    for item in packet['individual_memory'] + packet['shared_memory']:
        visible.update(item.get('source_ids', []))
    if data['memory']:
        store.add_episode(id=f'{agent}-t{turn}-private', session_id=agent,
                          content=data['memory'], episode_type='private',
                          context={'source_ids': sorted(visible), 'turn': turn, 'author': agent,
                                   'parent_shares': _ancestry(packet)})
        dirty.add(agent)
    publication = data['publication']
    action = publication['action']
    if action == 'none':
        return
    if not cell['shared']:
        # The factorial gate disables sharing even if a model requests it.
        state['publication_events'].append(dict(agent_id=agent, turn=turn, action='disabled'))
        return
    if action == 'withdraw':
        owned = {r.share_id for r in list_shares(published_storage=published, audience=packet['audience'])
                 if r.source_instance == f"{cell['id']}/{agent}"}
        if publication.get('share_id') not in owned:
            raise ValueError('withdrawal requires an owned active share')
        unshare(published_storage=published, share_id=publication['share_id'])
        state['publication_events'].append(dict(agent_id=agent, turn=turn, action=action,
                                                share_id=publication['share_id']))
    else:
        source_ids = publication.get('source_ids')
        if not isinstance(source_ids, list) or not source_ids or not all(isinstance(s, str) for s in source_ids):
            raise ValueError('publication requires source_ids')
        if not set(source_ids) <= visible:
            raise ValueError('publication cites an unexposed source')
        if publication.get('audience') != packet['audience']:
            raise ValueError('publication audience is not this cell')
        if not isinstance(publication.get('content'), str) or not publication['content'].strip():
            raise ValueError('publication content required')
        ancestry = [s for s in _ancestry(packet) if set(s['source_ids']) & set(source_ids)]
        content = dict(content=publication['content'], source_ids=source_ids, author=agent,
                       parent_shares=ancestry, turn=turn, synthetic=True)
        source_id = f'{agent}-t{turn}-publication'
        store.add_episode(id=source_id, session_id=agent, content=json.dumps(content),
                          episode_type='publication', context={'source_ids': source_ids})
        dirty.add(agent)
        record = share(source_storage=store, published_storage=published, source_id=source_id,
                       layer='episode', audience=packet['audience'],
                       reason=str(publication.get('reason', 'explicit model publication')),
                       source_instance=f"{cell['id']}/{agent}")
        state['publication_events'].append(dict(agent_id=agent, action=action,
                                                share_id=record.share_id, **content))
    dirty.add('published')


def run_cell(cell: dict, config: dict, local_dir: Path, durable_dir: Path,
             provider, *, stop_event=None) -> dict:
    """Run at most max_turns per agent; completed_turns is the aggregate count.

    The durable lock is nonblocking. Model calls must honor timeout_s; unfinished
    calls cannot mutate stores. Completed failures are audited and are not retried.
    Interrupted, uncommitted requests may be retried after resume.
    """
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,100}', cell['id']):
        raise ValueError('invalid cell id')
    for name, limit in [('population', 1024), ('concurrency', 128)]:
        if type(cell[name]) is not int or not 1 <= cell[name] <= limit:
            raise ValueError(f'invalid {name}')
    if config.get('data_mode', 'synthetic') != 'synthetic':
        raise ValueError('bootstrap supports only the bundled synthetic corpus')
    max_turns = int(config.get('max_turns', 12))
    if not 1 <= max_turns <= 1000:
        raise ValueError('invalid max_turns')
    budget = float(config.get('cell_seconds', 5400))
    request_timeout = float(config.get('request_timeout_s', 120))
    if not 0 < budget <= 86400 or not 0 < request_timeout <= 3600:
        raise ValueError('invalid deadline or request timeout')
    local, durable = Path(local_dir) / cell['id'], Path(durable_dir) / cell['id']
    if local.resolve() == durable.resolve():
        raise ValueError('local and durable directories must differ')
    local.mkdir(parents=True, exist_ok=True)
    durable.mkdir(parents=True, exist_ok=True)
    with (durable / 'owner.lock').open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"cell {cell['id']} already owned") from error
        return _run_owned(cell, config, local, durable, provider, stop_event,
                          max_turns, budget, request_timeout)


def _run_owned(cell, config, local, durable, provider, stop_event, max_turns, budget, request_timeout):
    from storage import Storage
    corpus_path = Path(__file__).with_name('corpus') / 'synthetic-engineering.json'
    corpus = json.loads(corpus_path.read_text())
    identity = dict(cell=cell, max_turns=max_turns, corpus_digest=_digest(corpus_path),
                    model=config.get('model'), model_revision=config.get('model_revision'),
                    max_output_tokens=config.get('max_output_tokens', 512))
    max_calls = int(config.get('max_calls_per_cell', 2048))
    max_prompt = int(config.get('max_prompt_chars', 32000))
    if not 1 <= max_calls <= 1_000_000 or not 1024 <= max_prompt <= 1_000_000:
        raise ValueError('invalid call or prompt ceiling')
    identity.update(max_calls_per_cell=max_calls, max_prompt_chars=max_prompt)
    state, previous = _restore(local, durable)
    if state is not None and state['identity'] != identity:
        raise ValueError('resume configuration differs from saved cell')
    if state is not None and state['status'] in ('complete', 'complete_with_errors'):
        _atomic_json(local / 'result.json', state)
        _atomic_json(durable / 'result.json', state)
        return state
    state = state or dict(id=cell['id'], status='running', identity=identity,
                          completed_turns=0, errors=[], usage=dict(input_tokens=0, output_tokens=0,
                          requests=0, missing_usage_requests=0, completed_requests=0), turns=[], publication_events=[],
                          revision_events=[], round_views={}, attempts=[], elapsed_s=0, synthetic=True, kind=cell['kind'],
                          corpus_id=corpus['id'], result_dir=str(durable),
                          request_count_semantics='Durably reserved calls; interrupted reservations may have reached provider. Token totals include only reported usage.')
    started = time.monotonic()
    prior_elapsed = state['elapsed_s']
    session_seconds = float(config.get('session_seconds', budget))
    if not 0 < session_seconds <= 86400:
        raise ValueError('invalid session_seconds')
    cell_remaining = max(0, budget - prior_elapsed)
    deadline = started + min(cell_remaining, session_seconds)
    deadline_scope = 'session' if session_seconds < cell_remaining else 'cell'
    (local / 'stores').mkdir(exist_ok=True)
    stores = {}
    dirty = set()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=cell['concurrency'])
    def get_store(name):
        if name not in stores:
            exists = (local / 'stores' / (name + '.sqlite')).exists()
            stores[name] = Storage(str(local / 'stores' / (name + '.sqlite')))
            if not exists:
                dirty.add(name)
        return stores[name]
    def save():
        nonlocal previous
        state['elapsed_s'] = prior_elapsed + time.monotonic() - started
        previous = _checkpoint(state, local, durable, stores, dirty, previous)
    try:
        # Include restored stores in every generation even if no new turn touches them.
        for path in (local / 'stores').glob('*.sqlite'):
            get_store(path.stem)
        published = get_store('published')
        for attempt in state['attempts']:
            if attempt['status'] in ('reserved', 'in_flight'):
                attempt['status'] = 'interrupted_unknown_outcome'
        completed = {(x['agent_id'], x['turn']) for x in state['turns']}
        audience = 'group:cell-' + hashlib.sha256(cell['id'].encode()).hexdigest()[:24]
        halted = False
        state['status'] = 'running'
        state.pop('deadline_scope', None)
        for turn in range(max_turns):
            if halted:
                break
            shared = state['round_views'].setdefault(str(turn),
                _shared_view(published, audience) if cell['shared'] else [])
            pending_agents = [i for i in range(cell['population']) if (f'agent-{i:04d}', turn) not in completed]
            for offset in range(0, len(pending_agents), cell['concurrency']):
                if (stop_event is not None and stop_event.is_set()) or time.monotonic() >= deadline or state['usage']['requests'] >= max_calls:
                    halted = True
                    break
                prepared = []
                for i in pending_agents[offset:offset + min(cell['concurrency'], max_calls - state['usage']['requests'])]:
                    agent = f'agent-{i:04d}'
                    store = get_store(agent)
                    sources = [s for s in corpus['sources'] if not s.get('denied')
                               and s['round'] == turn
                               and (cell['kind'] == 'serial' or s['cohort'] == i % 2)]
                    packet = dict(agent_id=agent, turn=turn, audience=audience, seed=cell['seed'],
                                  synthetic=True, corpus_id=corpus['id'], question=corpus['question'],
                                  sources=sources, individual_memory=_private_view(store) if cell['individual'] else [],
                                  shared_memory=shared)
                    packet = _bound_packet(packet, max_prompt)
                    attempt = dict(agent_id=agent, turn=turn, status='reserved', packet=packet)
                    state['attempts'].append(attempt)
                    state['usage']['requests'] += 1
                    state['usage']['missing_usage_requests'] += 1
                    prepared.append((packet, store, attempt))
                # Reserve the call budget durably before any external inference.
                save()
                batch = []
                for packet, store, attempt in prepared:
                    if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
                        attempt['status'] = 'not_sent'
                        state['usage']['requests'] -= 1
                        state['usage']['missing_usage_requests'] -= 1
                        halted = True
                        continue
                    attempt['status'] = 'in_flight'
                    timeout = min(request_timeout, max(0.001, deadline-time.monotonic()))
                    future = pool.submit(provider.generate, [{'role':'system','content':SYSTEM},
                                         {'role':'user','content':json.dumps(packet)}],
                                         max_tokens=config.get('max_output_tokens',512), timeout_s=timeout)
                    batch.append((future, packet, store, attempt))
                remaining = {f for f, _, _, _ in batch}
                while remaining and time.monotonic() < deadline and not (stop_event is not None and stop_event.is_set()):
                    _, remaining = concurrent.futures.wait(remaining, timeout=min(.1, max(0, deadline-time.monotonic())))
                for future, packet, store, attempt in batch:
                    if not future.done():
                        future.cancel()
                        attempt['status'] = 'interrupted_unknown_outcome'
                        halted = True
                        continue
                    record = dict(agent_id=packet['agent_id'], turn=turn, packet=packet,
                                  source_exposure=[s['id'] for s in packet['sources']], status='complete')
                    attempt['status'] = 'complete'
                    state['usage']['completed_requests'] += 1
                    try:
                        response = future.result()
                        record['response'] = response
                        missing = False
                        for key in ('input_tokens', 'output_tokens'):
                            value = response.get(key)
                            if type(value) is int and value >= 0:
                                state['usage'][key] += value
                            else:
                                missing = True
                        state['usage']['missing_usage_requests'] -= int(not missing)
                        data = _validate_output(response['text'])
                        record['decision'] = data
                        _apply(data, packet, store, published, state, dirty, cell)
                    except Exception as error:
                        record['status'] = 'error'
                        attempt['status'] = 'error'
                        record['error'] = f'{type(error).__name__}: {error}'
                        state['errors'].append(dict(agent_id=packet['agent_id'], turn=turn, error=record['error']))
                    for source in packet['sources']:
                        if source.get('supersedes'):
                            state['revision_events'].append(dict(agent_id=packet['agent_id'], turn=turn,
                                source_id=source['id'], supersedes=source['supersedes']))
                    state['turns'].append(record)
                    state['completed_turns'] += 1
                save()
                if halted:
                    break
        if state['completed_turns'] == cell['population'] * max_turns:
            state['status'] = 'complete_with_errors' if state['errors'] else 'complete'
        elif stop_event is not None and stop_event.is_set():
            state['status'] = 'interrupted'
        elif state['usage']['requests'] >= max_calls:
            state['status'] = 'call_budget'
        else:
            state['status'] = 'deadline'
            state['deadline_scope'] = deadline_scope
        state['failed_turns'] = sum(t['status'] == 'error' for t in state['turns'])
        state['successful_turns'] = state['completed_turns'] - state['failed_turns']
        state['agent_completed_turns'] = {f'agent-{i:04d}': sum(t['agent_id'] == f'agent-{i:04d}' for t in state['turns']) for i in range(cell['population'])}
        save()
        return state
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        for store in stores.values():
            store.close()
