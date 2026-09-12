"""Pinned Intel user-space profiles, installed and tested only on compute nodes.

Sources verified 2026-09-12:
https://docs.vllm.ai/en/latest/getting_started/installation/gpu/
https://github.com/vllm-project/vllm/blob/13e221f8308416564a446909c2fd4805c78fbb8a/requirements/xpu.txt
https://github.com/ggml-org/llama.cpp/blob/3057bb66c86c46d5781e50e85462a760ba7d1feb/docs/backend/SYCL.md
https://dgpu-docs.intel.com/driver/installation.html

These profiles never install or alter kernel drivers. oneAPI compiler/libraries for
SYCL must be supplied by the site; their exact versions are recorded. vLLM resolves
transitive versions once into a run-local lock, reused for repair/retry. Host Intel
runtime compatibility is established by probes and actual server inference.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .cluster import atomic_json, exclusive_lock, read_json, run_probes

PROFILES = {
    'vllm': {
        'repository':'https://github.com/vllm-project/vllm.git',
        'revision':'13e221f8308416564a446909c2fd4805c78fbb8a',
        'python':'3.12.11', 'ninja':'1.11.1.4', 'torch':'2.13.0', 'triton':'3.7.2+xpu',
        'vllm_xpu_kernels':'0.1.14.1',
        'driver_note':'Upstream recommends compute runtime 26.18 or newer starting with kernels 0.1.10; host must be probed.',
    },
    'sycl': {
        'repository':'https://github.com/ggml-org/llama.cpp.git',
        'revision':'3057bb66c86c46d5781e50e85462a760ba7d1feb',
        'python':'3.12.11', 'cmake':'3.31.6', 'ninja':'1.11.1.4',
        'compiler_note':'Requires site icx/icpx and oneAPI libraries (upstream verified 2025.3.3). No root install.',
    },
}


def compute_only():
    if not os.environ.get('SLURM_JOB_ID') or not os.environ.get('STAMPEDE_DEADLINE'):
        raise RuntimeError('Intel preparation requires a compute worker allocation')


def environment(run_dir: Path) -> dict:
    return dict(os.environ, UV_CACHE_DIR=str(run_dir/'.uv-cache'),
        UV_PYTHON_INSTALL_DIR=str(run_dir/'.python'), UV_NO_PROGRESS='1',
        HF_HOME=str(run_dir/'model'/'hub-cache'), HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
        HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
        VLLM_NO_USAGE_STATS='1', VLLM_TARGET_DEVICE='xpu',
        ONEAPI_DEVICE_SELECTOR='level_zero:0', OMP_NUM_THREADS='8',
        XDG_CACHE_HOME=str(run_dir/'.cache'))


def command(argv, *, env, cwd=None, capture=False, timeout=1200):
    print('+', ' '.join(map(str, argv)), flush=True)
    result = subprocess.run(list(map(str,argv)), env=env, cwd=cwd, check=True,
                            timeout=timeout, text=True, capture_output=capture)
    if capture and result.stdout:
        print(result.stdout, flush=True)
    return result.stdout if capture else ''


def _source(profile_dir, profile, env):
    source = profile_dir/'source'
    source.mkdir(parents=True, exist_ok=True)
    if not (source/'.git').exists():
        command(['git','init',source],env=env)
        command(['git','remote','add','origin',profile['repository']],env=env,cwd=source)
    command(['git','fetch','--depth','1','origin',profile['revision']],env=env,cwd=source)
    command(['git','checkout','--detach',profile['revision']],env=env,cwd=source)
    actual = command(['git','rev-parse','HEAD'],env=env,cwd=source,capture=True).strip()
    if actual != profile['revision']:
        raise RuntimeError('backend source revision mismatch')
    return source


def sycl_environment(env):
    if shutil.which('icpx',path=env.get('PATH')):
        return env
    setvars = Path('/opt/intel/oneapi/setvars.sh')
    if setvars.is_file():
        # Parse NUL-separated environment without printing values or evaluating generated code.
        output = subprocess.run(['bash','-c','source /opt/intel/oneapi/setvars.sh >/dev/null && env -0'],
                                env=env,check=True,capture_output=True,timeout=60).stdout
        return dict(item.decode().split('=',1) for item in output.split(b'\0') if b'=' in item)
    raise RuntimeError('SYCL profile requires site oneAPI icx/icpx; compiler was not found')


def _install(run_dir, backend, env):
    profile = PROFILES[backend]
    directory = run_dir/'profiles'/backend
    directory.mkdir(parents=True,exist_ok=True)
    uv = run_dir/'.tools/uv'
    python = directory/'.venv/bin/python'
    with exclusive_lock(directory/'install.lock',blocking=True):
        previous = read_json(directory/'installed.json')
        if previous.get('revision') == profile['revision'] and python.exists():
            return directory
        atomic_json(directory/'status.json', {'status':'installing',**profile})
        source = _source(directory,profile,env)
        if not python.exists():
            command([uv,'venv','--python','3.12.11',directory/'.venv'],env=env)
        lock = directory/'dependencies.lock'
        if backend == 'vllm':
            requirements = directory/'requirements.in'
            requirements.write_text(f'ninja=={profile["ninja"]}\n-r {source}/requirements/xpu.txt\n')
        else:
            requirements = directory/'requirements.in'
            requirements.write_text(f'cmake=={profile["cmake"]}\nninja=={profile["ninja"]}\n-r {source}/requirements/requirements-convert_hf_to_gguf.txt\n')
        if not lock.exists():
            command([uv,'pip','compile','--python',python,'--index-strategy','unsafe-best-match',
                     '--generate-hashes','--emit-index-url','-o',lock,requirements],env=env,timeout=1200)
        command([uv,'pip','sync','--python',python,'--index-strategy','unsafe-best-match',
                 '--require-hashes',lock],env=env,timeout=1200)
        if backend == 'vllm':
            command([uv,'pip','install','--python',python,'--no-build-isolation','--no-deps',source],
                    env=env,timeout=1800)
        else:
            command([directory/'.venv/bin/cmake','-S',source,'-B',directory/'build',
                '-DGGML_SYCL=ON','-DGGML_SYCL_F16=ON','-DCMAKE_C_COMPILER=icx',
                '-DCMAKE_CXX_COMPILER=icpx','-DCMAKE_BUILD_TYPE=Release','-DLLAMA_CURL=OFF',
                '-DLLAMA_BUILD_TESTS=OFF'],env=env)
            command([directory/'.venv/bin/cmake','--build',directory/'build','-j','8',
                     '--target','llama-server'],env=env,timeout=1800)
        freeze = command([uv,'pip','freeze','--python',python],env=env,capture=True)
        (directory/'installed-freeze.txt').write_text(freeze)
        record = {**profile, 'status':'installed','installed_at':time.time(),
                  'dependency_lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest()}
        if backend == 'sycl':
            record['compiler'] = command(['icpx','--version'],env=env,capture=True)
            binary = directory/'build/bin/llama-server'
            record['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        atomic_json(directory/'installed.json',record)
        atomic_json(directory/'status.json',record)
    return directory


def prepare_and_probe(run_dir: Path, backend: str):
    compute_only()
    env = environment(run_dir)
    if backend == 'sycl':
        env = sycl_environment(env)
    directory = _install(run_dir,backend,env)
    command(['uname','-a'],env=env)
    if Path('/etc/os-release').exists():
        print(Path('/etc/os-release').read_text(),flush=True)
    if backend == 'vllm':
        code = '''import json, torch, vllm
assert torch.xpu.is_available(), "torch XPU unavailable on allocated host"
a=torch.ones((64,64), device="xpu", dtype=torch.float32)
b=a@a
torch.xpu.synchronize()
assert b[0,0].item()==64
print(json.dumps({"torch":torch.__version__,"vllm":vllm.__version__,"devices":[str(torch.xpu.get_device_properties(i)) for i in range(torch.xpu.device_count())]}))'''
        command([directory/'.venv/bin/python','-c',code],env=env,timeout=120)
    else:
        devices = command(['sycl-ls'],env=env,capture=True,timeout=60)
        if 'level_zero:gpu' not in devices and 'level_zero:0' not in devices:
            raise RuntimeError('SYCL did not enumerate an Intel Level Zero GPU')
        command([directory/'build/bin/llama-server','--list-devices'],env=env,timeout=60)


def download_model(run_dir: Path, config: dict):
    compute_only()
    from huggingface_hub import HfApi, snapshot_download
    directory = run_dir/'model'
    directory.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(directory/'download.lock',blocking=True):
        if read_json(directory/'manifest.json').get('status') == 'complete':
            return
        pinned = read_json(directory/'resolved.json')
        api = HfApi(token=False)
        if not pinned:
            info = api.model_info(config['model'],revision=config.get('model_revision','main'),
                                  files_metadata=True,timeout=60)
            pinned = {'model':config['model'],'requested_revision':config.get('model_revision','main'),
                      'revision':info.sha}
            atomic_json(directory/'resolved.json',pinned)
        if pinned['model'] != config['model']:
            raise RuntimeError('run model identity changed')
        path = snapshot_download(config['model'], revision=pinned['revision'], token=False,
            cache_dir=str(directory/'hub-cache'), local_dir=str(directory/'snapshot'), max_workers=4,
            allow_patterns=['*.json','*.safetensors','*.model','*.txt','*.tiktoken','*.jinja'])
        files = []
        for file in sorted(Path(path).rglob('*')):
            if not file.is_file() or '.cache' in file.relative_to(path).parts:
                continue
            digest = hashlib.sha256()
            with file.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024*1024),b''):
                    digest.update(block)
            files.append({'path':str(file.relative_to(path)), 'bytes':file.stat().st_size,
                          'sha256':digest.hexdigest()})
        if not any(f['path'].endswith('.safetensors') for f in files):
            raise RuntimeError('model snapshot has no safetensors weights')
        atomic_json(directory/'manifest.json',{**pinned,'status':'complete','path':str(path),'files':files})


def ensure_model(run_dir: Path, config: dict, *, deadline: float, backend='vllm') -> dict:
    compute_only()
    env = environment(run_dir)
    result = run_probes({'download':[sys.executable,'-m','deploy.stampede.cluster','model',
                                    '--run-dir',str(run_dir)]},run_dir/'model'/'download-status',
                        timeout_s=max(.01,min(1800,deadline-time.time())),env=env)
    if result['download']['status'] != 'passed':
        raise RuntimeError('bounded model download failed; inspect model/download-status')
    model = read_json(run_dir/'model/manifest.json')
    if backend == 'sycl':
        directory = run_dir/'profiles/sycl'
        gguf = run_dir/'model/model-f16.gguf'
        with exclusive_lock(run_dir/'model/convert.lock',blocking=True):
            completed = read_json(run_dir/'model/gguf.json')
            if not completed or completed.get('revision') != model['revision'] or not gguf.exists():
                temporary = gguf.with_suffix('.partial.gguf')
                result = run_probes({'convert':[str(directory/'.venv/bin/python'),
                    str(directory/'source/convert_hf_to_gguf.py'),model['path'],'--outfile',str(temporary),
                    '--outtype','f16']},run_dir/'model/conversion-status',
                    timeout_s=max(.01,min(1200,deadline-time.time())),env=env)
                if result['convert']['status'] != 'passed':
                    raise RuntimeError('bounded GGUF conversion failed')
                os.replace(temporary,gguf)
                digest=hashlib.sha256()
                with gguf.open('rb') as stream:
                    for block in iter(lambda:stream.read(8*1024*1024),b''):
                        digest.update(block)
                atomic_json(run_dir/'model/gguf.json',{'revision':model['revision'],
                    'converter':PROFILES['sycl']['revision'],'sha256':digest.hexdigest(),'dtype':'f16'})
        model['gguf'] = str(gguf)
    return model


def server_command(run_dir, config, backend, model, *, port):
    env = environment(run_dir)
    env['HF_HUB_OFFLINE'] = '1'
    concurrency = max(config.get('concurrency',[4,16]))
    directory = run_dir/'profiles'/backend
    if backend == 'vllm':
        argv = [str(directory/'.venv/bin/python'),'-m','vllm.entrypoints.openai.api_server',
            '--model',model['path'],'--served-model-name',config['model'], '--host','127.0.0.1',
            '--port',str(port),'--tensor-parallel-size','1','--dtype','bfloat16',
            '--max-model-len','8192','--max-num-seqs',str(concurrency),'--enforce-eager']
    else:
        # Site setup is performed by worker immediately before launch; pure command building
        # remains usable for offline inspection and process-boundary tests.
        argv = [str(directory/'build/bin/llama-server'),'-m',model['gguf'],
            '--alias',config['model'],'--host','127.0.0.1','--port',str(port),
            '--n-gpu-layers','999','--parallel',str(concurrency),
            '--ctx-size',str(8192*concurrency),'--jinja']
    return argv,env
