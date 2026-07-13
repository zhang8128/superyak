import pytest
from storage import Storage
server = pytest.importorskip('server')

def test_operation_schema_and_append(tmp_path):
    s = Storage(str(tmp_path / 'g.db'))
    cols = {r[1] for r in s.conn.execute('pragma table_info(operation_log)')}
    assert cols == {'id','timestamp','operation','session_id','harness','model','repo','target_ids','details','outcome'}
    ident = s.add_operation('remember','sid','codex','m','/repo',['e1'],{'x':1},'success')
    row = s.conn.execute('select operation,session_id,target_ids,details from operation_log where id=?',(ident,)).fetchone()
    assert row['operation'] == 'remember' and row['session_id'] == 'sid'
    s.close()

def test_operation_fail_open(tmp_path):
    s = Storage(str(tmp_path / 'g.db'))
    s.conn.execute('drop table operation_log')
    assert s.add_operation('x','s')
    s.close()

def test_mutation_wrapper_preserves_result_and_logs(monkeypatch):
    class C:
        def execute(self, *args):
            return self

        def fetchone(self):
            return ("codex", "m", "/r")

    class S:
        conn = C()
        def add_operation(self,*args): self.args = args
    st = S(); monkeypatch.setattr(server, '_storage', st); monkeypatch.setattr(server, '_session_id', 'sid')
    @server._mutation_logged
    def fake(item_id): return {'id': item_id, 'ok': True}
    assert fake('x') == {'id':'x','ok':True}
    assert st.args[0] == 'fake'

def test_mutation_wrapper_preserves_exception(monkeypatch):
    monkeypatch.setattr(server, '_storage', None)
    @server._mutation_logged
    def boom(): raise ValueError('x')
    with pytest.raises(ValueError): boom()

@pytest.mark.skipif(server is None, reason='server dependencies unavailable')
def test_wrapper_classifies_domain_failures(monkeypatch):
    class S:
        def add_operation(self,*args): self.args = args
        conn = type('C', (), {'execute': lambda self,*a: type('R', (), {'fetchone': lambda self: ('codex','m','/r')})()})()
    st=S(); monkeypatch.setattr(server,'_storage',st); monkeypatch.setattr(server,'_session_id','s')
    @server._mutation_logged
    def bad(): return {'error':'bad'}
    bad(); assert st.args[7] == 'failure'
    @server._mutation_logged
    def removed(): return {'removed':False}
    removed(); assert st.args[7] == 'failure'

@pytest.mark.skipif(server is None, reason='server dependencies unavailable')
def test_wrapper_extracts_nested_ids(monkeypatch):
    class S:
        def add_operation(self,*args): self.args = args
        conn = type('C', (), {'execute': lambda self,*a: type('R', (), {'fetchone': lambda self: ('codex','m','/r')})()})()
    st=S(); monkeypatch.setattr(server,'_storage',st); monkeypatch.setattr(server,'_session_id','s')
    @server._mutation_logged
    def nested(): return {'anchor_id':'a1','task_context':{'id':'t1'}}
    nested(); assert set(st.args[5]) >= {'a1','t1'}
