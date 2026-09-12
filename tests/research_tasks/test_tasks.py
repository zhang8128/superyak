"""Portable tasks retain evidence and survive interruption without shared live state."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'atlas'),str(ROOT/'engram')]
from workbench.automation import ResearchInbox


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False))


@pytest.fixture
def source(tmp_path):
    p=tmp_path/'live'
    question={'id':'q-mg','kind':'question','title':'Fictional MG methods question',
              'summary':'What does this fictional study measure?', 'context':{'private':'DO NOT EXPORT'},
              'provenance':{'private':'DO NOT EXPORT'}}
    bundle={'schema_version':1,'title':'Private mixed workspace','sources':[],
            'items':[question,{'id':'private','kind':'question','title':'DO NOT EXPORT','summary':'private'}], 'relations':[]}
    dump(p/'workbench/data/seed.json',bundle)
    dump(p/'workbench/data/lighthouse-automation.json',{'version':1,'bundle':'workbench/data/seed.json','views':{'prediction':'workbench/data/view.json'}})
    dump(p/'workbench/data/view.json',{'issuer':'urn:fixture:mg','name':'Fixture MG','origin':'urn:fixture:origin',
        'context':{'id':'research/mg','path':['research','mg']},'item_ids':['q-mg','private'],'issued_at':'2026-09-12T00:00:00Z','rules':[]})
    passage={'id':'p1','locator':'Fictional methods, paragraph 1','text':'This fictional study measured reported fatigue in ten participants.'}
    doc={'source':{'id':'fixture:mg-1','title':'Fictional MG source','url':'https://example.org/fictional-mg','year':2026,'citation':'Fictional fixture, not clinical evidence'},
         'passages':[passage],'coverage':'abstract_only','coverage_note':'Fictional abstract fixture',
         'retrieved_at':'2026-09-12T00:00:00Z','document_url':'https://example.org/fictional-mg',
         'content_sha256':hashlib.sha256(json.dumps([passage],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    job={'id':'a'*64,'question_id':'q-mg','status':'recorded','document':doc,
         'paper':{'key':'MED:1','provider_source':'MED','provider_id':'1','doi':'','source':deepcopy(doc['source']),'title':doc['source']['title'],'private':'DO NOT EXPORT'},
         'extraction':{'private':'DO NOT EXPORT'},'session_id':'DO NOT EXPORT'}
    dump(p/'.atlas/research/jobs'/('a'*64+'.json'),job)
    return p,job


def exported(source,tmp_path):
    from research_tasks.packet import export_task
    p=tmp_path/'task.json'
    export_task(source[0],'q-mg','a'*64,p)
    return p


class Model:
    model='scripted-fixture'
    def __init__(self, verdict='supported', quote=None):
        self.calls=[]; self.verdict=verdict; self.quote=quote; self.last_response=None
    def extract(self,q,doc,context):
        self.calls.append('extract')
        assert context==[]
        self.last_response={'message':{'role':'assistant','content':'raw extraction','reasoning_content':'retained state'}}
        return {'model':self.model,'context_manifest':{'selected_record_ids':[], 'selected_passage_ids':['p1'], 'omitted_passages':0},'metrics':{},'analysis':{'relevant':True,'title':'Fictional fatigue observation',
            'summary':'A fictional study measured reported fatigue.','scope':'Fictional fixture only.',
            'limitations':'No treatment effect was established.','passage_id':'p1',
            'quote':self.quote or 'study measured reported fatigue in ten participants',
            'rationale':'This describes a measured endpoint.'}}
    def review(self,q,doc,candidate):
        self.calls.append('review')
        self.last_response={'message':{'role':'assistant','content':'raw review'}}
        return {'model':self.model,'context_manifest':{'selected_record_ids':[], 'selected_passage_ids':['p1'], 'omitted_passages':0},'metrics':{},'analysis':{'verdict':self.verdict,'reason':'The supplied passage supports only the stated endpoint.','evidence':[{'passage_id':'p1'}]}}


CONFIG={'backend':'scripted','model':'scripted-fixture','model_revision':'sha256:'+'1'*64,'endpoint':'fixture','protocol':'research','output_tokens':1800,'timeout':120,'seed':0,'reasoning_effort':None}


def run(packet,output,model):
    from research_tasks.runner import run_task
    return run_task(packet,output,model,config=CONFIG)


def test_export_selects_one_question_source_and_no_private_state(source,tmp_path):
    from research_tasks.packet import load_task
    before={str(p):p.read_bytes() for p in source[0].rglob('*') if p.is_file()}
    p=exported(source,tmp_path); task=load_task(p)
    assert task['question']['id']=='q-mg'
    assert task['document']['passages'][0]['locator']=='Fictional methods, paragraph 1'
    assert 'DO NOT EXPORT' not in p.read_text()
    assert task['provenance']['historical_prompt_replay'] is False
    assert all(Path(p).read_bytes()==content for p,content in before.items())


@pytest.mark.parametrize('problem',['question','passage','metadata','duplicate','nonterminal'])
def test_invalid_selection_or_changed_evidence_fails_before_export(source,tmp_path,problem):
    from research_tasks.packet import export_task
    project,job=source
    if problem=='question': job['question_id']='wrong'
    elif problem=='passage': job['document']['passages'][0]['text']='A modified source.'
    elif problem=='metadata': job['document']['source']['id']='different-from-paper'
    elif problem=='duplicate': job['document']['passages'].append(deepcopy(job['document']['passages'][0]))
    else: job['status']='pending'
    dump(project/'.atlas/research/jobs'/('a'*64+'.json'),job)
    with pytest.raises(ValueError): export_task(project,'q-mg','a'*64,tmp_path/'bad.json')
    assert not (tmp_path/'bad.json').exists()


def test_packet_tampering_is_detected_even_when_passages_unchanged(source,tmp_path):
    from research_tasks.packet import load_task
    p=exported(source,tmp_path); task=json.loads(p.read_text())
    task['document']['source']['title']='Altered attribution';dump(p,task)
    with pytest.raises(ValueError,match='hash|digest'): load_task(p)


def test_completed_task_replays_offline_and_preserves_artifacts(source,tmp_path):
    packet=exported(source,tmp_path); output=tmp_path/'run'; model=Model()
    result=run(packet,output,model)
    assert result['status']=='recorded' and model.calls==['extract','review']
    assert result['receipt']['publication_status']=='current'
    records=ResearchInbox(output/'project').snapshot()['bundle']['items']
    assert sum(v['kind']=='claim' for v in records)==1
    assert all(v['status']=='proposed' for v in records)
    before={str(p.relative_to(output)):p.read_bytes() for p in output.rglob('*') if p.is_file()}
    class Offline(Model):
        def extract(self,*args): raise AssertionError('Repeated completed model call')
        def review(self,*args): raise AssertionError('Repeated completed review')
    again=run(packet,output,Offline())
    assert again==result
    assert all((output/p).read_bytes()==content for p,content in before.items())
    assert 'retained state' in (output/'calls/extract.response.json').read_text()


def test_resume_after_lost_atlas_receipt_does_not_repeat_calls_or_finding(source,tmp_path,monkeypatch):
    packet=exported(source,tmp_path); output=tmp_path/'run'; model=Model()
    original=ResearchInbox.record
    class Crash(BaseException): pass
    def crash(self,*args,**kwargs):
        original(self,*args,**kwargs)
        raise Crash()
    monkeypatch.setattr(ResearchInbox,'record',crash)
    with pytest.raises(Crash):run(packet,output,model)
    assert model.calls==['extract','review']
    monkeypatch.setattr(ResearchInbox,'record',original)
    result=run(packet,output,model)
    assert model.calls==['extract','review']
    assert result['receipt']['duplicate'] is True
    assert len(list((output/'project/.atlas/drafts').glob('*.json')))==1


@pytest.mark.parametrize('verdict',['unsupported','uncertain'])
def test_failed_source_support_holds_without_publication(source,tmp_path,verdict):
    output=tmp_path/'run'; result=run(exported(source,tmp_path),output,Model(verdict))
    assert result['status']=='held'
    assert not list((output/'project/.atlas/drafts').glob('*.json'))


def test_bad_quote_is_retained_and_never_published(source,tmp_path):
    output=tmp_path/'run';model=Model(quote='an invented passage which does not exist')
    result=run(exported(source,tmp_path),output,model)
    assert result['status']=='invalid' and model.calls==['extract']
    assert 'raw extraction' in (output/'calls/extract.response.json').read_text()
    assert not list((output/'project/.atlas/drafts').glob('*.json'))


def test_unknown_request_outcome_is_not_automatically_repeated(source,tmp_path):
    from research_tasks.runner import TaskError
    class Crash(BaseException): pass
    class Interrupted(Model):
        def extract(self,*args): self.calls.append('extract');raise Crash()
    model=Interrupted();packet=exported(source,tmp_path);output=tmp_path/'run'
    with pytest.raises(Crash):run(packet,output,model)
    with pytest.raises(TaskError,match='uncertain|unfinished'):run(packet,output,model)
    assert model.calls==['extract']


def test_changed_run_configuration_or_saved_response_is_refused(source,tmp_path):
    from research_tasks.runner import run_task
    output=tmp_path/'run';packet=exported(source,tmp_path);model=Model();run(packet,output,model)
    with pytest.raises(ValueError,match='pin|configuration'):
        run_task(packet,output,model,config=CONFIG|{'seed':2})
    p=output/'calls/extract.response.json'; raw=json.loads(p.read_text());raw['payload']['result']['analysis']['summary']='tampered';dump(p,raw)
    with pytest.raises(ValueError,match='hash|digest'): run(packet,output,model)


def test_interrupted_task_refuses_corrupt_saved_reply_without_new_call(source,tmp_path,monkeypatch):
    packet=exported(source,tmp_path); output=tmp_path/'run'; model=Model()
    class Crash(BaseException): pass
    def crash(*args,**kwargs): raise Crash()
    monkeypatch.setattr(ResearchInbox,'record',crash)
    with pytest.raises(Crash):run(packet,output,model)
    response=output/'calls/extract.response.json'
    value=json.loads(response.read_text()); value['payload']['result']['analysis']['summary']='Changed'
    dump(response,value)
    with pytest.raises(ValueError,match='hash'):run(packet,output,model)
    assert model.calls==['extract','review']
    assert not (output/'result.json').exists()


def test_completed_task_refuses_modified_publication(source,tmp_path):
    packet=exported(source,tmp_path); output=tmp_path/'run'; model=Model()
    assert run(packet,output,model)['status']=='recorded'
    page=output/'project/Research/index.html'
    assert page.exists()
    page.write_text('Changed publication')
    with pytest.raises(ValueError,match='hash'):run(packet,output,model)
    assert model.calls==['extract','review']


def test_artifact_json_refuses_duplicate_keys(tmp_path):
    from research_tasks.storage import read
    path=tmp_path/'duplicate.json';path.write_text('{"payload":1,"payload":2}')
    with pytest.raises(ValueError,match='Duplicate'):read(path)


def test_packet_keeps_publication_types_in_both_model_calls(source,tmp_path):
    project,job=source
    job['document']['publication_types']=['Review','Preprint']
    job['paper']['publication_types']=['Review','Preprint']
    dump(project/'.atlas/research/jobs'/('a'*64+'.json'),job)
    class TypedModel(Model):
        def extract(self,q,doc,ctx):
            assert doc['publication_types']==['Review','Preprint']
            return super().extract(q,doc,ctx)
        def review(self,q,doc,candidate):
            assert doc['publication_types']==['Review','Preprint']
            return super().review(q,doc,candidate)
    result=run(exported(source,tmp_path),tmp_path/'run',TypedModel())
    assert result['status']=='recorded', result


def test_abstract_packet_does_not_export_private_search_or_error_text(source,tmp_path):
    from research_tasks.packet import load_task
    project,job=source
    job['document']['document_url']='https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=PRIVATE_QUERY_SENTINEL'
    job['document']['coverage_note']='Full text unavailable (PRIVATE_ERROR_SENTINEL)'
    dump(project/'.atlas/research/jobs'/('a'*64+'.json'),job)
    packet=exported(source,tmp_path);task=load_task(packet)
    assert 'PRIVATE_' not in packet.read_text()
    assert task['document']['document_url']==job['document']['source']['url']
    assert task['document']['content_sha256']==job['document']['content_sha256']


def test_reviewed_source_question_becomes_proposed_task_without_reviewer_identity(source,tmp_path):
    from research_tasks.packet import load_task
    base=source[0]/'workbench/data/seed.json';bundle=json.loads(base.read_text())
    bundle['items'][0].update(status='reviewed',reviewed_by='PRIVATE_REVIEWER',reviewed_at='2026-09-12T00:00:00Z')
    dump(base,bundle)
    packet=exported(source,tmp_path);task=load_task(packet)
    assert task['question']['status']=='proposed'
    assert task['provenance']['source_question_status']=='reviewed'
    assert 'PRIVATE_REVIEWER' not in packet.read_text()
