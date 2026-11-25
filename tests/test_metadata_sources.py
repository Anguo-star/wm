"""Metadata-only fixtures: pagination, scope, size provenance, and version changes."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'tools/data'))
import metadata_sources as sources
import wm_data as wm


class HeadersOnly:
    def __init__(self, status, headers):
        self.status_code=status;self.ok=status<400;self.headers=headers;self.closed=False
    def __enter__(self): return self
    def __exit__(self,*args): self.closed=True
    def raise_for_status(self):
        if not self.ok: raise requests.HTTPError(response=self)
    @property
    def content(self): raise AssertionError('payload must not be read')
    @property
    def text(self): raise AssertionError('payload must not be read')
    @property
    def raw(self): raise AssertionError('payload must not be read')
    def iter_content(self,*args,**kwargs): raise AssertionError('payload must not be read')


def test_ssv2_header_probe_uses_total_and_closes_without_reading(monkeypatch):
    head=HeadersOnly(403,{})
    response=HeadersOnly(206,{'Content-Length':'1','Content-Range':'bytes 0-0/10000000000','ETag':'v1'})
    monkeypatch.setattr(requests,'head',Mock(return_value=head))
    get=Mock(return_value=response);monkeypatch.setattr(requests,'get',get)
    assert wm.http_metadata('https://example.test/archive',allow_get_headers=True)==(10000000000,'v1',None)
    assert head.closed and response.closed
    assert get.call_args.kwargs['stream'] is True
    assert get.call_args.kwargs['headers']['Range']=='bytes=0-0'


def test_gcs_pages_exclude_placeholders_and_pin_generation(monkeypatch):
    calls=[]
    pages=[{'items':[{'name':'train/','size':'0'},{'name':'train/a','size':'7','generation':'11'}],'nextPageToken':'next'},
           {'items':[{'name':'train/b','size':'9','generation':'12'}]}]
    def get(url,params=None):
        calls.append(dict(params));return Mock(json=lambda:pages[len(calls)-1])
    monkeypatch.setattr(sources,'metadata_get',get)
    files,_=sources.gcs_entries({'id':'test','bucket':'example','prefix':'train/'})
    assert sum(f['bytes'] for f in files)==16 and len(files)==2
    assert calls[1]['pageToken']=='next'
    assert files[1]['url'].endswith('?generation=12')


def test_s3_requires_all_pages_and_records_etag(monkeypatch):
    xml=lambda body: ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'+body+'</ListBucketResult>').encode()
    obj=lambda key,size: f'<Contents><Key>{key}</Key><Size>{size}</Size><ETag>etag-{key}</ETag></Contents>'
    replies=[xml(obj('train/a',7)+'<IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken>'),
             xml(obj('train/b',9)+'<IsTruncated>false</IsTruncated>')]
    calls=[]
    def get(url,params=None):
        calls.append(dict(params));return Mock(content=replies[len(calls)-1])
    monkeypatch.setattr(sources,'metadata_get',get)
    files,_=sources.s3_entries({'id':'test','bucket':'example','prefix':'train/'})
    assert sum(f['bytes'] for f in files)==16
    assert calls[1]['continuation-token']=='next' and files[0]['etag']=='etag-train/a'


def test_mutable_human_bucket_requires_complete_batch_and_rechecks_hash(monkeypatch):
    files=[{'type':'file','path':'release/batch/'+part+'/file','size':5,'xetHash':'old'} for part in ['data','meta','videos']]
    monkeypatch.setattr(sources,'metadata_get',lambda *a,**kw: Mock(json=lambda:files,links={}))
    rows,_=sources.bucket_entries({'id':'human','bucket':'owner/bucket','prefix':'release/batch'})
    assert len(rows)==3
    changed=[{'path':rows[0]['path'],'size':5,'xetHash':'new'}]
    monkeypatch.setattr(requests,'post',Mock(return_value=Mock(json=lambda:changed)))
    with pytest.raises(RuntimeError,match='changed'):sources.verify_bucket_identity(rows[0])
    files.pop()
    with pytest.raises(ValueError,match='incomplete'):sources.bucket_entries({'id':'human','bucket':'owner/bucket','prefix':'release/batch'})


def test_epic_train_allowlist_excludes_other_splits():
    files=[{'path':p,'bytes':n} for p,n in [('meta.csv',1),('release/P01_001.MP4',6),('release/P01_002.MP4',3)]]
    result=wm.select_hf(files,{'mode':'budget','files':['meta.csv'],'budget_bytes':10,
        'include_regex':r'.*\.MP4','allowed_video_ids':['P01_001']})
    assert [f['path'] for f in result]==['meta.csv','release/P01_001.MP4']


def test_registry_aggregate_never_fabricates_doi_file_mapping(monkeypatch):
    attrs={'version':'5.2','sizes':['7','9'],'relatedIdentifiers':[{'relationType':'HasPart','relatedIdentifier':'one-doi'}]}
    monkeypatch.setattr(sources,'metadata_get',lambda *a,**kw:Mock(json=lambda:{'data':{'attributes':attrs}}))
    monkeypatch.setattr(sources,'probe_headers',lambda *a,**kw:{'status':403})
    result,evidence=sources.audit_metadata({'id':'scand','audit_kind':'registry','primary_metadata_url':'https://example.test',
        'registry_url':'https://example.test/doi','unit_evidence':[],'note':'Registry only'},wm.http_item)
    assert result['registered_bytes']==16 and result['registered_files']==2
    assert result['status']=='partial' and 'selected_bytes' not in result and 'scope_bytes' not in result
    assert evidence['registered_file_sizes_bytes']==[7,9] and len(evidence['related_file_dois'])==1
    assert 'files' not in evidence


def test_budget_selection_keeps_full_provider_inventory(tmp_path,monkeypatch):
    import argparse,gzip
    entries=[{'dataset':'test','path':x,'bytes':n,'kind':'http','url':'https://example.test/'+x} for x,n in [('train/a',7),('test/b',9)]]
    monkeypatch.setitem(sources.PROVIDERS,'s3',lambda spec:(entries,'v1'))
    config=tmp_path/'config.json';config.write_text(json.dumps({'datasets':[{'id':'test','name':'Test','phase':'starter',
        'provider':'s3','mode':'filtered','include_regex':'train/.*'}]}))
    out=tmp_path/'plan'
    args=argparse.Namespace(config=str(config),datasets=None,all_datasets=True,manual_csv=None,local=None,out=str(out))
    assert wm.plan(args)==0
    report=json.loads((out/'capacity_report.json').read_text());row=report['datasets'][0]
    assert row['selected_bytes']==7 and row['scope_bytes']==16
    assert len(json.loads(gzip.decompress((out/row['inventory_file']).read_bytes()))['files'])==2
