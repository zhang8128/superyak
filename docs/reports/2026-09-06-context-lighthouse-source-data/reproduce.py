"""One synthetic Codex invocation; fresh stores, explicit policies, no retry."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from context_cli import build_parser, make_runtime, resolve_paths
from context_store import ContextStore
from lighthouse_daemon import PublisherDaemon, PublisherStore
from lighthouse_pilot import (ALLOWED_CONTENT, DENIED_CONTENT, PUBLISHER, RECEIVER,
                              SyntheticEmbeddings, _seed_stores, _write_policy)
from lighthouse_receipts import validate_receipt

output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
os.environ['ENGRAM_HOME'] = str(output)
stores = output / 'stores'
stores.mkdir()
_seed_stores(stores)
private_before = (stores / 'source.db').read_bytes()
publisher_before = (stores / 'publisher.db').read_bytes()
instance = output / '.engram' / 'instances' / RECEIVER
instance.mkdir(parents=True)
(instance / 'graph.db').touch()
publisher_policy = output / 'publisher-policy.json'
receiver_policy = instance / 'receiver-policy.json'
_write_policy(publisher_policy, issuer=PUBLISHER, peer=RECEIVER,
              actions=('recall', 'read'), audiences=['commons'])
_write_policy(receiver_policy, issuer=RECEIVER, peer=PUBLISHER,
              actions=('recall', 'read', 'inject_context'))
publisher = PublisherStore(PUBLISHER, stores / 'publisher.db', publisher_policy, stores / 'disclosures.db')
runtime = None
with tempfile.TemporaryDirectory(prefix='lh-live-', dir='/tmp') as socket_dir:
    daemon = PublisherDaemon({PUBLISHER: publisher}, Path(socket_dir) / 's.sock', SyntheticEmbeddings())
    worker = threading.Thread(target=daemon.serve_forever, daemon=True)
    worker.start()
    try:
        if not daemon.wait_ready(timeout=5):
            raise RuntimeError('Synthetic publisher failed to start')
        (instance / 'lighthouse-receiver.toml').write_text(
            f'enabled = true\npublishers = ["{PUBLISHER}"]\nsocket_path = "{daemon.socket_path}"\npolicy_path = "receiver-policy.json"\n')
        args = build_parser().parse_args(['--instance', RECEIVER, '--no-engram',
            '--lighthouse-context', 'memory/technical', '--lighthouse-purpose', 'session-recall',
            '--timeout', '120', '--thread', 'synthetic-live', 'chat'])
        directory, memory = resolve_paths(args)
        runtime = make_runtime(args, ContextStore(directory / 'context.db'), memory)
        generate = runtime.provider.generate
        dispatches = []
        def capture(payload):
            dispatches.append(payload)
            (output / 'supplied-request.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
            return generate(payload)
        runtime.provider.generate = capture
        # The deadline wrapper uses with_timeout; keep recording on its fresh provider view.
        with_timeout = runtime.provider.with_timeout
        def bounded(timeout):
            view = with_timeout(timeout)
            original_generate = view.generate
            def record(payload):
                dispatches.append(payload)
                (output / 'supplied-request.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')
                return original_generate(payload)
            view.generate = record
            return view
        runtime.provider.with_timeout = bounded
        started = time.monotonic()
        result = runtime.chat('synthetic-live', 'According to the shared bridge maintenance note, which support should be inspected? Answer in one short sentence.', event_id='synthetic-live-once')
        elapsed = time.monotonic() - started
        manifest = runtime.store.manifest('synthetic-live', result['manifest_id'])
        assert len(dispatches) == 1
        assert ALLOWED_CONTENT in json.dumps(dispatches[0])
        assert DENIED_CONTENT not in json.dumps(dispatches[0])
        assert manifest['source_dispatch']
        receipts = output / 'receipts'
        receipts.mkdir()
        for i, event in enumerate(runtime.store.recent_kind('synthetic-live', 'lighthouse_receipt', 32)):
            receipt = event['metadata']['receipt']
            validate_receipt(receipt)
            assert ALLOWED_CONTENT not in json.dumps(receipt)
            (receipts / f'{i}-{event["metadata"]["stage"]}.json').write_text(json.dumps(receipt, indent=2) + '\n')
        assert (stores / 'source.db').read_bytes() == private_before
        assert (stores / 'publisher.db').read_bytes() == publisher_before
        report = {'synthetic': True, 'human_usefulness_evaluated': False,
                  'provider': 'codex', 'model': runtime.provider.model,
                  'provider_dispatches': len(dispatches), 'elapsed_seconds': elapsed,
                  'expected_account_supplied': True, 'restricted_account_absent': True,
                  'private_source_unchanged': True, 'publisher_unchanged': True,
                  'response': result['response'], 'usage': result['usage'],
                  'capabilities': result['capabilities'], 'manifest': manifest,
                  'source_account': ALLOWED_CONTENT}
        (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    finally:
        daemon.stop()
        worker.join(timeout=5)
        if runtime is not None:
            runtime.close()
