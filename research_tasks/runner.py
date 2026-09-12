"""Durable extraction and independent source-support calls for a frozen task."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import time
import uuid

from workbench.automation import ResearchInbox
from workbench.research_runner import prepare_draft, validate_analysis
from workbench.research_review import REVIEW_REVISION, review_input_digest, validate_review
from . import ROOT
from .packet import load_task
from .storage import IntegrityError, digest, read, read_checked, save_checked, write_once


class TaskError(RuntimeError):
    """Execution cannot safely continue under the current run identity."""


class CallFailed(TaskError):
    pass


def code_fingerprint():
    files = set()
    for pattern in ('research_tasks/*.py', 'atlas/workbench/*.py', 'atlas/workbench/static/*', 'engram/*.py'):
        files.update(ROOT.glob(pattern))
    files.update(ROOT / p for p in ('deploy/stampede/provider.py', 'engram/uv.lock', 'atlas/uv.lock'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.is_file()}


@contextmanager
def _owner(output):
    if output.is_symlink():
        raise ValueError('Run output cannot be a symlink')
    for p in (output, *output.parents):
        if (p / 'workbench/data/lighthouse-automation.json').exists():
            raise ValueError('Run outside an existing Atlas research project')
    if output.exists() and not (output / 'manifest.json').exists() and any(output.iterdir()):
        raise ValueError('Run output already contains unrelated files')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(p.is_symlink() for p in output.rglob('*')):
        raise ValueError('Run artifacts cannot contain symlinks')
    fd = os.open(output / 'run.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TaskError('This task run already has an owner') from error
        yield
    finally:
        os.close(fd)


def _seed(output, task):
    project = output / 'project'
    data = project / 'workbench/data'
    write_once(data / 'task.json', {'schema_version': 1, 'title': task['question']['title'],
        'sources': [], 'items': [task['question']], 'relations': []})
    write_once(data / 'lighthouse-automation.json', {'version': 1, 'bundle': 'workbench/data/task.json',
        'views': {'prediction': 'workbench/data/view.json'}})
    write_once(data / 'view.json', {'issuer': 'urn:superyak:portable:' + task['task_id'],
        'name': 'Portable research task', 'origin': 'urn:superyak:research-task',
        'context': {'id': 'research/portable-task', 'path': ['research', 'portable-task']},
        'item_ids': [task['question']['id']], 'issued_at': '2026-09-12T00:00:00Z', 'rules': []})
    return ResearchInbox(project)


def _call(output, stage, request, invoke, model):
    started = output / 'calls' / (stage + '.started.json')
    response = output / 'calls' / (stage + '.response.json')
    request_hash = digest(request)
    if response.exists():
        start = read_checked(started)
        saved = read_checked(response)
        if start['request_sha256'] != request_hash or saved['request_sha256'] != request_hash:
            raise IntegrityError('Saved call does not match the pinned task inputs')
    else:
        if started.exists():
            read_checked(started)
            raise TaskError(f'{stage} has an unfinished request with uncertain remote outcome; inspect it and use a new output for an explicit new attempt')
        save_checked(started, {'stage': stage, 'request': request, 'request_sha256': request_hash,
                              'started_at': datetime.now(timezone.utc).isoformat()})
        began = time.monotonic()
        model.last_response = None
        model.last_request = None
        model.last_response_body = None
        result, error = None, None
        try:
            result = invoke()
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
        saved = {'stage': stage, 'request_sha256': request_hash, 'result': result, 'error': error,
                 'raw_response': getattr(model, 'last_response', None),
                 'dispatched_request': getattr(model, 'last_request', None),
                 'raw_body': getattr(model, 'last_response_body', None),
                 'elapsed_seconds': time.monotonic() - began}
        save_checked(response, saved)
    if saved['error']:
        raise CallFailed(saved['error'])
    result = saved['result']
    if not isinstance(result, dict) or result.get('model') != model.model:
        raise CallFailed('Response does not identify the selected model')
    return result


def _artifacts(output):
    # Bind the complete isolated Atlas publication as well as the call journal.
    paths = (p for p in output.rglob('*') if p.is_file()
             and p != output / 'result.json' and p != output / 'run.lock')
    return {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def _finish(output, report):
    report = report | {'artifacts': _artifacts(output)}
    save_checked(output / 'result.json', report)
    return report


def run_task(packet_path, output, model, *, config):
    task = load_task(packet_path)
    if not isinstance(config, dict) or config.get('model') != model.model:
        raise ValueError('Run configuration and model identity differ')
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Run output cannot be a symlink')
    output = output.resolve()
    expected = {'version': 1, 'packet_sha256': task['packet_sha256'], 'config': config, 'code': code_fingerprint()}
    with _owner(output):
        manifest = output / 'manifest.json'
        if manifest.exists():
            if read_checked(manifest) != expected:
                raise ValueError('Run pin changed: task, configuration or implementation differs')
        else:
            save_checked(manifest, expected)
        write_once(output / 'task.json', task)
        if not (output / 'identity.json').exists():
            save_checked(output / 'identity.json', {'session_id': 'portable-task:' + str(uuid.uuid4())})
        identity = read_checked(output / 'identity.json')
        if (output / 'result.json').exists():
            result = read_checked(output / 'result.json')
            if result['artifacts'] != _artifacts(output):
                raise ValueError('Completed task artifact hashes changed')
            for p in (output / 'calls').glob('*.json'):
                read_checked(p)
            return result
        inbox = _seed(output, task)
        question, document = task['question'], task['document']
        report = {'task_id': task['task_id'], 'model': model.model,
                  'scientific_status': 'proposed', 'assessment': 'Automated source check; not independent scientific validation'}
        try:
            extraction = _call(output, 'extract', {'question': question, 'document': document, 'context': []},
                lambda: model.extract(question, document, []), model)
            extracted = validate_analysis(extraction, document)
            if extracted is None:
                return _finish(output, report | {'status': 'irrelevant'})
            selected = extraction.get('context_manifest', {}).get('selected_passage_ids')
            if selected is not None and extracted[0]['passage_id'] not in selected:
                raise ValueError('Quoted evidence was not in the model context')
            review = _call(output, 'review', {'question': question, 'document': document, 'candidate': extracted[0]},
                lambda: model.review(question, document, extracted[0]), model)
            assessment = validate_review(review, document)
            selected = review.get('context_manifest', {}).get('selected_passage_ids')
            if selected is not None and any(e['passage_id'] not in selected for e in assessment['evidence']):
                raise ValueError('Review evidence was not in the model context')
            if assessment['verdict'] != 'supported':
                return _finish(output, report | {'status': 'held', 'source_review': assessment})
            if code_fingerprint() != expected['code']:
                raise ValueError('Implementation changed during this task')
            job = {'id': task['task_id'], 'paper': task['paper'], 'document': document, 'extraction': extraction,
                   'source_review': {'revision': REVIEW_REVISION, 'result': review,
                       'input_digest': review_input_digest(model.model, question, document, extracted[0])}}
            draft = prepare_draft(job, question, inbox.snapshot(), extracted)
            save_checked(output / 'draft.json', draft)
            receipt = inbox.record(draft, identity['session_id'])
            if receipt['publication_status'] != 'current':
                raise TaskError('Finding saved but publication is pending; replay to recover')
            return _finish(output, report | {'status': 'recorded', 'receipt': receipt})
        except CallFailed as error:
            return _finish(output, report | {'status': 'failed', 'error': str(error)})
        except IntegrityError:
            raise
        except ValueError as error:
            return _finish(output, report | {'status': 'invalid', 'error': str(error)})
