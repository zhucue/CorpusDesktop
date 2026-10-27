"""Deployed evidence/note/export acceptance; synthetic policy only, bounded cleanup."""
import argparse
import csv
import hashlib
import io
import json
import secrets
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.private_material_smoke import fixture
from scripts.source_release_smoke import checked
from scripts.source_sync_smoke import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:60636')
    parser.add_argument('--ui-hold-seconds',type=int,default=0)
    parser.add_argument('--hold-browser',action='store_true')
    parser.add_argument('--credentials-stdin',action='store_true')
    args=parser.parse_args()
    if args.hold_browser and not args.ui_hold_seconds:
        args.ui_hold_seconds=900
    if not 0 <= args.ui_hold_seconds <= 900:
        parser.error('UI hold must be between 0 and 900 seconds')
    password=json.load(sys.stdin)['password'] if args.credentials_stdin else secrets.token_urlsafe(32)
    if not isinstance(password,str) or len(password)<16:
        parser.error('A test password of at least 16 characters is required')
    tag=uuid4().hex
    body={'source_id':'fixture-release-'+tag,'accounts':{
        role:{'id':str(uuid4()),'email':f'outcomes-{role}-{tag}@example.test','password':password}
        for role in ('admin','owner','editor','viewer','outsider')}}
    output=ROOT/'tmp/outcomes-smoke'/tag
    output.mkdir(parents=True)
    families=('evidence_actions','evidence','evidence_lists','note_actions','notes','note_lists',
              'export_actions','exports','export_lists','policy_actions','policies',
              'negative_checks','queries','snapshots','downloads')
    report={'status':'running','started_at':datetime.now(UTC).isoformat(),'fixture_only':True,
            'source_id':body['source_id'],'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            **{name:[] for name in families}}
    clients={}

    def save():
        (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')

    def request(who,method,path,data=None,*,expected=200,record=None,key=None):
        client,csrf=clients[who]
        headers={'Origin':args.base_url,'X-CSRF-Token':csrf}
        if method!='GET':
            headers['Idempotency-Key']=key or uuid4().hex
        response=client.request(method,'/api/v1'+path,json=data if method!='GET' else None,headers=headers)
        value=checked(response,expected)
        if record:
            report[record].append(value)
        save()
        return value

    def poll(path,target,record=None):
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            item=request('viewer','GET',path)
            if item['state']==target:
                if record:
                    report[record].append(item)
                    save()
                return item
            if item['state'] in {'FAILED','CANCELLED'}:
                report['failed_task']=item
                save()
                raise RuntimeError('OUTCOME_DEPENDENCY_FAILED')
            time.sleep(.25)
        raise RuntimeError('OUTCOME_DEPENDENCY_TIMEOUT')

    def hold(label):
        if args.ui_hold_seconds:
            marker=output/label
            print('UI_HOLD '+str(marker),flush=True)
            deadline=time.monotonic()+args.ui_hold_seconds
            while time.monotonic()<deadline and not marker.exists():
                time.sleep(1)

    try:
        report['fixture']=fixture('setup',body)
        for role,account in body['accounts'].items():
            client=httpx.Client(base_url=args.base_url,timeout=30)
            login=checked(client.post('/api/v1/auth/login',headers={'Origin':args.base_url},
                                      json={'email':account['email'],'password':password}),200)
            clients[role]=client,login['csrf_token']
        project=request('owner','POST','/projects',{'name':'成果验收 '+tag[:8]},expected=201)
        project_id=project['id']
        base=f'/projects/{project_id}'
        report['project_id']=project_id
        request('owner','PUT',base+'/members/'+body['accounts']['viewer']['id'],{'role':'viewer'})
        version=report['fixture']['versions'][0]
        policy_path=f"/admin/sources/{body['source_id']}/policies/{version['acquisition_id']}"

        def policy(export,decision='allow'):
            current=request('admin','GET',policy_path,record='policies')
            return request('admin','POST',policy_path,
                {'expected_revision':current['revision'],'decision':decision,'export_decision':export,
                 'review_note':'Authored outcome fixture only; no real Tatoeba approval',
                 'evidence_urls':['https://example.test/outcomes-fixture']},record='policy_actions')['policy']

        approved=policy('deny')
        release=request('admin','POST',f"/admin/sources/{body['source_id']}/releases",
            {'index_id':version['index_id'],'expected_policy_revision':approved['revision']},expected=201)['release']
        mounted=request('owner','POST',base+'/mounts',{'source_snapshot_id':release['source_snapshot_id']},expected=201)
        mount_id=mounted['mount']['id']
        revisions=[]
        canonical={}
        for filename,raw in [('unicode-first.txt',b'\xef\xbb\xbf'+'Hello.\r\nHello 😀 é.\nHello!'.encode()),
                             ('second-file.txt',b'Hello.\r\nHello!')]:
            uploaded=request('owner','POST',base+'/uploads',{'filename':filename,'size':len(raw),
                'sha256':hashlib.sha256(raw).hexdigest(),'media_type':'text/plain'},expected=201)
            client,csrf=clients['owner']
            checked(client.put(uploaded['upload_url'],content=raw,headers={
                'Origin':args.base_url,'X-CSRF-Token':csrf,'Content-Type':'text/plain'}),200)
            validation=request('owner','POST',f"/uploads/{uploaded['upload_id']}/complete",{},expected=202)
            poll('/jobs/'+validation['job_id'],'SUCCEEDED')
            imported=request('owner','POST',base+'/imports',{'upload_id':uploaded['upload_id'],'language':'eng'},expected=202)
            result=poll(base+'/imports/'+imported['import_id'],'SUCCEEDED')
            revisions.append(result['result']['id'])
            canonical[result['material_id']]=raw.decode('utf-8-sig')
        runs={}
        for name,mounts in [('private',[]),('mixed',[mount_id])]:
            created=request('owner','POST',base+'/snapshots',
                            {'mount_ids':mounts,'material_revision_ids':revisions},expected=202)
            snapshot=poll(base+'/snapshots/'+created['snapshot']['id'],'READY','snapshots')
            ast={'dsl_version':'corpus-query/v1','unit':'character','within':'sentence','overlap':'all',
                 'pattern':{'type':'literal','value':'Hello'}}
            action=request('viewer','POST',base+'/queries',{'snapshot_id':snapshot['id'],'query':ast,'page_size':50},expected=202)
            run=poll(base+'/queries/'+action['query_run_id'],'SUCCEEDED','queries')
            assert (run['total_hits'],run['matched_segments'],run['matched_documents'])==((5,5,2) if name=='private' else (125,65,62))
            runs[name]=run
        zero=request('viewer','POST',base+'/queries',{'snapshot_id':runs['mixed']['snapshot_id'],
            'query':{**ast,'pattern':{'type':'literal','value':'missing-outcomes-phrase'}},'page_size':50},expected=202)
        runs['zero']=poll(base+'/queries/'+zero['query_run_id'],'SUCCEEDED','queries')
        assert runs['zero']['total_hits']==0
        report['run_ids']={k:v['id'] for k,v in runs.items()}
        evidence=[]
        for ordinal in (0,124):
            action=request('owner','POST',base+'/evidence',{'result_set_id':runs['mixed']['result_set_id'],'ordinal':ordinal},expected=201,record='evidence_actions')
            detail=request('viewer','GET',base+'/evidence/'+action['evidence']['id'],record='evidence')
            context=detail['context']
            assert context['text'][context['start_cp']-context['context_start_cp']:context['end_cp']-context['context_start_cp']]=='Hello'
            evidence.append(detail)
        request('viewer','GET',base+'/evidence',record='evidence_lists')
        request('viewer','POST',base+'/evidence',{'result_set_id':runs['mixed']['result_set_id'],'ordinal':1},expected=403,record='negative_checks')
        request('outsider','GET',base+'/evidence/'+evidence[0]['id'],expected=404,record='negative_checks')
        note=request('owner','POST',base+'/notes',{'title':'=固定研究笔记','body':'原解释\r\n"Hello" 与 😀 é',
            'evidence_ids':[e['id'] for e in evidence],'query_run_ids':[runs['zero']['id']]},expected=201,record='note_actions')['note']
        accepted=request('owner','POST',base+'/notes/'+note['id']+'/accept',{'expected_revision':1},record='note_actions')['note']
        assert accepted['status']=='accepted'
        revised=request('owner','PATCH',base+'/notes/'+note['id'],
            {'expected_revision':1,'title':'第二版研究笔记','body':'更新解释；移除显示引用不移除授权依赖。','evidence_ids':[],'query_run_ids':[]},record='note_actions')['note']
        assert revised['status']=='draft' and len(revised['authorization_evidence_ids'])==2
        request('owner','PATCH',base+'/notes/'+note['id'],{'expected_revision':1,'title':'冲突','body':'不能覆写'},expected=409,record='negative_checks')
        old=request('viewer','GET',base+'/notes/'+note['id']+'?revision=1',record='notes')
        assert old['body']==note['body'] and old['status']=='accepted'
        request('viewer','GET',base+'/notes',record='note_lists')
        request('viewer','GET',base+'/notes/'+note['id']+'/revisions',record='note_lists')
        request('viewer','POST',base+'/notes',{'title':'无权写','body':'no'},expected=403,record='negative_checks')
        report['note_id']=note['id']
        ordered=[runs[k]['id'] for k in ('mixed','zero','private')]
        target={'kind':'query_runs','query_run_ids':ordered}
        request('viewer','POST',base+'/exports',{'target':target,'format':'json'},expected=403,record='negative_checks')

        def export(target,format,filename):
            action=request('viewer','POST',base+'/exports',{'target':target,'format':format},expected=202,record='export_actions')
            result=poll(base+'/exports/'+action['export_id'],'SUCCEEDED','exports')
            client,_=clients['viewer']
            path=output/filename
            digest=hashlib.sha256()
            total=0
            with client.stream('GET','/api/v1'+base+'/exports/'+action['export_id']+'/download') as response:
                if response.status_code!=200:
                    raise RuntimeError('EXPORT_DOWNLOAD_FAILED')
                assert response.headers['content-type'].split(';')[0]==result['result']['media_type']
                with path.open('xb') as stream:
                    for chunk in response.iter_bytes():
                        total+=len(chunk)
                        if total>8*1024**2:
                            raise RuntimeError('SMOKE_ARTIFACT_TOO_LARGE')
                        digest.update(chunk)
                        stream.write(chunk)
            assert total==result['result']['byte_size'] and digest.hexdigest()==result['result']['sha256']
            report['downloads'].append({'export_id':action['export_id'],'path':str(path.relative_to(ROOT)),
                'bytes':total,'sha256':digest.hexdigest(),'media_type':result['result']['media_type']})
            save()
            return action,path

        private_action,private_path=export({'kind':'query_runs','query_run_ids':[runs['private']['id']]},'json','private.json')
        assert len(json.loads(private_path.read_bytes())['rows'])==5
        policy('allow')
        shared_action,json_path=export(target,'json','mixed.json')
        _,csv_path=export(target,'csv','mixed.zip')
        data=json.loads(json_path.read_bytes())
        assert [m['counts']['total_hits'] for m in data['methods']['queries']]==[125,0,5]
        rows=data['rows']
        assert len(rows)==130 and rows[125]['row_number']==1 and rows[125]['hit_ref']['ordinal']==0
        for row in rows:
            if row['origin_kind']=='private':
                assert row['source_url'] is None and row['owner'] is None
                assert canonical[row['document_id']][row['start_cp']:row['end_cp']]=='Hello'
            else:
                assert row['owner']=='Fixture' and row['license']=='CC-BY-2.0-FR'
                assert row['source_id']==body['source_id'] and row['source_url']
        with zipfile.ZipFile(csv_path) as package:
            assert set(package.namelist())=={'results.csv','methods.json'}
            table=list(csv.DictReader(io.StringIO(package.read('results.csv').decode(),newline='')))
            assert len(table)==len(rows)
            for actual,expected in zip(table,rows):
                for key,value in expected.items():
                    if value is None or value=='':
                        assert actual[key]==''
                    elif type(value) in (int,float):
                        assert actual[key]==str(value)
                    elif isinstance(value,str):
                        assert actual[key][1:]==value and actual[key].startswith("'")
                    else:
                        assert json.loads(actual[key][1:])==value
        _,note_path=export({'kind':'note_revision','note_id':note['id'],'revision':1},'json','note.json')
        note_data=json.loads(note_path.read_bytes())['rows'][0]
        assert note_data['body']==note['body'] and note_data['status']=='accepted'
        assert {ref['id']:ref['context'] for ref in note_data['evidence_refs']}=={ref['id']:ref['context'] for ref in evidence}
        _,zero_path=export({'kind':'query_runs','query_run_ids':[runs['zero']['id']]},'json','zero.json')
        assert json.loads(zero_path.read_bytes())['rows']==[]
        request('viewer','GET',base+'/exports',record='export_lists')
        report['status']='passed'
        report['ui_accounts']={role:{'id':a['id'],'email':a['email']} for role,a in body['accounts'].items()}
        report['mixed_export_id']=shared_action['export_id']
        report['private_export_id']=private_action['export_id']
        save()
        hold('continue')
        policy('deny')  # Independent export withdrawal; fulltext remains allowed.
        request('viewer','GET',base+'/exports/'+shared_action['export_id']+'/download',expected=403,record='negative_checks')
        page=request('viewer','GET',base+'/result-sets/'+runs['mixed']['result_set_id']+'/hits')
        assert page['total_hits']==125
        # Pure-private export remains downloadable after a shared source export denial.
        client,_=clients['viewer']
        response=client.get('/api/v1'+base+'/exports/'+private_action['export_id']+'/download')
        assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==hashlib.sha256(private_path.read_bytes()).hexdigest()
        report['export_withdrawal_verified']=True
        save()
        hold('revoked-continue')
        policy('deny',decision='deny')
        request('viewer','GET',base+'/evidence/'+evidence[0]['id'],expected=404,record='negative_checks')
        request('viewer','GET',base+'/notes/'+note['id'],expected=403,record='negative_checks')
        report['fulltext_withdrawal_verified']=True
        save()
        hold('fulltext-continue')
    except BaseException as error:
        report['status']='failed'
        report['error_type']=type(error).__name__
        raise
    finally:
        for client,_ in clients.values():
            client.close()
        try:
            report['cleanup']=fixture('cleanup',body)
        finally:
            report['finished_at']=datetime.now(UTC).isoformat()
            save()
            print(str(output/'result.json'),flush=True)


if __name__=='__main__':
    main()
