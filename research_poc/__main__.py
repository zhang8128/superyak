"""Run or resume a bounded real-source research experiment."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time

# Engram is a sibling source project with established top-level module imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engram'))
from .atlas_bridge import prepare_atlas, fetch_documents, AtlasModel
from .experiment import CONDITIONS, COMMUNITY, write_report, save, _pin, run_worker, pin_implementation



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'status'], nargs='?', default='run')
    parser.add_argument('--atlas-source', default=str(Path.home() / 'Projects/atlas-workbench'))
    parser.add_argument('--output', default='.engram/research-poc/local-pilot')
    parser.add_argument('--model', default='qwen3.8:27b-mlx')
    parser.add_argument('--rounds', type=int, default=2, help='Fixed comparison rounds, 1–20')
    parser.add_argument('--community-rounds', type=int, default=2, help='May increase when resuming, up to 20')
    parser.add_argument('--concurrency', type=int, choices=[1, 2], default=2, help='Independent cell processes')
    parser.add_argument('--timeout', type=int, default=120, help='Per model call seconds')
    parser.add_argument('--retry-interrupted', action='store_true', help='Explicitly retry unsuccessful model attempts; remote execution may duplicate')
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 20 or not 1 <= args.community_rounds <= 20 or not 1 <= args.timeout <= 600:
        parser.error('rounds must be 1–20 and timeout 1–600 seconds')
    root = Path(args.output).resolve()
    if args.command == 'status':
        if not root.exists():
            parser.error('No run exists at this output path')
        cells = write_report(root)
        print(json.dumps([{key: c[key] for key in ('condition', 'completed_turns', 'calls', 'shares', 'failed_or_interrupted_calls')} for c in cells], indent=2))
        print(f'Report: {root / "report.md"}')
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'run.lock').open('a') as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('This run already has an owner')
        pin_implementation(root, Path(__file__).parent)
        prepared = prepare_atlas(Path(args.atlas_source), root)
        documents = fetch_documents(root)
        info = AtlasModel(args.model, args.timeout).check()
        _pin(root / 'experiment.json', dict(version=1, model=args.model, model_digest=info.get('digest'),
             comparison_rounds=args.rounds, concurrency=args.concurrency, conditions=CONDITIONS + [COMMUNITY],
             question_id=prepared['question']['id'], source_hashes=[d['document']['content_sha256'] for d in documents],
             context_budget=dict(context_window=16384, input_bytes=12000, output_reserve=1200, margin=1024)))
        if not (root / 'runtime.json').exists():
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True)
            save(root / 'runtime.json', dict(started_at=time.time(), python=sys.version, model_info=info,
                 superyak_revision=revision.stdout.strip(), operator_thread=os.environ.get('CODEX_THREAD_ID'),
                 identities='Separate logical research agents; not separate human or Codex sessions',
                 determinism='temperature 0, no fixed seed or deterministic execution guarantee'))
        print(f'Prepared {len(documents)} real documents; isolated state: {root}', flush=True)
        if args.command == 'prepare':
            return 0
        options = vars(args) | {'output': str(root), 'atlas_source': str(Path(args.atlas_source).resolve())}
        failures = []
        started = time.monotonic()
        with ProcessPoolExecutor(max_workers=args.concurrency, mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = {pool.submit(run_worker, options, condition): condition for condition in CONDITIONS + [COMMUNITY]}
            for future in as_completed(futures):
                condition = futures[future]
                try:
                    result = future.result()
                    print(f'{condition["id"]}: {result["completed_turns"]} turns, {result["calls"]} recorded calls, {result["shares"]} shares', flush=True)
                except Exception as error:
                    failures.append(dict(cell=condition['id'], error=f'{type(error).__name__}: {error}'))
                    print(f'{condition["id"]}: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
                write_report(root)
        cells = write_report(root)
        save(root / 'last-invocation.json', dict(elapsed_seconds=time.monotonic() - started, failures=failures,
             completed_turns=sum(c['completed_turns'] for c in cells), calls=sum(c['calls'] for c in cells)))
        print(f'Report: {root / "report.md"}', flush=True)
        return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
