import base64
import gzip
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/data-capacity'


def test_published_report_matches_manifest_and_all_inventories():
    manifest = json.loads((REPORTS / 'manifest.json').read_text())
    checksum = manifest.pop('manifest_sha256')
    raw = json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest() == checksum
    report = json.loads((REPORTS / 'capacity_report.json').read_text())
    assert report['datasets'] == manifest['datasets']
    assert len(report['datasets']) == 29
    assert report['selected_bytes'] == sum(x['bytes'] for x in manifest['files']) == 2556757642643
    assert len(manifest['files']) == 4902
    assert sum(x['selected_bytes'] is not None for x in report['datasets']) == 16
    assert sum(x['status'] == 'inventoried' for x in report['datasets']) == 7
    assert report['starter_selected_bytes'] == 1653563899540
    assert report['audit_counts'] == {'blocked':2,'inventoried':7,'not_generated':1,'partial':2,'planned':16,'published':1}
    assert not any(x['status'] in ('pending','error') for x in report['datasets'])
    assert set(report['download_unresolved']) == {'ego4d','egoexo4d','scand','panda','howto100m','selfsim'}
    lock = {x['id']:x for x in json.loads((ROOT/'tools/data/datasets.lock.json').read_text())['datasets']}
    selected = {}
    for f in manifest['files']: selected.setdefault(f['dataset'], {})[f['path']] = f
    for row in report['datasets']:
        if row.get('evidence_file'):
            evidence=json.loads((REPORTS/row['evidence_file']).read_text())
            raw=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            assert hashlib.sha256(raw).hexdigest()==row['evidence_sha256']
        if not row.get('inventory_file'): continue
        raw = gzip.decompress((REPORTS/row['inventory_file']).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == row['inventory_sha256']
        snapshot = json.loads(raw)
        assert len(snapshot['files']) == row['scope_files']
        assert sum(f['bytes'] for f in snapshot['files']) == row['scope_bytes']
        if lock[row['id']]['provider'] == 'hf': assert lock[row['id']]['revision'] == row['version']
        if row['id'] in selected:
            names = {f['path']:f for f in snapshot['files']}
            assert all(names[path] == f for path,f in selected[row['id']].items())
        else: assert row['selected_bytes'] is None


def test_html_embedded_assets_match_maintained_source():
    page = (ROOT/'index.html').read_text()
    for attr,path in [('capacity-baseline-json',REPORTS/'capacity_report.json'),('catalog-json',None)]:
        value = re.search(r'<script id="'+attr+r'" type="application/json">(.*?)</script>',page,re.S)[1]
        parsed = json.loads(value)
        if path: assert parsed == json.loads(path.read_text())
        else: assert len(parsed) == 29
    script = re.search(r'<script id="capacity-ui">(.*?)</script>',page,re.S)[1]
    assert script == (ROOT/'scripts/capacity-ui.js').read_text()
    blob = re.search(r'href="data:application/zip;base64,([^"]+)"',page)[1]
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(blob))) as archive:
        assert archive.testzip() is None
        for path in (ROOT/'tools/data').iterdir():
            if path.is_file(): assert archive.read(path.name) == path.read_bytes()
        assert json.loads(archive.read('audit/capacity_report.json')) == json.loads((REPORTS/'capacity_report.json').read_text())
        assert archive.read('audit/manifest.json') == (REPORTS/'manifest.json').read_bytes()
        for path in (REPORTS/'evidence').glob('*.json'):
            assert archive.read('audit/evidence/'+path.name)==path.read_bytes()
    assert '首批选中文件 · 精确字节小计' in page
    assert '恢复内置核验结果' in page
