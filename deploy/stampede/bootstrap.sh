#!/usr/bin/env bash
# Only run-local dependency setup. GPU setup and inference occur after ibrun.
set -euo pipefail
if [[ $# != 1 || "$1" != /* ]]; then
  echo 'usage: bash bootstrap.sh ABS_RUN_DIR (absolute path required)' >&2
  exit 2
fi
python3 - "$1" <<'PY'
import fcntl, hashlib, io, json, os, pathlib, subprocess, sys, tarfile, time, urllib.request
run = pathlib.Path(sys.argv[1])
run.mkdir(parents=True, exist_ok=True)
status = run / 'bootstrap-status.json'
def write(value):
    tmp = status.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2)+'\n')
    os.replace(tmp, status)
with (run / 'bootstrap.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    source = run / 'source'
    if not (source / 'engram/uv.lock').is_file():
        raise SystemExit('staged source/engram/uv.lock missing')
    env = dict(os.environ, UV_CACHE_DIR=str(run/'.uv-cache'),
               UV_PYTHON_INSTALL_DIR=str(run/'.python'),
               UV_PROJECT_ENVIRONMENT=str(run/'.venv'), UV_NO_PROGRESS='1')
    write({'status':'preparing','uv':'0.8.3','python':'3.12.11','started':time.time()})
    try:
        binary = run / '.tools/uv'
        if not binary.exists():
            url = 'https://github.com/astral-sh/uv/releases/download/0.8.3/uv-x86_64-unknown-linux-gnu.tar.gz'
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(100*1024*1024)
            if hashlib.sha256(data).hexdigest() != '427c27ed5f87bf91aa045cf459ea34d348ed6377c62c3c054f1b4046b2f83fe2':
                raise RuntimeError('uv release checksum mismatch')
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
                executable = archive.extractfile('uv-x86_64-unknown-linux-gnu/uv').read()
            binary.parent.mkdir(exist_ok=True)
            binary.write_bytes(executable)
            binary.chmod(0o755)
        subprocess.run([str(binary),'python','install','3.12.11'],env=env,check=True,timeout=600)
        subprocess.run([str(binary),'sync','--frozen','--no-dev','--no-install-project',
            '--python','3.12.11','--project',str(source/'engram')],env=env,check=True,timeout=1800)
        check = subprocess.run([str(run/'.venv/bin/python'),'-c','import sqlite_vec, jsonschema; import sys; print(sys.version)'],
                               env=env,check=True,capture_output=True,text=True,timeout=60)
        write({'status':'prepared','uv':'0.8.3','python':check.stdout.strip(),
               'lock_sha256':hashlib.sha256((source/'engram/uv.lock').read_bytes()).hexdigest(),
               'hardware_verified':False,'finished':time.time()})
    except BaseException as exc:
        write({'status':'failed','error':str(exc),'finished':time.time()})
        raise
PY
