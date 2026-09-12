"""Read-only archive tools, scoped to the current coding task and chosen sources."""

from __future__ import annotations

import sqlite3

from context_runtime import TOOLS as CHAT_TOOLS
from context_store import ArchiveSearchTimeout


SEARCH_KINDS = ('message', 'correction', 'coding_observation', 'coding_task')
TOOLS = [{**tool, 'description': tool['description'] + (
    ' Omit limit to read 2048 units, or set limit to an integer from 1 to 4096; use next_offset for further pages.'
    if tool['name'] == 'archive_read' else '')} for tool in CHAT_TOOLS]


class CodingMemory:
    def __init__(self, store, sources):
        self.store, self.sources = store, sources

    def call(self, thread, name, args):
        try:
            if not isinstance(args, dict):
                raise ValueError('Archive tool arguments must be an object')
            if name == 'archive_search':
                query = args.get('query')
                if set(args) != {'query'} or not isinstance(query, str) or len(query) > 2000:
                    raise ValueError('Archive query must be text of at most 2000 characters')
                rows = self.store.search(thread, query, limit=6, kinds=SEARCH_KINDS)
                results = [{'id': r['id'], 'role': r['role'], 'excerpt': r['content'][:800],
                            'metadata': r['metadata']} for r in rows]
                coverage = []
                for source in self.sources:
                    if getattr(source, 'mode', None) == 'adna_project':
                        results.extend({'id': c.id, 'role': c.role, 'excerpt': c.representations[0][:2000],
                                        'metadata': {'version': c.version, 'kind': c.reason}}
                                       for c in source.search(query, limit=3))
                        coverage.append(dict(source.coverage))
                return {'results': results,
                    'source_coverage': coverage,
                    'coverage': 'Bounded index of task goals, checkpoints, corrections, tool-result excerpts, and selected aDNA documents; read originals by ID.'}
            if name != 'archive_read':
                raise ValueError('Unsupported read-only archive tool')
            if set(args) - {'id', 'offset', 'limit'}:
                raise ValueError('Unexpected archive page fields')
            source_id, offset, limit = args.get('id'), args.get('offset', 0), args.get('limit', 2048)
            if not isinstance(source_id, str) or len(source_id) > 256:
                raise ValueError('Archive id must be a source ID string of at most 256 characters')
            if type(offset) is not int or offset < 0:
                raise ValueError('Archive offset must be an integer >= 0; omit it to start at 0')
            if type(limit) is not int or not 1 <= limit <= 4096:
                raise ValueError('Archive limit must be an integer from 1 to 4096; retry with limit=4096 or omit it for 2048')
            if source_id.startswith('state:'):
                pin = next((p for p in self.store.state(thread) if p['key'] == source_id[6:]), None)
                if pin is None:
                    raise KeyError('State is unavailable in this thread')
                source_id = pin['source_id']
            row = self.store.event_page(thread, source_id, offset, limit)
            if row:
                return {**row, 'offset_unit': 'characters'}
            if source_id.startswith(('engram:', 'adna:')):
                for source in self.sources:
                    row = source.read(source_id, offset=offset, limit=limit)
                    if row:
                        return row
                raise KeyError('Source is unavailable')
            data = self.store.read_artifact(thread, source_id, offset, limit)
            return {'id': source_id, 'text': data.decode('utf-8', errors='replace'), 'offset_unit': 'bytes',
                    'next_offset': offset + len(data) if len(data) == limit else None,
                    'encoding': 'UTF-8 display; a page boundary may split a character'}
        except ArchiveSearchTimeout as exc:
            return {'error': 'ArchiveSearchTimeout', 'coverage': 'incomplete', 'message': str(exc)}
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            return {'error': str(exc)}
