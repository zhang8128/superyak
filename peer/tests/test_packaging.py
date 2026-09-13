"""Exercise the actual distributable, isolated installs, and live startup."""
import hashlib
import json
import os
import runpy
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from urllib.request import urlopen
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def command(*args, cwd=ROOT, check=True):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')}
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, text=True, capture_output=True, timeout=120)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def bundle(root, output, check=True):
    script = root / 'scripts/source_bundle.py'
    assert script.is_file(), 'Standalone allowlisted source bundler is missing'
    return command(sys.executable, script, '--output', output, cwd=root, check=check)


@pytest.fixture
def archive(tmp_path):
    output = tmp_path / 'release.tar.gz'
    bundle(ROOT, output)
    return output


def test_bundle_actual_archive_excludes_unlisted_secrets_and_refuses_reuse(tmp_path):
    source = tmp_path / 'source'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.venv', '__pycache__', '.pytest_cache', 'dist'))
    sentinel = os.urandom(24).hex()
    for name in ('.env', '.private/key', 'peer.sqlite3', 'secret.pem', 'HANDOFF.md', 'superyak_peer/private.py', 'tests/passwords.json', 'superyak_peer/static/.env'):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sentinel)
    output = tmp_path / 'release.tar.gz'
    bundle(source, output)
    before = output.read_bytes()
    with tarfile.open(output) as archive:
        names = archive.getnames()
        assert 'superyak-peer/LICENSE' in names
        assert 'superyak-peer/scripts/two_peer_check.py' in names
        assert 'superyak-peer/uv.lock' in names
        checksums = json.load(archive.extractfile('superyak-peer/CHECKSUMS.json'))
        assert set(checksums) == {n.removeprefix('superyak-peer/') for n in names if n != 'superyak-peer/CHECKSUMS.json'}
        for member in archive.getmembers():
            assert member.isfile()
            assert not any(part.startswith('.') for part in Path(member.name).parts)
            data = archive.extractfile(member).read()
            assert sentinel.encode() not in data
            if member.name != 'superyak-peer/CHECKSUMS.json':
                assert hashlib.sha256(data).hexdigest() == checksums[member.name.removeprefix('superyak-peer/')]
    assert bundle(source, output, check=False).returncode != 0
    assert output.read_bytes() == before
    # An allowlisted symlink must never read a file outside the release tree.
    module = source / 'superyak_peer/__init__.py'
    module.unlink()
    module.symlink_to(source / '.env')
    assert bundle(source, tmp_path / 'unsafe.tar.gz', check=False).returncode != 0


def test_fresh_extraction_builds_static_wheel_and_starts_without_parent_repo(archive, tmp_path):
    extracted = tmp_path / 'fresh'
    # The shipped extractor supports early Python 3.11 as well as later releases.
    extract = runpy.run_path(str(ROOT / 'scripts/two_peer_check.py'))['extract']
    root = extract(archive, extracted)
    command('uv', 'sync', '--locked', '--no-dev', cwd=root)
    command(root / '.venv/bin/python', 'scripts/two_peer_check.py', '--help', cwd=root)
    builds = tmp_path / 'builds'
    command('uv', 'build', '--out-dir', builds, cwd=root)
    wheel = next(builds.glob('*.whl'))
    with zipfile.ZipFile(wheel) as package:
        assert {'superyak_peer/static/index.html', 'superyak_peer/static/app.js', 'superyak_peer/static/app.css'} <= set(package.namelist())
        assert any(name.endswith('/LICENSE') for name in package.namelist())
    installed = tmp_path / 'wheel-venv'
    command('uv', 'venv', installed, '--python', sys.executable, cwd=tmp_path)
    command('uv', 'pip', 'install', '--python', installed / 'bin/python', wheel, cwd=tmp_path)
    python = installed / 'bin/python'
    state = tmp_path / 'private-demo'
    seeded = command(python, '-m', 'superyak_peer', 'demo', '--data-dir', state, cwd=tmp_path)
    credentials = json.loads((state / 'demo-credentials.json').read_text())
    assert all(c['password'] not in seeded.stdout for c in credentials)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([str(python), '-m', 'superyak_peer', 'serve', '--data-dir', str(state), '--port', str(port)], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(f'http://127.0.0.1:{port}/', timeout=.5) as reply:
                    assert reply.status == 200 and b'Superyak' in reply.read()
                break
            except OSError:
                assert process.poll() is None, process.communicate()
                if time.monotonic() > deadline:
                    pytest.fail('Fresh wheel did not become ready')
                time.sleep(.05)
        with urlopen(f'http://127.0.0.1:{port}/assets/app.js') as reply:
            assert reply.status == 200 and len(reply.read()) > 1000
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_standard_build_excludes_private_state_and_unlisted_package_source(archive, tmp_path):
    extract = runpy.run_path(str(ROOT / 'scripts/two_peer_check.py'))['extract']
    root = extract(archive, tmp_path / 'standalone')
    state = root / '.engram/home-demo'
    command(sys.executable, '-m', 'superyak_peer', 'demo', '--data-dir', state, cwd=root)
    credentials = json.loads((state / 'demo-credentials.json').read_text())
    sentinel = os.urandom(24).hex()
    injected = ['.env', '.gitignore', '.engram/home/peer.sqlite3', '.engram/home/peer-key.pem', '.engram/home/identity.json', '.engram/home/demo-credentials.json', 'unlisted.txt', 'superyak_peer/unlisted.py', 'superyak_peer/static/unlisted.txt']
    for name in injected:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sentinel)
    builds = tmp_path / 'standard-build'
    command('uv', 'build', '--out-dir', builds, cwd=root)
    direct_builds = tmp_path / 'direct-wheel'
    command('uv', 'build', '--wheel', '--out-dir', direct_builds, cwd=root)
    with tarfile.open(next(builds.glob('*.tar.gz'))) as source:
        sdist = {str(Path(m.name).relative_to(Path(m.name).parts[0])): source.extractfile(m).read() for m in source.getmembers() if m.isfile()}
    with zipfile.ZipFile(next(builds.glob('*.whl'))) as wheel:
        wheel_files = {name: wheel.read(name) for name in wheel.namelist()}
    with zipfile.ZipFile(next(direct_builds.glob('*.whl'))) as wheel:
        direct_wheel_files = {name: wheel.read(name) for name in wheel.namelist()}
    for files in (sdist, wheel_files, direct_wheel_files):
        assert {'superyak_peer/static/index.html', 'superyak_peer/static/app.js', 'superyak_peer/static/app.css'} <= files.keys()
        assert any(name == 'LICENSE' or name.endswith('/LICENSE') for name in files)
        assert any(name == 'NOTICE' or name.endswith('/NOTICE') for name in files)
    assert {'scripts/source_bundle.py', 'scripts/two_peer_check.py', 'uv.lock', 'tests/test_packaging.py'} <= sdist.keys()
    forbidden = [sentinel.encode(), *(c['password'].encode() for c in credentials)]
    leaks = {kind: [name for name, content in files.items() if any(part.startswith('.') for part in Path(name).parts) or any(marker in content for marker in forbidden) or name in injected] for kind, files in [('sdist', sdist), ('wheel', wheel_files), ('direct_wheel', direct_wheel_files)]}
    assert leaks == {'sdist': [], 'wheel': [], 'direct_wheel': []}, leaks
