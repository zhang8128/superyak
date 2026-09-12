"""Self-contained, escaped HTML views and protected atomic file publication."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

from .validation import EXPLICIT_QUESTION_PREDICATES, WorkbenchError, normalize_bundle


DOCUMENT_MARKER = '<!doctype html>\n<!-- atlas-workbench:document:v1 -->\n'
STATIC = Path(__file__).with_name('static')
KIND_ORDER = {'question': 0, 'approach': 1, 'claim': 2, 'experiment': 3}
COUNT_LABELS = {
    'question': ('question', 'questions'), 'approach': ('approach', 'approaches'),
    'claim': ('claim', 'claims'), 'experiment': ('experiment', 'experiments'),
    'source': ('source', 'sources'), 'record': ('record', 'records'),
}


def _count_label(count, kind):
    singular, plural = COUNT_LABELS[kind]
    return f'{count} {singular if count == 1 else plural}'


def _text(value):
    return escape(str(value), quote=True)


def _badge(record):
    status = record['status']
    return f'<span class="badge {status}">{_text(status.replace("_", "-"))}</span>'


def _link(record, label=None):
    return f'<a href="#record={quote(record["id"], safe="")}" data-open="{_text(record["id"])}">{_text(label or record["title"])}</a>'


def _mapping(values, css='scope'):
    if not values:
        return '<p class="muted">None recorded.</p>'
    pairs = ''.join(f'<dt>{_text(key.replace("_", " "))}</dt><dd>{_text(value)}</dd>' for key, value in values.items())
    return f'<dl class="{css}">{pairs}</dl>'


def _evidence(record, sources):
    if not record['evidence']:
        return '<p class="muted">No direct source evidence recorded. Follow the connected claims below.</p>'
    entries = []
    for entry in record['evidence']:
        source = sources[entry['source_id']]
        entries.append(
            '<li class="evidence-entry">'
            f'<a href="{_text(source["url"])}" target="_blank" rel="noopener noreferrer">{_text(source["title"])} ↗</a>'
            f'<p class="locator"><strong>Locator:</strong> {_text(entry["locator"])}</p>'
            f'<p>{_text(entry["note"])}</p><details><summary>Citation · {_text(source["year"])}</summary>'
            f'<p>{_text(source["citation"])}</p></details></li>'
        )
    return '<ul class="evidence-list">' + ''.join(entries) + '</ul>'


def _history(record, history):
    entries = [event for event in history if event.get('record_id') == record['id']]
    reviewer = ''
    if record['reviewed_by']:
        reviewer = f'<p>Named local assessment: {_text(record["reviewed_by"])} · {_text(record["reviewed_at"])}</p>'
    if not entries:
        return reviewer + '<p class="muted">No local status changes recorded.</p>'
    rows = ''.join(
        '<li>'
        f'<strong>{_text(event.get("from_status", ""))} → {_text(event.get("to_status", ""))}</strong>'
        f'<p>{_text(event.get("reason", ""))}</p>'
        f'<p class="muted">{_text(event.get("actor", ""))} · {_text(event.get("timestamp", ""))}</p></li>'
        for event in entries
    )
    return reviewer + '<ol class="history">' + rows + '</ol>'


def _relation(relation, items, sources, history):
    answer = ''
    if relation['predicate'] in EXPLICIT_QUESTION_PREDICATES:
        answer = _mapping({label: relation['context'][key]
                           for key, label in (('answer_scope', 'Answer scope'), ('remaining', 'Remaining uncertainty'))
                           if relation['context'].get(key)})
    return (
        '<li class="relation">'
        f'<div class="relation-heading">{_badge(relation)} <span class="predicate">{_text(relation["predicate"].replace("_", " "))}</span></div>'
        f'<p>{_link(items[relation["subject"]])} → {_link(items[relation["object"]])}</p>'
        f'<p>{_text(relation["rationale"]) or "No rationale recorded."}</p>'
        f'{answer}'
        '<details><summary>Relation scope, evidence & history</summary>'
        f'{_mapping(relation["context"])}{_evidence(relation, sources)}{_history(relation, history)}'
        f'<p class="record-id">{_text(relation["id"])}</p></details></li>'
    )


def _detail(record, items, sources, relations, history, selected):
    related = []
    for direction, key in [('Outgoing', 'subject'), ('Incoming', 'object')]:
        matches = [relation for relation in relations if relation[key] == record['id']]
        body = '<ul class="relation-list">' + ''.join(_relation(r, items, sources, history) for r in matches) + '</ul>' if matches else '<p class="muted">None recorded.</p>'
        related.append(f'<h4>{direction}</h4>{body}')
    facets = {key: ', '.join(values) for key, values in record['facets'].items()}
    attribution = 'Publication attribution; not independently replicated here.' if record['status'] == 'source_reported' else 'A proposed question, interpretation or study; not an established result.'
    if record['status'] == 'withdrawn':
        attribution = 'Withdrawn from active use. Evidence and history remain inspectable.'
    elif record['status'] == 'reviewed':
        attribution = 'An explicitly named local assessment; reviewer credentials are not verified by this software.'
    return (
        f'<article class="record-detail" data-record-id="{_text(record["id"])}"{ "" if selected else " hidden"}>'
        f'<div class="eyebrow">{_text(record["kind"])} · {_badge(record)}</div>'
        f'<h2 tabindex="-1">{_text(record["title"])}</h2><p class="attribution">{attribution}</p>'
        f'<p class="summary">{_text(record["summary"])}</p>'
        f'<h3>Scope & limitations</h3>{_mapping(record["context"])}'
        f'<h3>Source evidence</h3>{_evidence(record, sources)}'
        f'<h3>Connected records</h3>{"".join(related)}'
        f'<h3>Facets</h3>{_mapping(facets, "facets")}'
        f'<h3>Review & withdrawal history</h3>{_history(record, history)}'
        f'<details><summary>Identity & provenance</summary><p class="record-id">{_text(record["id"])}</p>{_mapping(record["provenance"])}</details>'
        '</article>'
    )


def _questions(records, items, relations):
    cards = []
    questions = [record for record in records if record['kind'] == 'question']
    for index, record in enumerate(questions[:2]):
        approaches = [items[r['subject']] for r in relations if r['object'] == record['id'] and r['predicate'] == 'addresses' and r['status'] != 'withdrawn' and items[r['subject']]['status'] != 'withdrawn']
        experiments = [items[r['subject']] for r in relations if r['object'] == record['id'] and r['predicate'] == 'tests' and r['status'] != 'withdrawn' and items[r['subject']]['status'] != 'withdrawn']
        links = '<ul>' + ''.join(f'<li>{_link(a)}</li>' for a in approaches) + '</ul>' if approaches else '<p class="muted">No connected approaches yet.</p>'
        next_test = ''.join(f'<p class="next-test"><span>Connected test</span>{_link(e)} {_badge(e)}</p>' for e in experiments)
        cards.append(f'<article class="question-card"><div class="eyebrow">Question {index + 1:02d} · {_badge(record)}</div><h2>{_link(record)}</h2><p>{_text(record["summary"])}</p><h3>Connected approaches</h3>{links}{next_test}</article>')
    preview_note = (
        f'<p class="preview-note">Showing 2 of {len(questions)} questions, ordered by ID. '
        '<a class="browse-all" href="#workspace">Browse all records ↓</a></p>'
        if len(questions) > 2 else ''
    )
    return preview_note + (''.join(cards) or '<p class="muted">No questions in this collection. Browse the records below or import a question.</p>')


def _filters(records):
    axes = {}
    for record in records:
        for axis, values in record['facets'].items():
            axes.setdefault(axis, set()).update(values)
    selects = []
    for index, (axis, values) in enumerate(sorted(axes.items())):
        options = ''.join(f'<option value="{_text(value)}">{_text(value)}</option>' for value in sorted(values))
        selects.append(f'<div class="control"><label for="facet-{index}">{_text(axis)}</label><select id="facet-{index}" data-facet="{_text(axis)}"><option value="">All</option>{options}</select></div>')
    return ''.join(selects)


def render_bundle(bundle: dict) -> str:
    """Validate a portable bundle and render it without network or runtime assets."""
    data = normalize_bundle(bundle)
    history = bundle.get('history', [])
    if any(not isinstance(event, dict) for event in history):
        raise WorkbenchError('render history entries must be objects')
    data['history'] = history
    records = sorted(data['items'], key=lambda record: (KIND_ORDER[record['kind']], record['id']))
    items = {record['id']: record for record in records}
    sources = {source['id']: source for source in data['sources']}
    relations = data['relations']
    counts = Counter(record['kind'] for record in records)
    count_text = ' · '.join(_count_label(counts[kind], kind) for kind in KIND_ORDER) + f' · {_count_label(len(sources), "source")}'
    selected = records[0]['id'] if records else None
    record_rows = []
    for record in records:
        current = ' aria-current="true"' if record['id'] == selected else ''
        record_rows.append(
            f'<li data-list-id="{_text(record["id"])}"><a class="record-link" href="#record={quote(record["id"], safe="")}" data-open="{_text(record["id"])}"{current}>'
            f'<span class="list-meta">{_text(record["kind"])} {_badge(record)}</span><span>{_text(record["title"])}</span></a></li>'
        )
    eligible = [r for r in relations if r['predicate'] in {'requires', 'enables'} and r['status'] == 'reviewed' and items[r['subject']]['status'] != 'withdrawn' and items[r['object']]['status'] != 'withdrawn']
    dependencies = '<ul class="relation-list">' + ''.join(_relation(r, items, sources, history) for r in eligible) + '</ul>' if eligible else '<p>No active reviewed dependencies. In this view, prerequisites have not been adjudicated; this does not mean there are no prerequisites.</p>'
    source_list = ''.join(f'<li><a href="{_text(source["url"])}" target="_blank" rel="noopener noreferrer">{_text(source["title"])} ↗</a><p>{_text(source["citation"])}</p></li>' for source in data['sources'])
    serialized = json.dumps(data, ensure_ascii=True).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    replacements = {
        'TITLE': _text(data['title']), 'COUNTS': count_text,
        'QUESTIONS': _questions(records, items, relations), 'FILTERS': _filters(records),
        'RECORD_LIST': ''.join(record_rows), 'RECORD_COUNT': _count_label(len(records), 'record'),
        'DETAILS': ''.join(_detail(r, items, sources, relations, history, r['id'] == selected) for r in records),
        'DETAIL_EMPTY': '' if records else 'Select a record to inspect its evidence and history.',
        'DEPENDENCIES': dependencies, 'SOURCES': source_list or '<li>No sources recorded.</li>',
        'DATA': serialized, 'CSS': (STATIC / 'workbench.css').read_text(encoding='utf-8'),
        'JS': (STATIC / 'workbench.js').read_text(encoding='utf-8'),
    }
    # One-pass substitution prevents supplied strings from becoming template tokens.
    template = (STATIC / 'page.html').read_text(encoding='utf-8')
    return DOCUMENT_MARKER + re.sub(r'\{\{([A-Z_]+)\}\}', lambda match: replacements[match[1]], template)


def _check_output(output, database):
    if output.is_symlink():
        raise WorkbenchError(f'refusing symlink output: {output}')
    protected = [database, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))]
    for path in protected:
        if output.resolve() == path.resolve() or (output.exists() and path.exists() and output.samefile(path)):
            raise WorkbenchError(f'refusing to overwrite database or its journal: {output}')
    if output.exists():
        if not output.is_file():
            raise WorkbenchError(f'output is not a regular file: {output}')
        with output.open('rb') as existing:
            if existing.read(len(DOCUMENT_MARKER)) != DOCUMENT_MARKER.encode('utf-8'):
                raise WorkbenchError(f'refusing to overwrite a source bundle or unmarked file: {output}')


def write_rendered_bundle(bundle: dict, output, database) -> None:
    """Replace only marked documents, with a complete file in the same directory."""
    output, database = Path(output), Path(database)
    temporary = None
    try:
        _check_output(output, database)
        html = render_bundle(bundle)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, prefix='.atlas-render-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        _check_output(output, database)
        os.replace(temporary, output)
    except (OSError, UnicodeError) as exc:
        raise WorkbenchError(f'cannot render to {output}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
