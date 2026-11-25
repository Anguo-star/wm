"""Run with Playwright installed; optionally set WM_CHROMIUM_EXECUTABLE."""
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
        assert '23 项完整指定范围已核验' in page.locator('#cap-import-status').inner_text()
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
        with page.expect_download() as download:
            page.locator('#download-data').click()
        csv = Path(download.value.path()).read_text(encoding='utf-8-sig')
        assert '核验仓库范围字节' in csv and '414709277264' in csv

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
        assert not errors, errors
        no_js = browser.new_page(java_script_enabled=False)
        no_js.goto((ROOT/'index.html').as_uri()+'#data-capacity-summary')
        assert no_js.locator('#cap-selected-total').inner_text() == '1.654 TB'
        browser.close()
        print('Browser checks passed: embedded report, partial/invalid imports, reset, escaping, downloads, CSV, calculator, mobile, no-JS.')


if __name__ == '__main__': run()
