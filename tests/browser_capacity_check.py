"""Run with Playwright installed; optionally set WM_CHROMIUM_EXECUTABLE."""
import csv as csv_module
import io
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    report = json.loads((ROOT/'reports/data-capacity/capacity_report.json').read_text())
    with sync_playwright() as p:
        options = {'headless':True}
        if os.environ.get('WM_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['WM_CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors = []
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto((ROOT/'index.html').as_uri()+'#data-capacity-summary')
        assert page.locator('#cap-selected-total').inner_text() == '1.654 TB'
        assert '414.709 GB' in page.locator('[data-cap-id="droid"]').inner_text()
        assert '804554' in page.locator('[data-cap-id="agibot2026"]').inner_text()
        assert '19.450 GB' in page.locator('[data-cap-id="ssv2"]').inner_text()
        assert '登记容量已核验' in page.locator('[data-cap-id="scand"]').inner_text()
        assert '344,324,920,157' in page.locator('[data-cap-id="scand"]').inner_text()
        assert '索引容量已核验' in page.locator('[data-cap-id="panda"]').inner_text()
        assert '公开发布容量已核对' in page.locator('[data-cap-id="howto100m"]').inner_text()
        assert '尚未生成' in page.locator('[data-cap-id="selfsim"]').inner_text()
        assert '无法核验' in page.locator('[data-cap-id="ego4d"]').inner_text()
        assert '27 项完整指定范围已核验' in page.locator('#cap-import-status').inner_text()
        assert page.locator('#cap-import-status').inner_text().startswith('内置核验快照')
        page.screenshot(path='/tmp/wm-capacity-desktop.png')
        page.evaluate("location.hash = 'data-download-workflow'")

        def upload(data):
            page.locator('#cap-report').set_input_files({'name':'capacity_report.json','mimeType':'application/json',
                'buffer':json.dumps(data).encode()})

        invalid = {**report,'datasets':report['datasets'] + [report['datasets'][0]]}
        upload(invalid)
        page.wait_for_function("document.getElementById('cap-import-status').textContent.startsWith('导入失败')")
        assert page.locator('#cap-selected-total').inner_text() == '1.654 TB'

        libero = next(x for x in report['datasets'] if x['id'] == 'libero')
        partial = {**report,'datasets':[libero],'selected_bytes':libero['selected_bytes'],
            'transfer_bytes':libero['selected_bytes'],'starter_selected_bytes':libero['selected_bytes']}
        upload(partial)
        page.wait_for_function("document.getElementById('cap-selected-total').textContent === '0.004 TB'")
        rows = json.loads(page.locator('#catalog-json').text_content())
        assert next(x for x in rows if x['id'] == 'droid')['verifiedSelectedBytes'] is None
        page.locator('#cap-reset').click()
        assert page.locator('#cap-selected-total').inner_text() == '1.654 TB'

        pending = {**report['datasets'][0],'note':'<img src=x onerror="alert(1)">'}
        injected = {**report,'datasets':[pending],'selected_bytes':0,'transfer_bytes':0,'starter_selected_bytes':0}
        upload(injected)
        page.wait_for_function("document.querySelector('[data-cap-id=ego4d]').textContent.includes('<img')")
        assert page.locator('[data-cap-id="ego4d"] img').count() == 0
        page.locator('#cap-reset').click()

        with page.expect_download() as download:
            page.locator('#download-cap-report').click()
        assert json.loads(Path(download.value.path()).read_text()) == report
        with page.expect_download() as download:
            page.locator('#download-cap-toolkit').click()
        assert Path(download.value.path()).stat().st_size > 100000

        page.evaluate("location.hash = 'dataset-catalog'")
        assert page.locator('#dataset-table tbody tr:visible').count() == 34
        page.locator('#start-only').check()
        assert page.locator('#dataset-table tbody tr:visible').count() == 8
        assert page.locator('#d-genhumanego').is_visible()
        assert not page.locator('#d-hdepic').is_visible()
        page.locator('#start-only').uncheck()
        page.locator('#dataset-search').fill('Gen-HumanEgo')
        assert page.locator('#d-genhumanego').is_visible()
        page.locator('#dataset-search').fill('')
        with page.expect_download() as download:
            page.locator('#download-data').click()
        csv = Path(download.value.path()).read_text(encoding='utf-8-sig')
        assert '核验仓库范围字节' in csv and '414709277264' in csv
        exported = list(csv_module.DictReader(io.StringIO(csv)))
        assert len(exported) == 34
        assert sum(float(row['S1 默认采样百分比']) for row in exported) == 100
        assert next(row for row in exported if row['数据'] == 'Gen-HumanEgo')['S1 默认采样百分比'] == '35'

        page.evaluate("location.hash = 'predictor-data-mix'")
        with page.expect_download() as download:
            page.locator('#download-predictor-plan').click()
        assert json.loads(Path(download.value.path()).read_text()) == json.loads((ROOT/'tools/data/predictor_plan.json').read_text())
        assert 'S0 / S1' in page.locator('#own-data-plan').inner_text()

        page.evaluate("location.hash = 'latent-storage-estimator'")
        page.locator('#lc-hours').fill('1');page.locator('#lc-fps').fill('1')
        page.locator('#lc-view').fill('1');page.locator('#lc-model').select_option('1')
        assert page.locator('#lc-hourly').inner_text() == '1.887 GB'

        page.set_viewport_size({'width':390,'height':844})
        page.evaluate("location.hash = 'data-capacity-summary'")
        page.wait_for_timeout(100)
        assert page.locator('#cap-selected-total').inner_text() == '1.654 TB'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/wm-capacity-mobile.png')
        page.evaluate("location.hash = 'predictor-data-mix'")
        assert page.locator('#download-predictor-plan').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/wm-predictor-mobile.png')
        assert not errors, errors
        no_js = browser.new_page(java_script_enabled=False)
        no_js.goto((ROOT/'index.html').as_uri()+'#data-capacity-summary')
        assert no_js.locator('#cap-selected-total').inner_text() == '1.654 TB'
        browser.close()
        print('Browser checks passed: report imports/reset, escaping, 34-entry catalog, 8-source filter, plan/CSV downloads, calculator, mobile, no-JS.')


if __name__ == '__main__': run()
