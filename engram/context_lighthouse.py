"""Turn-local Lighthouse evidence with fresh authorization at dispatch.

Direct source/tool bodies are not cached in the archive. Generated output
follows the ordinary conversation archive behavior and may quote a source.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import sqlite3
import time
import uuid

from context_compile import Candidate
from lighthouse_client import LighthouseClient, NeighborUnavailable, validate_read
from lighthouse_policy import PolicyRequest
from lighthouse_protocol import artifact_digest, canonical_json, read_frame
from lighthouse_receipts import validate_receipt
from lighthouse_receiver_config import NAME, context_ref, load_receiver_policy, load_settings
from permissions import annotation_line
from neighbors import CLAIM_TYPE, PROFILE, neighbor_arm


def _key(item):
    return 'lighthouse:' + item['publisher'].removeprefix('urn:engram:') + ':' + item['memoryId']


def _evidence(item, *, with_permission=True):
    shown = {k: item[k] for k in ('publisher', 'memoryId', 'layer', 'lane', 'audiences', 'contentDigest')}
    permission = item.get('permission') if with_permission else None
    if permission is not None:
        shown['permission'] = annotation_line(permission) if isinstance(permission, dict) else permission
    return canonical_json({**shown, 'account': item['content']})


def _version(item):
    # The permission line names a receipt that changes on every read; the version names content and source only.
    return hashlib.sha256(_evidence(item, with_permission=False).encode()).hexdigest()


def _settings_digest(settings):
    return hashlib.sha256(canonical_json({k: str(v) if k.endswith('_path') else v
                                         for k, v in settings.items()}).encode()).hexdigest()


class LighthouseSource:
    mode = 'lighthouse'

    def __init__(self, store, *, receiver, instance_dir, context_id, purpose, thread=None, turn_id=None, deadline=None):
        from pathlib import Path
        if not isinstance(receiver, str) or not NAME.fullmatch(receiver):
            raise ValueError('Lighthouse requires a named receiver')
        if not isinstance(purpose, str) or not 1 <= len(purpose) <= 256:
            raise ValueError('Lighthouse requires an explicit purpose')
        self.store, self.receiver = store, receiver
        self.instance_dir = Path(instance_dir).resolve()
        self.context, self.purpose = context_ref(context_id), purpose
        self.thread, self.turn_id = thread, turn_id
        self.deadline = deadline
        self.entries = {}
        self.coverage = {}

    def for_turn(self, thread, turn_id, *, deadline=None):
        # The HTTP runtime is shared; evidence and handles must not cross threads.
        return LighthouseSource(self.store, receiver=self.receiver, instance_dir=self.instance_dir,
                                context_id=self.context['id'], purpose=self.purpose,
                                thread=thread, turn_id=turn_id, deadline=deadline)

    def _deadline(self, settings):
        now = time.monotonic()
        deadline = now + settings['timeout_s']
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        if deadline <= now:
            raise NeighborUnavailable('TIMEOUT')
        return deadline

    def _settings(self):
        if not (self.instance_dir / 'graph.db').is_file():
            return None
        return load_settings(self.instance_dir / 'lighthouse-receiver.toml')

    def _permits(self, settings, publisher, *, decisions=None, phase='check'):
        if publisher.removeprefix('urn:engram:') not in settings['publishers']:
            return False
        policy = load_receiver_policy(settings['policy_path'], self.receiver)
        allowed = True
        for action in ('recall', 'read', 'inject_context'):
            decision = policy.decide(PolicyRequest(
                publisher=publisher, profile=PROFILE, domain='memory.recall', action=action,
                context_id=self.context['id'], claim_type=CLAIM_TYPE, purpose=self.purpose,
                audience='self', at=datetime.now(timezone.utc)))
            allowed = allowed and decision.effect == 'allow'
            if decisions is not None:
                decisions.append(dict(publisher=publisher, action=action, phase=phase, **decision.to_json()))
        return allowed

    def _record(self, receipt, stage, settings, payload_digest=None):
        receipt = deepcopy(receipt)
        receipt.setdefault('extensions', {})['engram:contextRuntime'] = {
            'stage': stage, 'settingsDigest': _settings_digest(settings),
            'payloadDigest': payload_digest,
            'meaning': 'Authorized boundary delivery; does not establish model use or successful invocation.'}
        receipt['digest'] = artifact_digest(receipt)
        validate_receipt(receipt)
        self.store.append(self.thread, 'system', 'Lighthouse receipt', kind='lighthouse_receipt',
                          turn_id=self.turn_id, metadata={'stage': stage, 'receipt': receipt})
        return receipt

    def search(self, query, limit=8):
        settings = self._settings()
        self.coverage = {'enabled': settings is not None}
        if settings is None:
            return []
        source = self

        class ReceiptLog:
            receipt = None

            def add_log_entry(self, **entry):
                self.receipt = source._record(entry['context']['receipt'], 'source_preparation', settings)

        log = ReceiptLog()
        timeout = min(settings['timeout_s'], self._deadline(settings) - time.monotonic())
        result = neighbor_arm(query=query, context=self.context, purpose=self.purpose,
                              storage=log, session_id=self.thread, recall_id=self.turn_id or str(uuid.uuid4()),
                              receiver=self.receiver, **{**settings, 'k': min(settings['k'], max(1, limit)),
                                                        'timeout_s': timeout})
        if result is None:
            return []
        self.coverage.update(receipt_id=result['receipt_id'], diagnostics=result['diagnostics'])
        found = []
        for item in result['delivered']:
            key = _key(item)
            self.entries[key] = {'item': item, 'receipt': log.receipt, 'settings': _settings_digest(settings)}
            found.append(Candidate(key, 'user', (_evidence(item),), score=40-len(found),
                                   reason='Lighthouse shared account', version=_version(item)))
        return found

    def valid(self, candidate):
        # Publisher I/O is batched after counting in prepare_dispatch. This check
        # also protects an existing tool episode before preparing another request.
        entry = self.entries.get(candidate.id)
        if entry is None or _version(entry['item']) != candidate.version:
            return False
        settings = self._settings()
        return bool(settings and entry['settings'] == _settings_digest(settings)
                    and self._permits(settings, entry['item']['publisher']))

    def _read_entries(self, entries, *, stage, payload_digest=None):
        """Re-read original handles with one deadline, then recheck every receiver grant."""
        if not entries:
            return {}, []
        settings = self._settings()
        if settings is None or any(e['settings'] != _settings_digest(settings) for e in entries.values()):
            return {}, []
        deadline = self._deadline(settings)
        client = LighthouseClient(settings['socket_path'], timeout_s=settings['timeout_s'])
        groups, verified, decisions, diagnostics = {}, {}, [], []
        for key, entry in entries.items():
            groups.setdefault(entry['receipt']['id'], {})[key] = entry
        for group in groups.values():
            receipt = next(iter(group.values()))['receipt']
            for snapshot in receipt['extensions']['engram:traceSnapshots']:
                publisher = snapshot['publisher']
                chosen = [e['item'] for e in group.values() if e['item']['publisher'] == publisher]
                if not chosen or not self._permits(settings, publisher, decisions=decisions, phase=stage + '_read'):
                    continue
                try:
                    reply = client.call(read_frame(receiver=self.receiver,
                        publisher=publisher.removeprefix('urn:engram:'), context=self.context,
                        purpose=self.purpose, turn_id=snapshot['turnId'],
                        memory_ids=[i['memoryId'] for i in chosen]), deadline=deadline)
                    verified.update({_key(item): item for item in validate_read(reply, selected=chosen)})
                except (OSError, ValueError, RuntimeError) as error:
                    diagnostics.append({'publisher': publisher, 'code': getattr(error, 'code', 'READ_FAILED')})
        # Configuration and every receiver grant are reloaded after all publisher I/O.
        if time.monotonic() >= deadline or self._settings() != settings:
            return {}, []
        allowed = {publisher for publisher in {i['publisher'] for i in verified.values()}
                   if self._permits(settings, publisher, decisions=decisions, phase=stage + '_delivery')}
        if time.monotonic() >= deadline or self._settings() != settings:
            return {}, []
        verified = {key: item for key, item in verified.items() if item['publisher'] in allowed
                    and ('content' not in entries[key]['item'] or _version(item) == _version(entries[key]['item']))}
        receipts = []
        for group in groups.values():
            receipt = deepcopy(next(iter(group.values()))['receipt'])
            receipt['id'] = f'urn:engram:{self.receiver}:receipt:{uuid.uuid4()}'
            receipt['issuedAt'] = datetime.now(timezone.utc).isoformat()
            receipt['payload']['turnId'] = self.turn_id or str(uuid.uuid4())
            receipt['payload']['selected'] = [i for i in receipt['payload']['selected'] if _key(i) in group]
            receipt['payload']['delivered'] = [dict(publisher=verified[key]['publisher'],
                memoryId=verified[key]['memoryId'], readDecision=verified[key]['decision'])
                for key in group if key in verified]
            receipt['payload']['injected'] = bool(receipt['payload']['delivered'])
            receipt['extensions']['engram:receiverDecisions'] = decisions
            receipt['extensions']['engram:diagnostics'] = diagnostics
            saved = self._record(receipt, stage, settings, payload_digest)
            receipts.append(saved['id'])
        return verified, receipts

    def prepare_dispatch(self, candidates, payload_digest, *, reads=()):
        relevant = {c.id: c.version for c in candidates if c.id.startswith('lighthouse:')}
        for snapshot in reads:
            if snapshot['id'].startswith('lighthouse:'):
                relevant.setdefault(snapshot['id'], None)
        if not relevant:
            return set(), None
        try:
            entries = {key: self.entries[key] for key in relevant}
            verified, receipts = self._read_entries(entries, stage='model_dispatch', payload_digest=payload_digest)
            invalid = {key for key, version in relevant.items()
                       if key not in verified or (version is not None and _version(verified[key]) != version)}
            return invalid, {'mode': self.mode, 'receipt_id': receipts[0] if receipts else None,
                             'receipt_ids': receipts, 'invalidated_ids': sorted(invalid)}
        except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error):
            return set(relevant), {'mode': self.mode, 'error': 'SOURCE_REVALIDATION_FAILED'}

    def read(self, source_id, *, offset=0, limit=4096):
        if not source_id.startswith('lighthouse:'):
            return None
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError('Invalid source page')
        try:
            # Inspection has no live turn session. Restore only an authorized,
            # thread-local handle from bounded content-free receipt history.
            if source_id not in self.entries:
                for event in reversed(self.store.recent_kind(self.thread, 'lighthouse_receipt', 8)):
                    receipt = event['metadata']['receipt']
                    validate_receipt(receipt)
                    payload = receipt['payload']
                    if (receipt['issuer'] != f'urn:engram:{self.receiver}' or payload['context'] != self.context
                            or payload['purpose'] != self.purpose):
                        continue
                    delivered = {_key(i) for i in payload['delivered']}
                    for snapshot in receipt['extensions']['engram:traceSnapshots']:
                        for candidate in snapshot['candidates']:
                            item = {**candidate, 'publisher': snapshot['publisher']}
                            if _key(item) == source_id and source_id in delivered:
                                # No body is cached: the publisher must supply it again.
                                self.entries[source_id] = {'item': item, 'receipt': receipt,
                                    'settings': receipt['extensions']['engram:contextRuntime']['settingsDigest']}
                    if source_id in self.entries:
                        break
            entry = self.entries.get(source_id)
            if entry is None:
                return None
            verified, _ = self._read_entries({source_id: entry}, stage='source_inspection')
            item = verified.get(source_id)
            if item is None:
                return None
            self.entries[source_id] = {**entry, 'item': item}
            return {'id': source_id, 'source': item['publisher'], 'layer': item['layer'], 'lane': item['lane'],
                    'text': item['content'][offset:offset+limit], 'content_digest': item['contentDigest'],
                    'next_offset': offset+limit if offset+limit < len(item['content']) else None}
        except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error):
            return None
