"""Offline campaign checks use the real memory stores and checkpoint path."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from deploy.stampede.simulate import run_simulation


def test_whole_matrix_and_resume_without_model_calls(tmp_path):
    first = run_simulation(tmp_path, workers=2)
    assert first['mode'] == 'simulation'
    assert first['hardware_verified'] is False
    assert first['status'] == 'complete'
    assert len(first['cells']) == 20
    assert first['provider_calls_this_invocation'] == 156
    assert all(c['status'] == 'complete' for c in first['cells'])
    durable = tmp_path / 'durable'
    shared = json.loads((durable / 'factorial-i1-s1-p2-c2' / 'result.json').read_text())
    assert shared['publication_events']
    assert shared['usage']['missing_usage_requests'] == shared['usage']['requests']
    assert shared['revision_events']
    assert all('sealed-calibration' not in json.dumps(t) for t in shared['turns'])
    later = [t['packet'] for t in shared['turns'] if t['packet']['turn'] == 2]
    assert all(p['individual_memory'] for p in later)
    assert any(p['shared_memory'] for p in later)
    assert len(list((tmp_path/'local'/'factorial-i1-s1-p2-c2'/'stores').glob('agent-*.sqlite'))) == 2
    shutil.rmtree(tmp_path / 'local')
    second = run_simulation(tmp_path, workers=3)
    assert second['status'] == 'complete'
    assert second['provider_calls_this_invocation'] == 0
    assert second['cells'] == first['cells']
    assert len(list((tmp_path/'local'/'factorial-i1-s1-p2-c2'/'stores').glob('agent-*.sqlite'))) == 2


def test_simulate_cli_forwards_flags_and_needs_no_credentials(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('OPENAI_API_KEY', None)
    result = subprocess.run(
        [sys.executable, '-m', 'deploy.stampede', 'simulate', '--output', str(tmp_path), '--workers', '2'],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'complete'
    assert json.loads((tmp_path/'simulation.json').read_text())['mode'] == 'simulation'


def test_exported_real_checkpoint_restores_after_original_run_is_lost(tmp_path):
    from deploy.stampede.experiment import build_cells, run_cell
    from deploy.stampede.export import create_export
    from deploy.stampede.simulate import SimulationProvider
    run = tmp_path/'original'
    cell = next(c for c in build_cells({'populations': [2], 'concurrency': [2]})
                if c['individual'] and c['shared'])
    config = {'max_turns': 2, 'cell_seconds': 30, 'request_timeout_s': 2,
              'model': 'scripted-simulation', 'data_mode': 'synthetic'}
    provider = SimulationProvider()
    first = run_cell(cell, config, tmp_path/'local', run/'cells', provider)
    export = create_export(run, run/'exports/checkpoint.tar.gz')
    restored = tmp_path/'restored'
    with tarfile.open(export['archive']) as archive:
        archive.extractall(restored, filter='data')
    shutil.rmtree(run)
    shutil.rmtree(tmp_path/'local')
    before = provider.calls
    result = run_cell(cell, config, tmp_path/'fresh-local', restored/'cells', provider)
    assert result['status'] == 'complete'
    assert result['turns'] == first['turns']
    assert result['publication_events'] == first['publication_events']
    assert provider.calls == before
