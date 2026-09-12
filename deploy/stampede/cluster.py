"""Bounded compute-node orchestration. No scheduler submission or login inference."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import random
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

SHUTDOWN_MARGIN_S = 240


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@contextmanager
def exclusive_lock(path: Path, *, blocking: bool = False):
    """Advisory locks release on process exit, including Slurm termination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def stop_process(process: subprocess.Popen, grace_s: float = 5) -> None:
    try:
        # The leader may have exited while compiler/server grandchildren still run.
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except ProcessLookupError:
        process.wait()
    except PermissionError:
        if process.poll() is None:
            raise
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can return EPERM after an orphan group has already disappeared.
            if process.poll() is None:
                raise


class ModelServer:
    def __init__(self, command, log_path: Path, *, env=None):
        self.command, self.log_path, self.env = command, log_path, env
        self.process = None
        self.log = None

    def __enter__(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open('a')
        try:
            self.process = subprocess.Popen(self.command, stdout=self.log,
                stderr=subprocess.STDOUT, env=self.env, start_new_session=True)
        except BaseException:
            self.log.close()
            raise
        return self

    def __exit__(self, *args):
        if self.process:
            stop_process(self.process)
        if self.log:
            self.log.close()

    def wait_ready(self, url: str, deadline: float, stop_event: threading.Event):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.time() < deadline and not stop_event.is_set():
            if self.process.poll() is not None:
                raise RuntimeError(f'model server exited {self.process.returncode}; see {self.log_path}')
            try:
                with opener.open(url + '/models', timeout=min(2, max(.1, deadline-time.time()))) as response:
                    if response.status == 200:
                        return
            except (OSError, ValueError):
                pass
            stop_event.wait(.5)
        raise RuntimeError('model server readiness deadline reached')


def run_probes(commands: dict, output_dir: Path, *, timeout_s=120,
               env=None, stop_event=None) -> dict:
    """Each branch has its own process group, timeout, log, and durable result."""
    stop_event = stop_event or threading.Event()
    output_dir.mkdir(parents=True, exist_ok=True)
    def probe(name, command):
        start = time.time()
        result = {'name': name, 'status': 'running', 'command': command, 'started': start}
        atomic_json(output_dir / f'{name}.json', result)
        try:
            with ModelServer(command, output_dir / f'{name}.log', env=env) as child:
                while child.process.poll() is None:
                    if stop_event.is_set():
                        result['status'] = 'interrupted'
                        break
                    if time.time()-start >= timeout_s:
                        result['status'] = 'timeout'
                        break
                    stop_event.wait(min(.05, max(.001, timeout_s-(time.time()-start))))
                else:
                    result['status'] = 'passed' if child.process.returncode == 0 else 'failed'
                result['returncode'] = child.process.poll()
        except Exception as exc:
            result.update(status='failed', error=str(exc))
        result['finished'] = time.time()
        atomic_json(output_dir / f'{name}.json', result)
        return name, result
    with ThreadPoolExecutor(max_workers=max(1, len(commands))) as pool:
        futures = [pool.submit(probe, name, cmd) for name, cmd in commands.items()]
        return dict(future.result() for future in futures)


def assigned_cells(cells: list[dict], rank: int, nodes: int) -> list[dict]:
    if nodes < 1 or not 0 <= rank < nodes:
        raise ValueError('invalid node rank')
    community = [c for c in cells if c.get('kind') == 'community']
    comparisons = [c for c in cells if c.get('kind') != 'community']
    random.Random(cells[0].get('seed', 20260912) if cells else 20260912).shuffle(comparisons)
    if nodes == 1:
        if not community:
            return comparisons
        queue = []
        for comparison in comparisons:
            queue.extend(community)
            queue.append(comparison)
        return queue + community
    if community:
        return community if rank == 0 else comparisons[rank-1::nodes-1]
    return comparisons[rank::nodes]


def accept_campaign_backend(run_dir: Path, identity: dict) -> dict:
    """The first verified inference fixes one backend/precision for this run."""
    with exclusive_lock(run_dir/'campaign-backend.lock', blocking=True):
        previous = read_json(run_dir/'campaign-backend.json')
        if previous and previous != identity:
            raise RuntimeError(f'campaign backend is already fixed: {previous}')
        if not previous:
            atomic_json(run_dir/'campaign-backend.json', identity)
        return identity


def verify_and_accept_backend(provider, config: dict, *, deadline: float,
                              run_dir: Path, identity: dict, diagnostic_path=None) -> dict:
    """Exercise the real experiment output contract before selecting a backend."""
    from .experiment import SYSTEM, _validate_output
    remaining = deadline-time.time()
    if remaining <= 0:
        raise RuntimeError('startup inference allocation deadline reached')
    packet = {
        'agent_id':'startup-agent', 'turn':0, 'audience':'startup-diagnostic',
        'seed':config.get('seed',20260912), 'synthetic':True, 'corpus_id':'startup-synthetic-engineering-v1',
        'question':('Summarize the supplied evidence in answer and memory. '
                    'For this startup check set publication to {"action":"none"}.'),
        'sources':[{'id':'startup-valve-test', 'synthetic':True,
                    'content':'In this fictional engineering trial, valve A remained closed during test one.'}],
        'individual_memory':[], 'shared_memory':[],
    }
    response = provider.generate([{'role':'system','content':SYSTEM},
                                  {'role':'user','content':json.dumps(packet)}],
                                 max_tokens=config.get('max_output_tokens',512),
                                 timeout_s=min(config.get('request_timeout_s',120),remaining))
    decision = _validate_output(response['text'])
    if decision['publication']['action'] != 'none':
        raise ValueError('startup publication action must be none')
    verified = {'status':'passed', 'execution':identity, 'response':response, 'decision':decision}
    if diagnostic_path is not None:
        atomic_json(diagnostic_path, verified)
    accept_campaign_backend(run_dir, identity)
    return verified


def run_schedule(cells, config, local_dir, run_dir, provider, *, deadline,
                 execute=None, stop_event=None) -> dict:
    if execute is None:
        from .experiment import run_cell
        execute = run_cell
    stop_event = stop_event or threading.Event()
    timer = threading.Timer(max(0, deadline-time.time()), stop_event.set)
    timer.daemon = True
    timer.start()
    state = {'status': 'running', 'cells': {}}
    try:
        for cell in cells:
            cid = cell['id']
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', cid) or cid in {'.', '..'}:
                raise ValueError('unsafe cell id')
            durable = run_dir / 'cells' / cid
            previous = read_json(durable / 'scheduler.json')
            identity = config.get('inference_identity')
            if previous and identity and previous.get('execution') != identity:
                state['cells'][cid] = {'id':cid, 'status':'failed',
                    'error':'saved cell inference identity differs from this worker'}
                continue
            # The experiment owns checkpoint restoration and completion validation.
            if previous.get('status') in ('completed', 'complete', 'complete_with_errors'):
                state['cells'][cid] = previous
                continue
            if stop_event.is_set() or time.time() >= deadline:
                state['cells'][cid] = {'id': cid, 'status': 'pending'}
                continue
            try:
                with exclusive_lock(durable / 'scheduler.lock'):
                    previous = read_json(durable / 'scheduler.json')
                    if previous.get('status') in ('completed', 'complete', 'complete_with_errors'):
                        state['cells'][cid] = previous
                        continue
                    local_dir.mkdir(parents=True, exist_ok=True)
                    atomic_json(durable / 'scheduler.json', {'id': cid, 'status': 'running',
                        'host': socket.gethostname(), 'pid': os.getpid(), 'started': time.time(),
                        'execution':identity})
                    try:
                        bounded_config = {**config, 'cell_seconds':config.get('cell_seconds',5400),
                            'session_seconds':min(config.get('cell_seconds',5400),
                                                  max(.01,deadline-time.time()))}
                        if cell.get('kind') == 'community':
                            remaining = max(.01, deadline-time.time())
                            bounded_config.update(max_turns=1000, max_calls_per_cell=1_000_000,
                                cell_seconds=86400, session_seconds=(min(60, remaining)
                                    if config.get('nodes',1)==1 else remaining))
                        result = execute(cell, bounded_config, local_dir, run_dir / 'cells', provider, stop_event=stop_event)
                        if cell.get('kind') == 'community' and result.get('status') in ('deadline','interrupted'):
                            result = dict(result, budget_reason=('epoch_limit'
                                if config.get('nodes',1)==1 and result.get('deadline_scope')=='session'
                                else 'allocation_limit' if result.get('deadline_scope')=='session' or stop_event.is_set()
                                else 'cell_budget'))
                    except Exception as exc:
                        result = {'id': cid, 'status': 'failed', 'error': str(exc)}
                    if identity:
                        result = dict(result, execution=identity, host=socket.gethostname(),
                                      device_probe=config.get('device_probe'))
                    atomic_json(durable / 'scheduler.json', result)
                    state['cells'][cid] = result
            except BlockingIOError:
                state['cells'][cid] = {'id': cid, 'status': 'busy'}
        statuses = [r['status'] for r in state['cells'].values()]
        if all(s in ('completed', 'complete') for s in statuses):
            state['status'] = 'completed'
        elif stop_event.is_set() or any(s in ('pending', 'interrupted') for s in statuses):
            state['status'] = 'interrupted'
        else:
            state['status'] = 'partial'
        return state
    finally:
        timer.cancel()


def batch_command(run_dir: Path, config: dict, environ: dict):
    if not environ.get('SLURM_JOB_ID'):
        raise RuntimeError('batch requires a Slurm compute allocation')
    nodes = int(environ.get('SLURM_NNODES', '0'))
    if nodes != config['nodes'] or int(environ.get('SLURM_NTASKS', '0')) != nodes:
        raise RuntimeError('allocation must have exactly one task per node and configured node count')
    env = dict(environ, TACC_TASKS_PER_NODE='1', I_MPI_PIN='0')
    return ['ibrun', str(run_dir / '.venv/bin/python'), '-m', 'deploy.stampede.cluster',
            'worker', '--run-dir', str(run_dir)], env


def job_deadline(config: dict, environ: dict, *, now=None) -> float:
    value = environ.get('SLURM_JOB_END_TIME')
    if not value or not str(value).isdigit():
        raise RuntimeError('Slurm job end time is unavailable; refusing an unbounded worker')
    return float(value) - SHUTDOWN_MARGIN_S


def _allocation_end(environ: dict) -> dict:
    if environ.get('SLURM_JOB_END_TIME'):
        return environ
    info = subprocess.run(['scontrol', 'show', 'job', '-o', environ['SLURM_JOB_ID']],
                          capture_output=True, text=True, check=True, timeout=15)
    match = re.search(r'\bEndTime=([^\s]+)', info.stdout)
    if not match:
        raise RuntimeError('scontrol did not return job end time')
    return dict(environ, SLURM_JOB_END_TIME=str(int(datetime.fromisoformat(match[1]).timestamp())))


def _signals(stop_event):
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
        signal.signal(sig, lambda *_: stop_event.set())


def current_node_states(run_dir: Path, nodes: int, job_id: str) -> dict:
    """Old run-directory reports cannot establish success for a resumed job."""
    reports = {}
    for rank in range(nodes):
        try:
            report = read_json(run_dir/'nodes'/str(rank)/'status.json')
        except (OSError, ValueError) as exc:
            reports[str(rank)] = {'status':'invalid', 'job_id':job_id, 'error':str(exc)}
            continue
        if report.get('job_id') != job_id:
            report = {'status':'missing', 'job_id':job_id,
                      'previous_job_id':report.get('job_id'), 'hardware_verified':False}
        reports[str(rank)] = report
    return reports


def batch(run_dir: Path) -> int:
    config = read_json(run_dir / 'config.json')
    command, env = batch_command(run_dir, config, dict(os.environ))
    env = _allocation_end(env)
    deadline = job_deadline(config, env)
    env['STAMPEDE_DEADLINE'] = str(deadline)
    stop_event = threading.Event()
    _signals(stop_event)
    atomic_json(run_dir/'status.json', {'status':'running', 'job_id':env['SLURM_JOB_ID'],
                                      'deadline':deadline, 'hardware_verified':False})
    with ModelServer(command, run_dir/'ibrun.log', env=env) as workers:
        terminate_at = deadline + 150
        next_update = 0
        while workers.process.poll() is None and time.time() < terminate_at:
            if time.monotonic() >= next_update:
                nodes = current_node_states(run_dir,config['nodes'],env['SLURM_JOB_ID'])
                # Live summaries omit full turn histories, which remain in cell artifacts.
                summaries = {rank:{k:v for k,v in report.items() if k != 'cells'}
                             for rank,report in nodes.items()}
                atomic_json(run_dir/'status.json', {'status':'running',
                    'job_id':env['SLURM_JOB_ID'], 'deadline':deadline, 'nodes':summaries,
                    'hardware_verified':any(n.get('hardware_verified') for n in nodes.values()),
                    'updated':time.time()})
                next_update = time.monotonic()+1
            if stop_event.is_set():
                # Worker deadline/signal handlers need time to publish a complete snapshot.
                terminate_at = min(terminate_at, time.time()+150)
            time.sleep(.5)
    nodes = current_node_states(run_dir,config['nodes'],env['SLURM_JOB_ID'])
    complete = workers.process.returncode == 0 and all(n.get('status') == 'completed' for n in nodes.values())
    state = {'status': 'completed' if complete else 'partial', 'job_id':env['SLURM_JOB_ID'],
             'nodes':nodes, 'finished':time.time(), 'returncode':workers.process.returncode,
             'hardware_verified':any(n.get('hardware_verified') for n in nodes.values())}
    atomic_json(run_dir/'status.json', state)
    return 0 if complete else 1


def worker(run_dir: Path) -> int:
    from .experiment import build_cells
    from .provider import LocalModel
    from . import profiles
    config = read_json(run_dir/'config.json')
    if not os.environ.get('SLURM_JOB_ID') or not os.environ.get('STAMPEDE_DEADLINE'):
        raise RuntimeError('worker must be launched by cluster batch in a compute allocation')
    rank_value = os.environ.get('PMI_RANK', os.environ.get('PMIX_RANK', os.environ.get('SLURM_PROCID')))
    if rank_value is None:
        raise RuntimeError('ibrun did not supply a node rank')
    rank = int(rank_value)
    if not 0 <= rank < config['nodes']:
        raise RuntimeError('invalid worker rank')
    node_dir = run_dir/'nodes'/str(rank)
    node_dir.mkdir(parents=True, exist_ok=True)
    deadline = float(os.environ['STAMPEDE_DEADLINE'])
    stop_event = threading.Event()
    _signals(stop_event)
    timer = threading.Timer(max(0, deadline-time.time()), stop_event.set)
    timer.daemon = True
    timer.start()
    state = {'status':'preparing', 'rank':rank, 'host':socket.gethostname(),
             'job_id':os.environ['SLURM_JOB_ID'],
             'hardware_verified':False, 'started':time.time()}
    atomic_json(node_dir/'status.json', state)
    try:
        # A duplicate host assignment fails instead of running two GPU owners.
        with exclusive_lock(run_dir/'host-locks'/f'{socket.gethostname()}.lock'):
            commands = {name:[sys.executable, '-m', 'deploy.stampede.cluster', 'probe',
                       '--run-dir',str(run_dir),'--backend',name] for name in profiles.PROFILES}
            results = run_probes(commands, node_dir/'probes', timeout_s=min(2700, max(.01, deadline-time.time())),
                                 env=os.environ.copy(), stop_event=stop_event)
            state['probes'] = results
            choices = [name for name in profiles.PROFILES if results[name]['status']=='passed'
                       and config.get('backend','auto') in ('auto', name)]
            selected = read_json(run_dir/'campaign-backend.json')
            if selected:
                choices = [name for name in choices if name == selected['backend']]
            if not choices:
                raise RuntimeError('no requested Intel backend passed; inspect independent probe logs')
            cells = assigned_cells(build_cells(config), rank, config['nodes'])
            # Each node has isolated live SQLite stores. run_cell restores durable complete generations.
            with tempfile.TemporaryDirectory(prefix=f'superyak-{os.environ["SLURM_JOB_ID"]}-{rank}-',
                    dir='/tmp') as temporary:
                errors = {}
                for backend in choices:
                    if stop_event.is_set():
                        break
                    try:
                        model = profiles.ensure_model(run_dir, config, deadline=deadline, backend=backend)
                        command, env = profiles.server_command(run_dir, config, backend, model, port=8000)
                        if backend == 'sycl':
                            env = profiles.sycl_environment(env)
                        with ModelServer(command, node_dir/f'{backend}-server.log', env=env) as server:
                            url = 'http://127.0.0.1:8000/v1'
                            server.wait_ready(url, min(deadline,time.time()+900), stop_event)
                            provider = LocalModel(url, config['model'], seed=config.get('seed',20260912))
                            # Successful arithmetic probing alone does not establish inference compatibility.
                            identity = {
                                'backend':backend, 'profile_revision':profiles.PROFILES[backend]['revision'],
                                'model_revision':model['revision'], 'dtype':'bfloat16' if backend=='vllm' else 'float16',
                                'device_selector':env['ONEAPI_DEVICE_SELECTOR']}
                            verify_and_accept_backend(provider,config,deadline=deadline,run_dir=run_dir,
                                identity=identity,diagnostic_path=node_dir/f'{backend}-inference.json')
                            effective_config = dict(config, inference_identity=identity, model_revision=model['revision'],
                                                    device_probe=str(node_dir/'probes'/f'{backend}.log'))
                            state.update(status='running', backend=backend, hardware_verified=True,
                                         model_revision=model['revision'])
                            atomic_json(node_dir/'status.json', state)
                            schedule = run_schedule(cells, effective_config, Path(temporary), run_dir, provider,
                                                    deadline=deadline, stop_event=stop_event)
                            state.update(schedule)
                            break
                    except Exception as exc:
                        errors[backend] = str(exc)
                        atomic_json(node_dir/f'{backend}-inference-failure.json', {'status':'failed','error':str(exc)})
                else:
                    raise RuntimeError(f'no backend completed inference startup: {errors}')
                if stop_event.is_set() and state['status'] in ('preparing', 'running'):
                    state['status'] = 'interrupted'
                state['backend_errors'] = errors
    except Exception as exc:
        state.update(status='interrupted' if stop_event.is_set() else 'failed', error=str(exc))
    finally:
        timer.cancel()
        state['finished'] = time.time()
        atomic_json(node_dir/'status.json', state)
    # Handled failures belong in durable reports. Nonzero MPI rank exits can abort
    # unrelated nodes; the batch controller alone returns campaign failure status.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['batch','worker','probe','model'])
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--backend', choices=['vllm','sycl'])
    args = parser.parse_args(argv)
    if not args.run_dir.is_absolute():
        parser.error('--run-dir must be absolute')
    if args.mode == 'probe':
        from .profiles import prepare_and_probe
        if not args.backend:
            parser.error('probe requires --backend')
        prepare_and_probe(args.run_dir, args.backend)
        return 0
    if args.mode == 'model':
        from .profiles import download_model
        download_model(args.run_dir, read_json(args.run_dir/'config.json'))
        return 0
    return batch(args.run_dir) if args.mode == 'batch' else worker(args.run_dir)


if __name__ == '__main__':
    raise SystemExit(main())
