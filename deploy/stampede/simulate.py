"""Deterministic offline rehearsal; never reports inference measurements."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
import uuid


class SimulationProvider:
    """Exercise evidence correction and explicit publication without a model."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, messages, *, max_tokens=512, timeout_s=120):
        packet = json.loads(messages[-1]['content'])
        with self._lock:
            self.calls += 1
        sources = packet['sources']
        source_ids = [source['id'] for source in sources]
        evidence = ' '.join(source['text'] for source in sources)
        publication = {'action': 'none'}
        if sources:
            publication = {
                'action': 'publish', 'audience': packet['audience'],
                'content': 'Simulation evidence review: ' + evidence,
                'source_ids': source_ids,
            }
        response = {
            'answer': 'SIMULATION: scripted evidence summary, not model reasoning. ' + evidence,
            'memory': f"Simulation history for {packet['agent_id']}, turn {packet['turn']}: " + evidence,
            'publication': publication,
        }
        return {'text': json.dumps(response), 'model': 'scripted-simulation',
                'input_tokens': None, 'output_tokens': None}


def run_simulation(output: Path, *, workers: int = 2) -> dict:
    """Run all twenty small cells, or restore completed cells with no new calls."""
    if isinstance(workers, bool) or workers not in range(1, 5):
        raise ValueError('workers must be between 1 and 4')
    # Engram preserves its independent source/package boundary in this monorepo.
    engram_source = str(Path(__file__).resolve().parents[2] / 'engram')
    if engram_source not in sys.path:
        sys.path.insert(0, engram_source)
    from .experiment import build_cells, run_cell

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = {
        'populations': [2, 4], 'concurrency': [1, 2], 'community_population': 0,
        'max_turns': 3, 'cell_seconds': 300, 'max_calls_per_cell': 100,
        'max_prompt_chars': 32000, 'max_output_tokens': 512,
        'request_timeout_s': 10, 'data_mode': 'synthetic',
        'model': 'scripted-simulation', 'model_revision': 'simulation-v1',
    }
    provider = SimulationProvider()

    def run(cell):
        try:
            result = run_cell(cell, config, output/'local', output/'durable', provider)
            return {key: result[key] for key in ('id', 'status', 'completed_turns', 'usage')}
        except Exception as error:
            # Independent cell errors stay visible and do not cancel siblings.
            return {'id': cell['id'], 'status': 'failed',
                    'error': f'{type(error).__name__}: {error}'}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        cells = list(pool.map(run, build_cells(config)))
    result = {
        'mode': 'simulation', 'hardware_verified': False,
        'status': 'complete' if all(c['status'] == 'complete' for c in cells) else 'partial',
        'provider_calls_this_invocation': provider.calls, 'cells': cells,
        'description': 'Real Engram stores and checkpoints; scripted responses; no GPU or SSH.',
    }
    temp = output / ('.simulation-' + uuid.uuid4().hex + '.json')
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    os.replace(temp, output/'simulation.json')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.engram/stampede/simulation'))
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    args = parser.parse_args(argv)
    result = run_simulation(args.output, workers=args.workers)
    summary = {key: result[key] for key in
               ('mode', 'hardware_verified', 'status', 'provider_calls_this_invocation')}
    summary.update(cells=len(result['cells']),
                   report=str(args.output.resolve()/'simulation.json'))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
