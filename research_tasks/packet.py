"""Explicitly select one cached source and current question; omit live history."""
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from workbench.automation import ResearchInbox
from workbench.validation import normalize_item, normalize_source
from .storage import canonical, digest, read, write_once

FORMAT = 'superyak-research-task-v1'
QUESTION_FIELDS = {'id', 'kind', 'title', 'summary', 'status', 'facets'}
DOCUMENT_FIELDS = {'source', 'passages', 'coverage', 'coverage_note', 'retrieved_at', 'document_url', 'content_sha256', 'publication_types'}
PAPER_FIELDS = {'key', 'doi', 'provider_source', 'provider_id', 'title', 'publication_types', 'source'}


def _validate_document(document):
    if (not isinstance(document, dict) or set(document) - DOCUMENT_FIELDS
            or DOCUMENT_FIELDS - {'publication_types'} - set(document)):
        raise ValueError('Document fields are incomplete or unexpected')
    if normalize_source(document['source']) != document['source']:
        raise ValueError('Source metadata is not normalized')
    if document['coverage'] not in {'abstract_only', 'full_text_excerpt'}:
        raise ValueError('Unknown source coverage')
    for key in ('coverage_note', 'retrieved_at', 'document_url'):
        if not isinstance(document[key], str) or not document[key].strip():
            raise ValueError(f'Missing document {key}')
    datetime.fromisoformat(document['retrieved_at'].replace('Z', '+00:00'))
    url = urlsplit(document['document_url'])
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
        raise ValueError('Document locator must be an attributed HTTP URL')
    types = document.get('publication_types', [])
    if not isinstance(types, list) or len(types) > 100 or any(
            not isinstance(v, str) or not 1 <= len(v.strip()) <= 500 for v in types):
        raise ValueError('Invalid document publication types')
    passages = document['passages']
    if not isinstance(passages, list) or not 1 <= len(passages) <= 256:
        raise ValueError('Document needs bounded cached passages')
    ids = set()
    for passage in passages:
        if (not isinstance(passage, dict) or set(passage) != {'id', 'locator', 'text'}
                or any(not isinstance(v, str) or not v.strip() for v in passage.values())):
            raise ValueError('Passages require original text, unique ID and locator')
        if passage['id'] in ids:
            raise ValueError('Duplicate passage ID')
        ids.add(passage['id'])
    if sum(len(p['text']) for p in passages) > 18000:
        raise ValueError('Cached document exceeds Atlas passage limit')
    if hashlib.sha256(canonical(passages)).hexdigest() != document['content_sha256']:
        raise ValueError('Cached passage hash mismatch')


def validate_task(task):
    required = {'format', 'task_id', 'packet_sha256', 'question', 'paper', 'document', 'document_sha256', 'provenance'}
    if not isinstance(task, dict) or set(task) != required or task['format'] != FORMAT:
        raise ValueError('Unsupported task packet')
    payload = {key: value for key, value in task.items() if key not in {'task_id', 'packet_sha256'}}
    sha = digest(payload)
    if task['packet_sha256'] != sha or task['task_id'] != 'task-' + sha:
        raise ValueError('Task packet hash mismatch')
    question = task['question']
    if not isinstance(question, dict) or set(question) != QUESTION_FIELDS:
        raise ValueError('Unexpected selected question fields')
    normalized = normalize_item(question)
    if normalized['kind'] != 'question' or normalized['status'] != 'proposed':
        raise ValueError('Choose an active research question')
    _validate_document(task['document'])
    if digest(task['document']) != task['document_sha256']:
        raise ValueError('Full document hash mismatch')
    paper = task['paper']
    if not isinstance(paper, dict) or set(paper) - PAPER_FIELDS or not isinstance(paper.get('key'), str) or not paper['key']:
        raise ValueError('Invalid selected paper identity')
    if paper.get('source') != task['document']['source']:
        raise ValueError('Paper and retrieved source identities differ')
    if paper.get('publication_types', []) != task['document'].get('publication_types', []):
        raise ValueError('Paper and document publication types differ')
    provenance = task['provenance']
    if (not isinstance(provenance, dict) or set(provenance) != {'question_id', 'job_id', 'job_sha256', 'historical_prompt_replay', 'source_question_status'}
            or provenance['source_question_status'] not in ('proposed', 'source_reported', 'reviewed')
            or provenance['question_id'] != question['id'] or provenance['historical_prompt_replay'] is not False
            or not isinstance(provenance['job_id'], str)
            or not re.fullmatch('[a-f0-9]{64}', provenance['job_id'])
            or not isinstance(provenance['job_sha256'], str)
            or not re.fullmatch('[a-f0-9]{64}', provenance['job_sha256'])):
        raise ValueError('Invalid task selection provenance')
    return task


def load_task(path):
    return validate_task(read(path))


def export_task(project, question_id, job_id, output):
    project, output = Path(project), Path(output)
    if project.is_symlink() or output.is_symlink():
        raise ValueError('Project and packet cannot be symlinks')
    project = project.resolve(strict=True)
    if output.resolve().is_relative_to(project):
        raise ValueError('Export outside the selected live project')
    if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{64}', job_id):
        raise ValueError('Choose an exact paper job ID')
    job_path = project / '.atlas/research/jobs' / (job_id + '.json')
    if any(p.is_symlink() for p in (job_path, *job_path.parents)):
        raise ValueError('Cached source paths cannot contain symlinks')
    job = read(job_path)
    if job.get('id') != job_id or job.get('question_id') != question_id or job.get('status') != 'recorded':
        raise ValueError('Choose a completed recorded job for this question')
    snapshot = ResearchInbox(project).snapshot()
    selected = [v for v in snapshot['bundle']['items'] if v['id'] == question_id]
    if len(selected) != 1 or not any(question_id in ids for ids in snapshot['views'].values()):
        raise ValueError('Choose a question from the configured views')
    if selected[0]['kind'] != 'question' or selected[0]['status'] == 'withdrawn':
        raise ValueError('Choose an active research question')
    question = {key: deepcopy(selected[0][key]) for key in QUESTION_FIELDS}
    question['status'] = 'proposed'
    if not isinstance(job.get('document'), dict) or not isinstance(job.get('paper'), dict):
        raise ValueError('Job has no cached document and paper')
    document = {key: deepcopy(job['document'][key]) for key in DOCUMENT_FIELDS if key in job['document']}
    _validate_document(document)
    if document['coverage'] == 'abstract_only':
        # Search URLs and transport exceptions may contain private planning text.
        # Retain the public source identity and exact cached passage hashes.
        document['document_url'] = document['source']['url']
        document['coverage_note'] = 'Only the cached provider abstract is supplied; no full text is included.'
    paper = {key: deepcopy(value) for key, value in job['paper'].items() if key in PAPER_FIELDS}
    payload = {'format': FORMAT, 'question': question, 'document': document, 'paper': paper,
               'document_sha256': digest(document), 'provenance': {'question_id': question_id,
               'job_id': job_id, 'job_sha256': digest(job), 'historical_prompt_replay': False,
               'source_question_status': selected[0]['status']}}
    sha = digest(payload)
    task = validate_task(payload | {'task_id': 'task-' + sha, 'packet_sha256': sha})
    write_once(output.resolve(), task)
    return task
