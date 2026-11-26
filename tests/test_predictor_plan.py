import base64
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_plan_weights_sources_and_eval_isolation():
    plan=json.loads((ROOT/'tools/data/predictor_plan.json').read_text())
    config=json.loads((ROOT/'tools/data/datasets.json').read_text())
    ids={x['id'] for x in config['datasets']}
    assert plan['status']=='proposed_not_trained'
    for stage in plan['stages']:
        assert set(stage['mixture'])<=ids
        assert sum(stage['mixture'].values())==100
        assert all(v>0 for v in stage['mixture'].values())
        assert not set(plan['evaluation_only']) & set(stage['mixture'])
        assert stage['default_updates']>0 and stage['global_batch_windows']>0
    s1=plan['stages'][1]['mixture'];s2=plan['stages'][2]['mixture']
    assert s1['genhumanego']+s1['egodex']==50
    assert s1['droid']+s1['bridgev2']==30
    assert s2['droid']+s2['bridgev2']+s2['oxe']==60
    assert 'selfsim' not in s2  # not-yet-generated data cannot silently occupy the base mixture
    assert not set(plan['default_zero_sources'])&set(s1)
    assert set(plan['default_zero_sources'])<=ids
    assert {x['id'] for x in plan['optional_sources']}<=ids
    assert sum(plan['robot_condition_mix'].values())==100
    assert plan['robot_condition_mix']['numeric_only']+plan['robot_condition_mix']['numeric_and_verified_text']>=90


def test_html_plan_download_catalog_priorities_and_report_are_consistent():
    page=(ROOT/'index.html').read_text()
    plan=json.loads((ROOT/'tools/data/predictor_plan.json').read_text())
    blob=re.search(r'id="download-predictor-plan"[^>]*href="data:application/json;base64,([^"]+)"',page)[1]
    assert json.loads(base64.b64decode(blob))==plan
    catalog=json.loads(re.search(r'<script id="catalog-json" type="application/json">(.*?)</script>',page,re.S)[1])
    config=json.loads((ROOT/'tools/data/datasets.json').read_text())
    report=json.loads((ROOT/'reports/data-capacity/capacity_report.json').read_text())
    assert {x['id'] for x in catalog}=={x['id'] for x in config['datasets']}=={x['id'] for x in report['datasets']}
    assert {x['id'] for x in catalog if x['priority']=='start'}==set(plan['stages'][1]['mixture'])
    for row in catalog:
        assert row['predictorS1Percent']==plan['stages'][1]['mixture'].get(row['id'],0)
    assert '视频/控制基线：仅真实视频与受控仿真' not in page
    assert '首轮 Predictor 数据选择与采样配方' not in page
    assert 'id="dataset-inclusion-policy"' in page and 'id="matrix-genhumanego"' in page
    actual={x['id']:x for x in report['datasets']}
    assert actual['genhumanego']['scope_bytes']==62035012405416
    assert actual['genhumanego']['scope_files']==44636
    assert actual['genhumanego']['selected_bytes'] is None
    assert actual['openhumanwam']['status']=='partial'
    assert actual['openhumanwam']['auxiliary_bytes']==1538777125
    assert actual['openhumanwam']['selected_bytes'] is None
