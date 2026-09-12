"""Durable local research cells; Atlas is a boundary, not a cluster dependency."""
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import time
import uuid

from engram.storage import Storage
from engram.sharing import list_shares, share

CONDITIONS = [dict(id=f'i{int(i)}-s{int(s)}', individual=i, shared=s, kind='factorial')
              for i in (False, True) for s in (False, True)]
COMMUNITY = dict(id='community', individual=True, shared=True, kind='community')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('wb') as output:
        output.write(encoded(value))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read(path):
    return json.loads(path.read_bytes())


def _pin(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f'Run configuration changed: {path}')
    else:
        save(path, value)


def pin_implementation(root, source):
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(source.glob('*.py'))}
    path = root / 'implementation.json'
    if not path.exists() and any((root / 'cells').glob('*/calls/*/attempt-*.json')):
        raise ValueError('Existing run predates implementation pinning; use a new output directory')
    _pin(path, {'version': 1, 'files': files})


def _call(root, turn, stage, function, arguments, *, retry_interrupted):
    """Returned calls are reusable; uncertain attempts are never silently repeated."""
    directory = root / 'calls' / f'{turn}-{stage}'
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / 'result.json'
    request = dict(stage=stage, inputs_sha256=digest(arguments))
    _pin(directory / 'request.json', request)
    attempts = sorted(directory.glob('attempt-*.json'))
    if result_path.exists():
        saved = read(result_path)
        latest = read(attempts[-1])
        if latest['status'] != 'returned':
            save(attempts[-1], latest | {'status': 'returned', 'elapsed_seconds': saved['elapsed_seconds']})
        return saved['result']
    if attempts and not retry_interrupted:
        raise RuntimeError(f'{turn}/{stage} has a failed or interrupted call; inspect its audit, then use --retry-interrupted')
    attempt_path = directory / f'attempt-{len(attempts):03d}.json'
    attempt = dict(started_at=time.time(), status='started')
    save(attempt_path, attempt)
    try:
        result = function(*arguments)
    except Exception as error:
        attempt.update(status='failed', error=f'{type(error).__name__}: {error}', elapsed_seconds=time.time() - attempt['started_at'])
        if hasattr(error, 'result'):
            attempt['returned_result'] = error.result
        save(attempt_path, attempt)
        raise
    save(result_path, dict(result=result, elapsed_seconds=time.time() - attempt['started_at']))
    attempt.update(status='returned', elapsed_seconds=time.time() - attempt['started_at'])
    save(attempt_path, attempt)
    return result


def _put(store, identity, content, session, kind, context):
    previous = store.get_episode(identity)
    value = encoded(content).decode()
    if previous is None:
        store.add_episode(id=identity, session_id=None, content=value, episode_type=kind,
                          context=context | {'logical_session': session})
    elif previous['content'] != value:
        raise ValueError('A saved memory differs from its checkpointed model result')


def _context(private, published, agent, round_index, individual, shared, audience):
    result = []
    if individual:
        for row in private.conn.execute("SELECT * FROM episodes WHERE episode_type = 'research-private' ORDER BY id"):
            if json.loads(row['context'])['round'] < round_index:
                result.append(json.loads(row['content']))
    if shared:
        for publication in list_shares(published_storage=published, audience=audience):
            value = json.loads(published.get_episode(publication.memory_id)['content'])
            if value['author'] != agent and value['round'] < round_index:
                result.append(value['envelope'])
    return result


def run_cell(root: Path, condition: dict, prepared: dict, documents: list[dict], model,
             *, rounds=2, record=None, fork=None, retry_interrupted=False, progress=None):
    """Two agents swap fixed documents, recalling only earlier completed rounds."""
    if len(documents) != 2 or type(rounds) is not int or not 1 <= rounds <= 20:
        raise ValueError('The POC requires two documents and 1–20 rounds')
    if record is None or fork is None:
        from .atlas_bridge import record_finding, fork_project
        record, fork = record or record_finding, fork or fork_project
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'owner.lock').open('a') as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('This research cell already has an owner') from error
        configuration = dict(version=1, condition=condition, question=prepared['question'],
                             documents_sha256=digest(documents), model=getattr(model, 'model', 'test-boundary'))
        _pin(root / 'configuration.json', configuration)
        identity_path = root / 'identity.json'
        if not identity_path.exists():
            # Persist the original identity so copying a completed run preserves its
            # authors and audience. Existing development runs use these same values.
            save(identity_path, {'audience': 'group:poc-' + digest(str(root))[:16],
                                 'session_prefix': 'atlas-poc:' + digest(str(root))[:12]})
        identity = read(identity_path)
        project = fork(Path(prepared['seed_project']), root / 'atlas-project')
        published = Storage(str(root / 'published.db'))
        private = [Storage(str(root / f'agent-{i}.db')) for i in range(2)]
        audience = identity['audience']
        try:
            for round_index in range(rounds):
                # Every agent's view is frozen before this round can publish anything.
                contexts = [_context(private[i], published, f'agent-{i}', round_index,
                                     condition['individual'], condition['shared'], audience) for i in range(2)]
                for agent_index in range(2):
                    agent = f'agent-{agent_index}'
                    turn = f'r{round_index:03d}-a{agent_index}'
                    path = root / 'turns' / f'{turn}.json'
                    if path.exists():
                        continue
                    entry = documents[(round_index + agent_index) % 2]
                    context = contexts[agent_index]
                    _pin(root / 'inputs' / f'{turn}.json', dict(document_sha256=digest(entry), context=context))
                    if progress:
                        progress(f'{condition["id"]} {turn}: extraction')
                    generated = _call(root, turn, 'extract', model.generate,
                                      [prepared['question'], entry['document'], context], retry_interrupted=retry_interrupted)
                    extraction = generated['extraction']
                    candidate = extraction['analysis']
                    review = None
                    if candidate['relevant']:
                        if progress:
                            progress(f'{condition["id"]} {turn}: source review')
                        review = _call(root, turn, 'review', model.review,
                                       [prepared['question'], entry['document'], candidate], retry_interrupted=retry_interrupted)
                    supported = bool(review and review['analysis']['verdict'] == 'supported')
                    session = f'{identity["session_prefix"]}:{agent}'
                    if condition['individual']:
                        note = dict(record=dict(id=f'private:{agent}:{round_index}', kind='note',
                            title='Private tentative reflection', summary=generated['private_note'],
                            status='unreviewed', scope='Background only, never independent evidence'))
                        _put(private[agent_index], turn + '-private', note, session, 'research-private', {'round': round_index})
                    receipt, publication = None, None
                    if condition['shared'] and generated['publish'] and supported:
                        # Record first: a saved but pending Atlas publication is recoverable by its stable key.
                        receipt = record(project, question=prepared['question'], paper=entry['paper'],
                                         document=entry['document'], extraction=extraction, review=review,
                                         session_id=session, idempotency_key=turn)
                        public_record = dict(id=f'shared:{agent}:{round_index}', kind='claim', status='proposed',
                                             **{key: candidate[key] for key in ('title', 'summary', 'scope', 'limitations')})
                        envelope = dict(record=public_record, sources=[entry['document']['source']],
                                        attribution=dict(author=agent, source_sha256=entry['document']['content_sha256'],
                                            passage_id=candidate['passage_id'], quote=candidate['quote'],
                                            review='supported by same-model source check; remains proposed'))
                        public = dict(author=agent, round=round_index, envelope=envelope)
                        _put(private[agent_index], turn + '-publication', public, session, 'research-publication', {'round': round_index})
                        publication = share(source_storage=private[agent_index], published_storage=published,
                            source_id=turn + '-publication', layer='episode', audience=audience,
                            reason='Explicit model choice with supported source-only review', source_instance=session).share_id
                    selected = extraction.get('context_manifest', {}).get('selected_record_ids', [])
                    save(path, dict(turn=turn, round=round_index, agent=agent, source=entry['document']['source'],
                        coverage=entry['document']['coverage'], source_sha256=entry['document']['content_sha256'],
                        supplied_memory_ids=[c['record']['id'] for c in context], admitted_memory_ids=selected,
                        candidate=candidate, publish_requested=generated['publish'], supported=supported,
                        review=review, receipt=receipt, share_id=publication))
            result = cell_summary(root)
            save(root / 'summary.json', result)
            return result
        finally:
            for storage in private + [published]:
                storage.close()


def cell_summary(root):
    config = read(root / 'configuration.json')
    turns = [read(path) for path in sorted((root / 'turns').glob('*.json'))]
    for turn in turns:
        extraction = read(root / 'calls' / f'{turn["turn"]}-extract' / 'result.json')['result']['extraction']
        turn['source_context_manifest'] = extraction.get('context_manifest', {})
    attempts, responses, metrics = [], [], []
    uncertain = 0
    for directory in sorted((root / 'calls').glob('*')):
        entries = [read(p) for p in sorted(directory.glob('attempt-*.json'))]
        result_path = directory / 'result.json'
        returned = read(result_path) if result_path.exists() else None
        if returned:
            responses.append(returned)
        for index, attempt in enumerate(entries):
            known_returned = bool(returned and index == len(entries) - 1)
            uncertain += not known_returned
            value = returned['result'] if known_returned else attempt.get('returned_result', {})
            normalized = value.get('extraction', value)
            metrics.append(normalized.get('metrics', normalized.get('response', {})))
        attempts.extend(entries)
    return dict(condition=config['condition'], completed_turns=len(turns), calls=len(attempts),
                failed_or_interrupted_calls=uncertain,
                supported=sum(t['supported'] for t in turns), shares=sum(bool(t['share_id']) for t in turns),
                supplied_memories=sum(len(t['supplied_memory_ids']) for t in turns),
                admitted_memories=sum(len(t['admitted_memory_ids']) for t in turns),
                model_reported_prompt_tokens=sum(m.get('prompt_eval_count', 0) for m in metrics),
                model_reported_output_tokens=sum(m.get('eval_count', 0) for m in metrics),
                token_metrics_complete=bool(metrics) and all('prompt_eval_count' in m and 'eval_count' in m for m in metrics),
                summed_call_seconds=round(sum(r['elapsed_seconds'] for r in responses), 3),
                path=str(root), turns=turns)


def write_report(root: Path):
    """Readable audit of observations; no invented quality or causal effect score."""
    cells = [cell_summary(p.parent) for p in sorted((root / 'cells').glob('*/configuration.json'))]
    save(root / 'results.json', {'cells': cells})
    lines = ['# Atlas + Superyak local research POC', '',
             'Two logical researchers per cell; fixed public documents and question. Four memory conditions and a separate continuing community. Source review uses the same local model in a fresh request. Findings remain proposed. This is a mechanism test, not an estimate of research benefit or Stampede capacity.', '',
             '| Cell | Turns | Calls | Supported | Shared | Memory supplied/admitted | Errors/uncertain |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for c in cells:
        lines.append(f'| {c["condition"]["id"]} | {c["completed_turns"]} | {c["calls"]} | {c["supported"]} | {c["shares"]} | {c["supplied_memories"]}/{c["admitted_memories"]} | {c["failed_or_interrupted_calls"]} |')
    lines.extend(['', 'Raw requests are identified by exact input/context hashes; returned outputs and model-reported metrics are saved under each cell. Private notes are retained in owner stores and local operator audit files, never copied into shared context.', ''])
    for c in cells:
        lines.extend([f'## {c["condition"]["id"]}', '', f'Prompt/output tokens reported: {c["model_reported_prompt_tokens"]}/{c["model_reported_output_tokens"]}; token fields complete: {c["token_metrics_complete"]}. Sum of returned call times: {c["summed_call_seconds"]} seconds.', ''])
        for turn in c['turns']:
            candidate = turn['candidate']
            lines.extend([f'### {turn["turn"]}: {candidate.get("title", "No relevant finding")}', '',
                candidate.get('summary', ''), '', f'Scope: {candidate.get("scope", "")}', '',
                f'Limitations: {candidate.get("limitations", "")}', '',
                f'Source: [{turn["source"].get("title", turn["source"]["id"])}]({turn["source"]["url"]}); coverage: {turn["coverage"]}.', '',
                f'Source check: {"supported" if turn["supported"] else "not supported"}. Explicit publication choice: {turn["publish_requested"]}. Shared: {bool(turn["share_id"])}.', '',
                f'Memory supplied: {turn["supplied_memory_ids"]}; admitted: {turn["admitted_memory_ids"]}.', ''])
            lines.extend([f'Source passages admitted: {turn["source_context_manifest"].get("selected_passage_ids", [])}.', ''])
    markdown = '\n'.join(lines)
    (root / 'report.md').write_text(markdown)
    (root / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Atlas research POC</title><style>body{max-width:1100px;margin:40px auto;font:16px/1.5 system-ui;padding:0 20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><pre>' + html.escape(markdown) + '</pre>')
    return cells


def run_worker(options, condition):
    from .atlas_bridge import prepare_atlas, fetch_documents, AtlasModel
    root = Path(options['output'])
    prepared = prepare_atlas(Path(options['atlas_source']), root)
    documents = fetch_documents(root)
    model = AtlasModel(options['model'], timeout=options['timeout'])
    model.check()
    try:
        return run_cell(root / 'cells' / condition['id'], condition, prepared, documents, model,
                        rounds=options['community_rounds'] if condition['kind'] == 'community' else options['rounds'],
                        retry_interrupted=options['retry_interrupted'], progress=lambda message: print(message, flush=True))
    except Exception as error:
        # Atlas validation exceptions carry extra fields and cannot cross a process
        # boundary safely. The complete returned result is already in the call audit.
        raise RuntimeError(f'{type(error).__name__}: {error}') from None
