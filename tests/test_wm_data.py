import argparse
import gzip
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wm_data', ROOT / 'tools/data/wm_data.py')
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)


def args_for(tmp_path, config):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'datasets': config}))
    return argparse.Namespace(config=str(path), datasets=None, all_datasets=True,
        approved=None, manual_csv=None, local=None, out=str(tmp_path / 'report'))


def test_metadata_plan_requires_no_download_approval(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests, 'get', Mock(side_effect=AssertionError('data GET forbidden')))
    response = Mock(status_code=200, ok=True, headers={'Content-Length': '123', 'Content-Type': 'application/zip'})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    head = Mock(return_value=response)
    monkeypatch.setattr(requests, 'head', head)
    args = args_for(tmp_path, [{'id':'archive','name':'Archive','phase':'starter','provider':'http',
        'items':[{'path':'data.zip','url':'https://example.test/data.zip'}]}])
    assert wm.plan(args) == 0
    report = json.loads((Path(args.out) / 'capacity_report.json').read_text())
    assert report['selected_bytes'] == report['starter_selected_bytes'] == 123
    assert report['data_bytes_downloaded'] == 0
    assert report['datasets'][0]['status'] == 'planned'
    assert head.call_count == 1


def test_unreliable_head_does_not_fall_back_to_data_get(monkeypatch):
    import requests
    response = Mock(status_code=200, ok=True, headers={'Content-Type':'text/html'})
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(requests, 'head', Mock(return_value=response))
    monkeypatch.setattr(requests, 'get', Mock(side_effect=AssertionError('data GET forbidden')))
    with pytest.raises(ValueError, match='HEAD'):
        wm.http_metadata('https://example.test/login')


def test_inventory_does_not_become_selected_training_data(tmp_path, monkeypatch):
    entries = [{'dataset':'extra','path':'video.mp4','bytes':900,'kind':'hf'}]
    monkeypatch.setattr(wm, 'hf_entries', lambda s: (entries,'a' * 40))
    args = args_for(tmp_path, [{'id':'extra','name':'Extra','phase':'expansion',
        'provider':'hf','repo':'owner/data','mode':'inventory'}])
    assert wm.plan(args) == 2
    report = json.loads((Path(args.out) / 'capacity_report.json').read_text())
    row = report['datasets'][0]
    assert row['status'] == 'inventoried' and row['selected_bytes'] is None
    assert row['scope_bytes'] == 900 and report['selected_bytes'] == 0
    raw = gzip.decompress((Path(args.out) / row['inventory_file']).read_bytes())
    assert wm.hashlib.sha256(raw).hexdigest() == row['inventory_sha256']
    assert json.loads(raw)['files'] == entries


def test_hf_reads_every_page_at_fixed_commit(monkeypatch):
    import huggingface_hub
    from huggingface_hub.hf_api import RepoFile
    api = Mock()
    api.dataset_info.return_value = Mock(sha='a' * 40)
    api.list_repo_tree.return_value = iter([
        RepoFile(path='a.parquet', size=11, oid='b' * 40),
        RepoFile(path='b.parquet', size=19, oid='c' * 40),
    ])
    monkeypatch.setattr(huggingface_hub, 'HfApi', lambda: api)
    entries, revision = wm.hf_entries({'id':'test','repo':'owner/test'})
    assert sum(x['bytes'] for x in entries) == 30
    assert all(x['revision'] == revision for x in entries)
    api.list_repo_tree.assert_called_once_with('owner/test', repo_type='dataset',
        revision=revision, recursive=True, expand=False)


def test_complete_shards_respect_budget_and_exclude_split_archives():
    entries = [{'path':p,'bytes':n} for p,n in [
        ('meta.csv',10),('OpenVid_part0.zip',60),('OpenVid_part1.zip',50),
        ('OpenVid_part2.zip.part0',20),('OpenVidHD_part0.zip',20)]]
    cfg = {'mode':'budget','files':['meta.csv'],'include_regex':r'OpenVid_part\d+\.zip', 'budget_bytes':80}
    a = wm.select_hf(entries,cfg)
    assert a == wm.select_hf(list(reversed(entries)),cfg)
    assert sum(x['bytes'] for x in a) <= 80
    assert len(a) == 2 and any(x['path'] == 'meta.csv' for x in a)
    assert all(x['path'] in ['meta.csv','OpenVid_part0.zip','OpenVid_part1.zip'] for x in a)


def test_missing_fixed_file_and_duplicate_tree_fail():
    with pytest.raises(ValueError,match='absent'):
        wm.select_hf([],{'mode':'fixed','files':['missing.tar']})
    with pytest.raises(ValueError,match='duplicate'):
        wm.select_hf([{'path':'a','bytes':1}] * 2,{'mode':'all'})


@pytest.mark.parametrize('path',['../outside','/absolute','a/../b','a\\b','a//b','.','C:/bad'])
def test_unsafe_paths_fail(path):
    with pytest.raises(ValueError): wm.safe_path(path)


def test_failure_report_redacts_url_secrets(tmp_path, monkeypatch):
    import requests
    response = Mock(status_code=403)
    error = requests.HTTPError('https://example.test/?token=SECRET',response=response)
    monkeypatch.setattr(wm,'hf_entries',Mock(side_effect=error))
    args = args_for(tmp_path,[{'id':'blocked','name':'Blocked','phase':'starter','provider':'hf'}])
    assert wm.plan(args) == 2
    text = (Path(args.out) / 'capacity_report.json').read_text()
    assert 'SECRET' not in text and '403' in text
    report = json.loads(text)
    assert report['selected_bytes'] == 0 and report['datasets'][0]['selected_bytes'] is None


def test_manifest_tamper_is_rejected(tmp_path):
    body = {'schema':'wm-data-manifest-v1','files':[]}
    body['manifest_sha256'] = wm.digest(body)
    path = tmp_path / 'manifest.json'; wm.write_json(path,body)
    assert wm.load_manifest(path)['files'] == []
    body['files'] = [{'bytes':999}]; wm.write_json(path,body)
    with pytest.raises(ValueError,match='integrity'): wm.load_manifest(path)


def test_recon_gzip_header_keeps_archive_bytes(tmp_path, monkeypatch):
    import requests
    compressed = gzip.compress(b'local synthetic fixture, not dataset content')
    row = {'url':'https://example.test/file.tar.gz','path':'file.tar.gz','bytes':len(compressed),
           'etag':'"v1"','last_modified':'today','allowed_content_encodings':['gzip','x-gzip']}
    monkeypatch.setattr(wm,'http_metadata',lambda url, allowed: (len(compressed),'"v1"','today'))
    response = Mock(status_code=200,headers={'Content-Encoding':'x-gzip','Content-Type':'application/x-gzip','ETag':'"v1"'})
    response.__enter__ = Mock(return_value=response);response.__exit__ = Mock(return_value=None)
    response.raw.stream.return_value = iter([compressed])
    response.iter_content.side_effect = AssertionError('must not auto-decompress archive')
    monkeypatch.setattr(requests,'get',Mock(return_value=response))
    target = tmp_path / 'file.tar.gz'; wm.fetch_http(row,target)
    assert target.read_bytes() == compressed
    response.raw.stream.assert_called_once_with(8 * 1024 * 1024,decode_content=False)


def test_download_still_requires_explicit_license_approval(tmp_path):
    body = {'schema':'wm-data-manifest-v1','pending':[], 'files':[{'dataset':'test','kind':'http','bytes':10}]}
    body['manifest_sha256'] = wm.digest(body)
    path = tmp_path / 'manifest.json';wm.write_json(path,body)
    args = argparse.Namespace(manifest=str(path),dest=str(tmp_path / 'dest'),approved=None,
        allow_partial=False,execute=False)
    with pytest.raises(ValueError,match='missing --approved'): wm.download(args)
