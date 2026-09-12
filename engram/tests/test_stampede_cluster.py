"""Process and accelerator boundaries; scheduler uses real filesystem state."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


def cluster():
    try:
        return importlib.import_module('deploy.stampede.cluster')
    except ModuleNotFoundError:
        pytest.fail('cluster orchestration is not implemented')


def test_independent_probes_keep_failure_and_success(tmp_path):
    c = cluster()
    commands = {
        'vllm': [sys.executable, '-c', 'import sys; print("driver mismatch", flush=True); sys.exit(7)'],
        'sycl': [sys.executable, '-c', 'print("level_zero:gpu Intel GPU")'],
    }
    results = c.run_probes(commands, tmp_path, timeout_s=3)
    assert results['vllm']['status'] == 'failed'
    assert results['sycl']['status'] == 'passed'
    assert 'driver mismatch' in (tmp_path / 'vllm.log').read_text()
    assert json.loads((tmp_path / 'sycl.json').read_text())['returncode'] == 0


def test_probe_timeout_does_not_cancel_other_branch(tmp_path):
    c = cluster()
    result = c.run_probes({
        'vllm': [sys.executable, '-c', 'import time; time.sleep(30)'],
        'sycl': [sys.executable, '-c', 'print("ok")'],
    # Include generous process-startup headroom under full-suite contention.
    # The sleeping branch still exceeds this bound by an order of magnitude.
    }, tmp_path, timeout_s=3)
    assert result['vllm']['status'] == 'timeout'
    assert result['sycl']['status'] == 'passed'


def test_assignments_keep_one_owner_and_reserve_community():
    c = cluster()
    cells = [{'id': f'c{i}', 'kind': 'comparison'} for i in range(20)]
    cells.append({'id': 'community', 'kind': 'community'})
    assigned = [c.assigned_cells(cells, rank, 4) for rank in range(4)]
    assert [x['id'] for x in assigned[0]] == ['community']
    assert sorted(x['id'] for group in assigned for x in group) == sorted(x['id'] for x in cells)
    assert {x['id'] for x in c.assigned_cells(cells, 0, 1)} == {x['id'] for x in cells}


def test_scheduler_continues_after_failure_and_resumes_results(tmp_path):
    c = cluster()
    cells = [{'id': 'bad'}, {'id': 'good'}]
    process_calls = []
    def execute(cell, config, local_dir, durable_dir, provider, *, stop_event):
        process_calls.append(cell['id'])
        if cell['id'] == 'bad':
            raise RuntimeError('model server rejected cell')
        assert local_dir.is_relative_to(tmp_path / 'local')
        return {'id': cell['id'], 'status': 'completed', 'completed_turns': 1}
    result = c.run_schedule(cells, {}, tmp_path / 'local', tmp_path / 'run', None,
                            deadline=time.time()+20, execute=execute)
    assert result['status'] == 'partial'
    assert result['cells']['bad']['status'] == 'failed'
    assert result['cells']['good']['status'] == 'completed'
    c.run_schedule(cells, {}, tmp_path / 'local2', tmp_path / 'run', None,
                   deadline=time.time()+20, execute=execute)
    assert process_calls == ['bad', 'good', 'bad']


def test_scheduler_does_not_start_work_after_deadline(tmp_path):
    c = cluster()
    def execute(*args, **kwargs):
        pytest.fail('expired job started new work')
    result = c.run_schedule([{'id':'pending'}], {}, tmp_path/'local', tmp_path/'run', None,
                            deadline=time.time()-1, execute=execute)
    assert result['status'] == 'interrupted'
    assert result['cells']['pending']['status'] == 'pending'


def test_scheduler_signals_live_cell_before_expiry(tmp_path):
    c = cluster()
    def execute(cell, config, local_dir, durable_dir, provider, *, stop_event):
        assert stop_event.wait(2), 'cell did not receive deadline stop'
        return {'id': cell['id'], 'status': 'interrupted'}
    start = time.time()
    result = c.run_schedule([{'id':'live'}], {}, tmp_path/'local', tmp_path/'run', None,
                            deadline=time.time()+.1, execute=execute)
    assert result['status'] == 'interrupted'
    assert time.time()-start < 2


def test_scheduler_exclusive_cell_lock(tmp_path):
    c = cluster()
    with c.exclusive_lock(tmp_path/'run'/'cells'/'live'/'scheduler.lock'):
        result = c.run_schedule([{'id':'live'}], {}, tmp_path/'local', tmp_path/'run', None,
                                deadline=time.time()+1,
                                execute=lambda *a, **k: pytest.fail('concurrent ownership'))
    assert result['cells']['live']['status'] == 'busy'


def test_batch_refuses_missing_or_oversubscribed_slurm_allocation(tmp_path):
    c = cluster()
    with pytest.raises(RuntimeError, match='allocation'):
        c.batch_command(tmp_path, {'nodes': 2}, {})
    with pytest.raises(RuntimeError, match='one task per node'):
        c.batch_command(tmp_path, {'nodes':2}, {'SLURM_JOB_ID':'42','SLURM_NNODES':'2','SLURM_NTASKS':'4'})
    command, env = c.batch_command(tmp_path, {'nodes':2},
        {'SLURM_JOB_ID':'42','SLURM_NNODES':'2','SLURM_NTASKS':'2'})
    assert command[0] == 'ibrun'
    assert 'worker' in command
    assert env['TACC_TASKS_PER_NODE'] == '1'


def test_deadline_uses_slurm_end_time_and_shutdown_margin():
    c = cluster()
    assert c.job_deadline({'walltime':'12:00:00'}, {'SLURM_JOB_END_TIME':'1000'}, now=100) == 760
    with pytest.raises(RuntimeError, match='end time'):
        c.job_deadline({'walltime':'12:00:00'}, {}, now=100)


def test_model_server_process_is_terminated(tmp_path):
    c = cluster()
    server = c.ModelServer([sys.executable, '-c', 'import time; time.sleep(30)'],
                           tmp_path/'server.log', env=os.environ.copy())
    with server:
        pid = server.process.pid
        assert server.process.poll() is None
    assert server.process.poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_bootstrap_rejects_relative_directory_without_installing(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'deploy/stampede/bootstrap.sh'
    assert script.exists(), 'bootstrap is not implemented'
    result = subprocess.run(['bash', str(script), 'relative'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'absolute' in result.stderr


def test_scheduler_uses_experiment_parent_directories(tmp_path):
    c = cluster()
    def execute(cell, config, local_dir, durable_dir, provider, *, stop_event):
        assert durable_dir == tmp_path/'run'/'cells'
        assert local_dir == tmp_path/'local'
        with c.exclusive_lock(durable_dir/cell['id']/'owner.lock'):
            return {'id': cell['id'], 'status':'completed'}
    result = c.run_schedule([{'id':'one'}], {}, tmp_path/'local', tmp_path/'run', None,
                           deadline=time.time()+1, execute=execute)
    assert result['status'] == 'completed', result


def test_profiles_reject_login_node_before_install(tmp_path, monkeypatch):
    try:
        p = importlib.import_module('deploy.stampede.profiles')
    except ModuleNotFoundError:
        pytest.fail('Intel profiles missing')
    monkeypatch.delenv('SLURM_JOB_ID', raising=False)
    with pytest.raises(RuntimeError, match='compute'):
        p.prepare_and_probe(tmp_path, 'vllm')
    assert not (tmp_path/'profiles').exists()


def test_server_commands_use_same_pinned_model_and_loopback(tmp_path):
    try:
        p = importlib.import_module('deploy.stampede.profiles')
    except ModuleNotFoundError:
        pytest.fail('Intel profiles missing')
    model = {'path':str(tmp_path/'model'/'snapshot'),'revision':'a'*40,
             'gguf':str(tmp_path/'model'/'model-f16.gguf')}
    config = {'model':'Qwen/Qwen3-8B','concurrency':[4,16]}
    for backend in ('vllm','sycl'):
        command, env = p.server_command(tmp_path, config, backend, model, port=8031)
        assert '127.0.0.1' in command
        assert 'Qwen/Qwen3-8B' in command
        assert '8031' in command
        assert env['HF_HUB_OFFLINE'] == '1'
        assert env['ONEAPI_DEVICE_SELECTOR'] == 'level_zero:0'


def test_process_group_cleanup_after_parent_exits(tmp_path):
    c = cluster()
    marker = tmp_path/'child.pid'
    code = ('import subprocess,sys,pathlib; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
            f'pathlib.Path({str(marker)!r}).write_text(str(p.pid))')
    with c.ModelServer([sys.executable,'-c',code],tmp_path/'log') as server:
        server.process.wait(timeout=2)
    child = int(marker.read_text())
    # kill(0) also sees zombies; ps distinguishes an exited orphan from live work.
    deadline = time.time()+2
    while time.time()<deadline:
        status = subprocess.run(['ps','-o','stat=','-p',str(child)],capture_output=True,text=True).stdout.strip()
        if not status or status.startswith('Z'):
            break
        time.sleep(.02)
    else:
        os.kill(child, 9)
        pytest.fail('orphan model child remains running after server parent exited')


def test_bootstrap_executes_frozen_setup_and_persists_failure(tmp_path):
    script = Path(__file__).resolve().parents[2]/'deploy/stampede/bootstrap.sh'
    source = tmp_path/'source'/'engram'
    source.mkdir(parents=True)
    (source/'uv.lock').write_text('version = 1\n')
    binary = tmp_path/'.tools'/'uv'
    binary.parent.mkdir()
    binary.write_text('#!/bin/sh\necho "recorded setup boundary" >&2\nexit 8\n')
    binary.chmod(0o755)
    result = subprocess.run(['bash',str(script),str(tmp_path)],capture_output=True,text=True)
    assert result.returncode != 0
    state = json.loads((tmp_path/'bootstrap-status.json').read_text())
    assert state['status'] == 'failed'
    assert 'recorded setup boundary' in result.stderr


def test_scheduler_real_experiment_restores_and_skips_completed_calls(tmp_path):
    c = cluster()
    class Provider:
        calls = 0
        def generate(self, messages, **kwargs):
            self.calls += 1
            return {'text':json.dumps({'answer':'synthetic answer','memory':'my private history',
                                      'publication':{'action':'none'}}),
                    'input_tokens':4,'output_tokens':3,'model':'fixture'}
    provider = Provider()
    cell = {'id':'actual-cell','population':2,'individual':True,'shared':True,
            'concurrency':2,'seed':5,'kind':'factorial'}
    config = {'max_turns':1,'cell_seconds':10,'request_timeout_s':1,'data_mode':'synthetic'}
    result = c.run_schedule([cell],config,tmp_path/'local',tmp_path/'run',provider,deadline=time.time()+10)
    assert result['status'] == 'completed', result
    assert provider.calls == 2
    assert (tmp_path/'run/cells/actual-cell/CURRENT').exists()
    # Missing scheduler summary models interruption after the experiment snapshot completed.
    (tmp_path/'run/cells/actual-cell/scheduler.json').unlink()
    resumed = c.run_schedule([cell],config,tmp_path/'new-local',tmp_path/'run',provider,deadline=time.time()+10)
    assert resumed['status'] == 'completed'
    assert provider.calls == 2
    assert len(list((tmp_path/'new-local/actual-cell/stores').glob('agent-*.sqlite'))) == 2


def test_single_node_interleaves_persistent_community_epochs():
    c = cluster()
    comparisons = [{'id':f'c{i}','kind':'factorial','seed':23} for i in range(8)]
    community = {'id':'community','kind':'community','seed':23}
    assigned = c.assigned_cells(comparisons+[community],0,1)
    assert assigned[0] == assigned[-1] == community
    assert assigned[::2] == [community]*9
    assert sorted(x['id'] for x in assigned[1::2]) == sorted(x['id'] for x in comparisons)
    assert c.assigned_cells(comparisons+[community],0,1) == assigned


def test_community_epoch_uses_stable_identity_and_session_budget(tmp_path):
    c = cluster()
    seen = []
    def execute(cell, config, local_dir, durable_dir, provider, *, stop_event):
        seen.append(config)
        return {'id':cell['id'],'status':'deadline','deadline_scope':'session','elapsed_s':2}
    community = {'id':'community','kind':'community'}
    state = c.run_schedule([community,community], {'nodes':1,'max_turns':12},
                           tmp_path/'local',tmp_path/'run',None,deadline=time.time()+80,execute=execute)
    assert len(seen) == 2
    assert all(s['max_turns']==1000 and s['max_calls_per_cell']==1_000_000 for s in seen)
    assert all(s['cell_seconds']==86400 and s['session_seconds']==60 for s in seen)
    assert state['cells']['community']['budget_reason']=='epoch_limit'
    assert state['status'] != 'completed'


def test_campaign_backend_cannot_mix_inference_profiles(tmp_path):
    c = cluster()
    identity = {'backend':'vllm','model_revision':'a'*40,'profile_revision':'b'*40,'dtype':'bfloat16'}
    accepted = c.accept_campaign_backend(tmp_path,identity)
    assert accepted == identity
    assert c.accept_campaign_backend(tmp_path,dict(identity)) == identity
    with pytest.raises(RuntimeError, match='campaign backend'):
        c.accept_campaign_backend(tmp_path,dict(identity,backend='sycl',dtype='float16'))
    assert json.loads((tmp_path/'campaign-backend.json').read_text()) == identity


def test_cell_resume_rejects_changed_backend_identity(tmp_path):
    c = cluster()
    original = {'backend':'vllm','dtype':'bfloat16','model_revision':'a'*40}
    def execute(cell, config, local_dir, durable_dir, provider, *, stop_event):
        return {'id':cell['id'],'status':'completed'}
    first = c.run_schedule([{'id':'bound-cell'}],{'inference_identity':original},tmp_path/'local',
                           tmp_path/'run',None,deadline=time.time()+10,execute=execute)
    assert first['cells']['bound-cell']['execution'] == original
    second = c.run_schedule([{'id':'bound-cell'}],
        {'inference_identity':dict(original,backend='sycl')},tmp_path/'new-local',tmp_path/'run',
        None,deadline=time.time()+10,execute=lambda *a,**k:pytest.fail('mixed backend resumed'))
    assert second['cells']['bound-cell']['status'] == 'failed'
    assert 'inference identity' in second['cells']['bound-cell']['error']


@pytest.mark.parametrize('text', ['ready', '{"answer": "ok"}', '{"answer": 3, "memory": "x", "publication": {"action": "none"}}'])
def test_text_or_malformed_startup_cannot_accept_backend(tmp_path, text):
    c = cluster()
    class Provider:
        def generate(self, messages, **kwargs):
            return {'text':text,'model':'fixture'}
    with pytest.raises((ValueError, RuntimeError)):
        c.verify_and_accept_backend(Provider(), {'model':'fixture'}, deadline=time.time()+5,
                                    run_dir=tmp_path, identity={'backend':'vllm'})
    assert not (tmp_path/'campaign-backend.json').exists()


def test_startup_validates_real_experiment_schema_before_acceptance(tmp_path):
    c = cluster()
    from deploy.stampede.experiment import SYSTEM
    class Provider:
        def generate(self, messages, **kwargs):
            assert messages[0] == {'role':'system','content':SYSTEM}
            packet = json.loads(messages[1]['content'])
            assert packet['synthetic'] and packet['sources']
            assert kwargs['max_tokens'] == 512
            return {'text':json.dumps({'answer':'Valve remained closed.', 'memory':'Test one: closed valve.',
                                      'publication':{'action':'none'}}),'model':'fixture'}
    verified = c.verify_and_accept_backend(Provider(),{'model':'fixture'},deadline=time.time()+5,
                                           run_dir=tmp_path,identity={'backend':'vllm'})
    assert verified['decision']['publication']['action'] == 'none'
    assert json.loads((tmp_path/'campaign-backend.json').read_text()) == {'backend':'vllm'}


def test_resumed_comparison_keeps_cumulative_budget_with_short_allocation(tmp_path):
    c = cluster()
    from deploy.stampede.experiment import run_cell
    class Provider:
        calls = 0
        def generate(self,messages,**kwargs):
            self.calls += 1
            time.sleep(.03)
            return {'text':json.dumps({'answer':'synthetic','memory':'saved',
                                      'publication':{'action':'none'}}),
                    'input_tokens':3,'output_tokens':2,'model':'fixture'}
    provider = Provider()
    cell = {'id':'resumed-comparison','population':1,'individual':True,'shared':False,
            'concurrency':1,'seed':5,'kind':'factorial'}
    config = {'max_turns':100,'cell_seconds':2,'session_seconds':.4,
              'request_timeout_s':1,'data_mode':'synthetic'}
    first = run_cell(cell,config,tmp_path/'initial',tmp_path/'run/cells',provider)
    assert first['status'] == 'deadline' and first['elapsed_s'] >= .4
    seen = []
    def execute(cell,config,local_dir,durable_dir,provider,*,stop_event):
        seen.append(config)
        return run_cell(cell,config,local_dir,durable_dir,provider,stop_event=stop_event)
    before = first['usage']['requests']
    resumed = c.run_schedule([cell],config,tmp_path/'restored',tmp_path/'run',provider,
                            deadline=time.time()+.3,execute=execute)
    assert seen[0]['cell_seconds'] == 2
    assert 0 < seen[0]['session_seconds'] <= .3
    assert resumed['cells'][cell['id']]['usage']['requests'] > before
    assert resumed['cells'][cell['id']]['elapsed_s'] < 2


def test_failed_worker_persists_current_job_status_without_aborting_mpi(tmp_path, monkeypatch):
    import signal
    c = cluster()
    (tmp_path/'config.json').write_text(json.dumps({'nodes':1,'backend':'auto'}))
    monkeypatch.setenv('SLURM_JOB_ID','current-job')
    monkeypatch.setenv('STAMPEDE_DEADLINE',str(time.time()+5))
    monkeypatch.setenv('PMI_RANK','0')
    monkeypatch.setattr(c,'run_probes',lambda *a,**k:{name:{'status':'failed','error':'GPU unavailable'}
                                                    for name in ('vllm','sycl')})
    handlers = {sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGUSR1)}
    try:
        result = c.worker(tmp_path)
    finally:
        for sig,handler in handlers.items():
            signal.signal(sig,handler)
    state = json.loads((tmp_path/'nodes/0/status.json').read_text())
    assert result == 0, 'a handled node failure must not trigger an MPI rank abort'
    assert state['status'] == 'failed' and state['job_id'] == 'current-job'
    assert state['hardware_verified'] is False


def _fake_ibrun(tmp_path,monkeypatch,body):
    binary = tmp_path/'bin/ibrun'
    binary.parent.mkdir()
    binary.write_text(f'#!{sys.executable}\n'+body+'\n')
    binary.chmod(0o755)
    (tmp_path/'config.json').write_text(json.dumps({'nodes':1}))
    monkeypatch.setenv('PATH',str(binary.parent)+os.pathsep+os.environ['PATH'])
    monkeypatch.setenv('SLURM_JOB_ID','current-job')
    monkeypatch.setenv('SLURM_NNODES','1')
    monkeypatch.setenv('SLURM_NTASKS','1')
    monkeypatch.setenv('SLURM_JOB_END_TIME',str(int(time.time()+600)))


def _batch_with_restored_signals(c,run_dir):
    import signal
    handlers = {sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGUSR1)}
    try:
        return c.batch(run_dir)
    finally:
        for sig,handler in handlers.items():
            signal.signal(sig,handler)


@pytest.mark.parametrize('node_job,node_status,launcher_exit',[
    ('current-job','failed',0), ('old-job','completed',0), ('current-job','completed',3)])
def test_batch_rejects_failed_stale_or_launcher_failed_completion(tmp_path,monkeypatch,node_job,node_status,launcher_exit):
    c = cluster()
    c.atomic_json(tmp_path/'nodes/0/status.json',{'job_id':node_job,'status':node_status,'hardware_verified':True})
    _fake_ibrun(tmp_path,monkeypatch,f'raise SystemExit({launcher_exit})')
    result = _batch_with_restored_signals(c,tmp_path)
    state = json.loads((tmp_path/'status.json').read_text())
    assert result != 0 and state['status'] == 'partial'
    if node_job == 'old-job':
        assert state['hardware_verified'] is False
        assert state['nodes']['0']['status'] == 'missing'


def test_batch_publishes_current_node_verification_while_running(tmp_path,monkeypatch):
    c = cluster()
    body = '''import json,os,pathlib,sys,time
run=pathlib.Path(sys.argv[-1]); node=run/'nodes/0/status.json'; node.parent.mkdir(parents=True)
def write(status):
    temporary=node.with_suffix('.tmp')
    temporary.write_text(json.dumps({'job_id':os.environ['SLURM_JOB_ID'],'status':status,'hardware_verified':True}))
    os.replace(temporary,node)
write('running')
time.sleep(1.5)
write('completed')'''
    _fake_ibrun(tmp_path,monkeypatch,body)
    states = []
    stop = threading.Event()
    def observe():
        while not stop.wait(.03):
            if (tmp_path/'status.json').exists():
                states.append(json.loads((tmp_path/'status.json').read_text()))
    observer = threading.Thread(target=observe)
    observer.start()
    try:
        assert _batch_with_restored_signals(c,tmp_path) == 0
    finally:
        stop.set()
        observer.join(timeout=2)
    assert any(s['status']=='running' and s['hardware_verified'] for s in states)
