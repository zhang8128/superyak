"""Fresh-checkout integration; no model, network or live Atlas journal."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def command(*args, cwd=None):
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment['PYTHONNOUSERSITE'] = '1'
    return subprocess.run([sys.executable, '-S', *map(str, args)], cwd=cwd or ROOT,
                          env=environment, capture_output=True, text=True, timeout=30)


def test_offline_demo_is_isolated_repeatable_and_exports_views(tmp_path):
    script = ROOT / 'scripts/atlas.py'
    assert script.is_file(), 'Root Atlas demo has not been implemented'
    project = tmp_path / 'project'
    result = command(script, '--project', project, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['publication_status'] == 'current'
    view = report['research_views']
    assert Path(view['browser']).is_relative_to(project)
    assert 'q-fate' in Path(view['browser']).read_text()
    assert Path(view['home']).is_file()
    assert Path(view['canvas']).is_file()
    assert not list(project.glob('.atlas/drafts/*.json')), 'Demo must not invent research findings'
    state = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (project / '.atlas/publications').rglob('*') if p.is_file()}
    again = command(script, '--project', project, cwd=tmp_path)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)['generation'] == report['generation']
    assert all(hashlib.sha256((project / path).read_bytes()).hexdigest() == value for path, value in state.items())


def test_demo_refuses_foreign_seed_without_overwriting_it(tmp_path):
    script = ROOT / 'scripts/atlas.py'
    assert script.is_file(), 'Root Atlas demo has not been implemented'
    project = tmp_path / 'foreign'
    config = project / 'workbench/data/lighthouse-automation.json'
    config.parent.mkdir(parents=True)
    config.write_text('{"foreign": true}')
    result = command(script, '--project', project, cwd=tmp_path)
    assert result.returncode != 0
    assert config.read_text() == '{"foreign": true}'
    assert not (project / '.atlas').exists()


def test_poc_defaults_to_bundled_atlas(tmp_path):
    program = r'''
import json, sys
from pathlib import Path
from research_poc import __main__ as cli
class Finished(Exception): pass
def prepare(source, output):
    print(json.dumps({'source':str(source)}))
    raise Finished()
cli.prepare_atlas = prepare
try:
    cli.main(['prepare', '--output', sys.argv[1]])
except Finished:
    pass
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path / 'run')], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)['source']) == ROOT / 'atlas'


def test_staged_atlas_runs_without_private_state_or_editable_installs(tmp_path):
    from deploy.stampede.launcher import prepare_bundle
    source = tmp_path / 'source'
    for component in ('deploy', 'research_poc', 'atlas'):
        original = ROOT / component
        assert original.is_dir(), f'Missing bundled component: {component}'
        shutil.copytree(original, source / component,
                        ignore=shutil.ignore_patterns('.venv', '.atlas', '.engram', '__pycache__', '.pytest_cache'))
    (source / 'scripts').mkdir()
    script = ROOT / 'scripts/atlas.py'
    assert script.is_file(), 'Root Atlas demo has not been implemented'
    shutil.copyfile(script, source / 'scripts/atlas.py')
    for relative in ('atlas/.atlas/drafts/private.json', 'atlas/Research/private.md',
                     'atlas/.obsidian/private.json', 'atlas/.env', 'atlas/private.db',
                     'atlas/.engram/memory.json', 'atlas/workbench/private.json',
                     'atlas/workbench/data/private.json', 'atlas/workbench/static/private.txt',
                     'research_poc/private.json'):
        p = source / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('private fixture')
    (source / 'atlas/workbench/private_link.py').symlink_to(source / 'atlas/.env')
    (source / 'atlas/workbench/private_directory').symlink_to(source / 'atlas/.atlas', target_is_directory=True)
    archive = prepare_bundle(source, tmp_path / 'source.tar.gz')
    extracted = tmp_path / 'extracted'
    with tarfile.open(archive) as bundle:
        names = bundle.getnames()
        assert 'atlas/workbench/automation.py' in names
        assert 'atlas/workbench/data/cell_fate.json' in names
        assert 'atlas/workbench/static/page.html' in names
        assert 'research_poc/__main__.py' in names
        assert 'scripts/atlas.py' in names
        assert not any('private' in name or '/Research/' in name or '/.atlas/' in name
                       or '/.obsidian/' in name or name.endswith(('.db', '/.env')) for name in names)
        bundle.extractall(extracted, filter='data')
    result = command(extracted / 'scripts/atlas.py', '--project', tmp_path / 'demo', cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)['research_views']['browser']).is_file()
    cli = command(extracted / 'atlas/scripts/atlas_research.py', '--project', tmp_path / 'demo', 'context', 'q-fate', cwd=tmp_path)
    assert cli.returncode == 0, cli.stderr
    assert any(r['record']['id'] == 'q-fate' for r in json.loads(cli.stdout)['records'])
