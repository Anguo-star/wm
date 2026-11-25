#!/usr/bin/env python3
"""Embed the checked-in metadata report and toolkit in the standalone HTML.

Uses only local files. Does not contact data providers or download data.
"""
import base64
import csv
import html
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/data-capacity'
TOOLKIT = ROOT / 'tools/data'


def replace_once(text, pattern, replacement):
    updated, count = re.subn(pattern, lambda _: replacement, text, flags=re.S)
    if count != 1:
        raise ValueError(f'Expected exactly one match, got {count}: {pattern[:100]}')
    return updated


def main():
    page = (ROOT / 'index.html').read_text()
    report = json.loads((REPORTS / 'capacity_report.json').read_text())
    by_id = {x['id']: x for x in report['datasets']}
    catalog_match = re.search(r'<script id="catalog-json" type="application/json">(.*?)</script>', page, re.S)
    catalog = json.loads(catalog_match[1])
    for row in catalog:
        item = by_id.get(row['id'])
        if not item: continue
        row.update(verifiedSelectedBytes=item['selected_bytes'], selectedFileCount=item['files'],
            selectedVersion=item['version'], verifiedScopeBytes=item['scope_bytes'],
            scopeFileCount=item.get('scope_files'), capacityCheckedAt=item.get('checked_at', report['created_at']),
            auxiliaryBytes=item.get('auxiliary_bytes'), registeredBytes=item.get('registered_bytes'),
            publishedApproxBytes=item.get('published_bytes_approx'), verificationNote=item.get('note',''))
        if item['selected_bytes'] is not None:
            row['capacityStatus'] = '远端文件元数据（未下载）' if item['status'] == 'planned' else '本地文件 stat'
            display = f'<strong>{item["selected_bytes"]/1e9:,.3f} GB</strong> · {item["files"]:,} 文件 · {row["capacityStatus"]}'
            display += f'<span class="paper-use">精确 {item["selected_bytes"]:,} bytes；版本 {html.escape(str(item["version"]))}</span>'
        elif item['status'] == 'inventoried':
            row['capacityStatus'] = '完整指定范围已核验'
            display = f'完整指定范围已核验 · {item["scope_bytes"]/1e9:,.3f} GB · {item["scope_files"]:,} 文件；扩展范围单列'
        else:
            row['capacityStatus'] = item.get('verification_label',{'blocked':'无法核验文件清单（访问受限）','not_generated':'尚未生成 · 无现成文件','error':'元数据查询失败','pending':'旧报告未提供核验结果'}.get(item['status'],'可核验部分已完成'))
            display = html.escape(row['capacityStatus'])
            if item.get('registered_bytes') is not None:
                display += f' · {item["registered_bytes"]:,} bytes / {item["registered_files"]} 个容量记录'
            if item.get('auxiliary_bytes') is not None:
                display += f' · {item["auxiliary_bytes"]:,} bytes / {item["auxiliary_files"]} 文件（非视频）'
            if item.get('published_bytes_approx') is not None:
                display += f' · 约 {item["published_bytes_approx"]/1e12:g} TB（非精确字节）'
        if item['scope_bytes'] is not None:
            display += f'<span class="paper-use">核验范围：{item["scope_bytes"]:,} bytes / {item["scope_files"]:,} 文件；{html.escape(str(item["version"]))}；{item.get("checked_at",report["created_at"])[:10]}</span>'
        display += f'<span class="paper-use">{html.escape(item.get("note",""))}</span>'
        page = replace_once(page, rf'<div class="cap-actual" data-cap-id="{row["id"]}">.*?</div>',
            f'<div class="cap-actual" data-cap-id="{row["id"]}">{display}</div>')
    catalog_json = json.dumps(catalog, ensure_ascii=False).replace('</', '<\\/')
    page = replace_once(page, r'<script id="catalog-json" type="application/json">.*?</script>',
        '<script id="catalog-json" type="application/json">' + catalog_json + '</script>')

    # Keep published rounded values as historical references, separate from the audit.
    page = page.replace('明确选定发布包 · 公开值小计', '原规划发布包 · 公开值参考')
    page = page.replace('尚待选文件的首批配额上限', '首批配额上限 · 原规划')
    page = page.replace('逐文件核验后实际选择容量', '首批选中文件 · 精确字节小计')
    starter = [x for x in report['datasets'] if x['phase'] == 'starter']
    selected = [x for x in starter if x['selected_bytes'] is not None]
    total = sum(x['selected_bytes'] for x in selected)
    files = sum(x['files'] for x in selected)
    inventory_count = sum(x['status'] == 'inventoried' for x in report['datasets'])
    page = replace_once(page, r'<b id="cap-selected-total">.*?</b>', f'<b id="cap-selected-total">{total/1e12:.3f} TB</b>')
    page = replace_once(page, r'<span id="cap-selected-detail">.*?</span>',
        f'<span id="cap-selected-detail">首批 {len(selected)} 项 / {files:,} 文件；其他范围与登记/索引容量单列；未下载数据</span>')
    counts=report['audit_counts'];verified=counts.get('planned',0)+counts.get('local',0)+inventory_count
    summary = f'''<div class="lead" id="capacity-audit-summary"><p><strong>{report['created_at'][:10]} 元数据核验：</strong>{verified} 项取得完整指定范围的逐文件容量；其中首批 {len(selected)} 项已固定选择，共 <strong>{total:,} bytes（{total/1e12:.6f} TB）</strong>，{files:,} 个完整文件。扩展范围与首批分别统计，Human-1M 仅指选定完整批次，Molmo2-Cap 仅指该标注仓库。</p><p>SCAND 已核验 DOI 登记的 <strong>344,324,920,157 bytes</strong>，Panda 官方索引已核验 <strong>114,255,340 bytes</strong>；二者均不充当已选训练视频容量。HowTo100M 作者公布预处理视频约 <strong>12 TB</strong>，精确清单需申请账号。Ego4D / Ego-Exo4D 官方清单访问受限；自建仿真尚未生成。</p><p>读取 HF、S3、GCS 文件树、发布清单和 HTTP 响应头，<strong>未读取或保存训练文件正文</strong>。SSv2 的 HEAD 被拒绝，使用流式请求只读 Content-Range 响应头后关闭。公开舍入值、预算和精确文件容量分开显示。</p></div>'''
    if 'id="capacity-audit-summary"' in page:
        page = replace_once(page, r'<div class="lead" id="capacity-audit-summary">.*?</div>', summary)
    else:
        page = page.replace('<div class="table-wrap"><table class="plan-table"><thead><tr><th>首批类别</th>',
            summary + '<div class="table-wrap"><table class="plan-table"><thead><tr><th>首批类别</th>', 1)
    page = page.replace('未选文件的配额上限</th>', '原规划配额上限</th>')
    page = page.replace('尚待明确的文件子集</th>', '原规划待选择项</th>')
    page = page.replace('原规划待选择项</th>', '原规划范围（现状见上方核验目录）</th>')

    page = page.replace('默认只做 plan，不下载大文件。未经授权、没有确切字节数或缺失配套文件的条目保持待定。',
        'plan 只读取元数据，不发送数据文件 GET。公开元数据核验无需声明下载许可；读取到 gated 仓库文件树也不代表已取得内容访问权。下载仍需确认许可并显式执行。没有确切字节数或未选训练子集的条目保持待定。')
    page = page.replace('读取实际文件 size 或 Content-Length/Range 总大小，失败不补估算。生成 manifest.json、files.csv、capacity_report.json。',
        '读取完整分页文件树或 HTTP HEAD 的 Content-Length，失败不补估算，也不以 Range GET 获取数据。生成 manifest.json、files.csv、capacity_report.json 和可复核的压缩文件树快照。')
    page = page.replace('plan 只读取元数据，不发送数据文件 GET。公开元数据核验无需声明下载许可；读取到 gated 仓库文件树也不代表已取得内容访问权。下载仍需确认许可并显式执行。没有确切字节数或未选训练子集的条目保持待定。',
        'plan 只读取清单、登记记录与响应头，不读取或保存训练文件正文。公开元数据核验无需声明下载许可；下载需另行确认许可并显式执行。已核验范围、登记/索引容量、公开舍入值和访问受限项分别标注。')
    page = page.replace('读取完整分页文件树或 HTTP HEAD 的 Content-Length，失败不补估算，也不以 Range GET 获取数据。生成 manifest.json、files.csv、capacity_report.json 和可复核的压缩文件树快照。',
        '读取 HF/S3/GCS 完整分页文件树、发布方清单、DOI 登记或 HTTP 文件长度。SSv2 显式允许流式 Range 请求，仅读取 Content-Range 响应头并关闭，不读取正文。生成 manifest.json、files.csv、capacity_report.json 与压缩文件树证据。')
    page = page.replace('# 先确认各数据许可；必要时先 hf auth login\npython wm_data.py plan --datasets egodex droid bridgev2 libero --approved egodex droid bridgev2 libero --out wm_plan',
        '# 公开元数据核验不下载数据、不接受许可\npython wm_data.py plan --datasets egodex droid bridgev2 libero --out wm_plan\n# 重现本次 HF 固定版本（扩展项只列文件树）\npython wm_data.py plan --config datasets.lock.json --all-datasets --out wm_audit')
    page = page.replace('plan --manual-csv 文件名 --approved 对应ID', 'plan --manual-csv 文件名')
    page = page.replace('Human-1M/AgiBot/Assembly101 大库默认不自动遍历或下载；建议先按任务与完整 episode 清单选取，明确版本、许可与去重规则。',
        '默认 plan 只检查首批；--all-datasets 会额外列出配置中 AgiBot/Assembly101 等发布仓库的完整文件树，可能耗时较长。Human-1M 的 PB 级 bucket 仍需先选任务、episode 与相机范围，未自动遍历。文件树查询不读取视频、图像或训练分片内容。')
    page = page.replace('Human-1M 的 PB 级 bucket 仍需先选任务、episode 与相机范围，未自动遍历。',
        'Human-1M 已选并核验一个完整发布批次（data/meta/videos）；RxR 已核验完整 train pose traces、配套标注与场景包。扩展仓库范围单列，不重复加入首批合计。')
    page = page.replace('清除导入结果</button>', '恢复内置核验结果</button>')
    status = f'内置 {report["created_at"][:10]} 核验快照：{verified} 项逐文件容量、{counts.get("partial",0)} 项登记/索引容量、{counts.get("published",0)} 项公开发布值；{counts.get("blocked",0)} 项清单访问受限、{counts.get("not_generated",0)} 项尚未生成；未下载数据。'
    page = replace_once(page, r'<p class="cap-status" id="cap-import-status" role="status">.*?</p>',
        f'<p class="cap-status" id="cap-import-status" role="status">{status}</p>')

    # Export all new evidence fields with the existing catalog CSV action.
    if "['verifiedScopeBytes'" not in page:
        page = page.replace("['selectedFileCount', '核验文件数'],", "['selectedFileCount', '核验文件数'],\n      ['verifiedScopeBytes', '核验仓库范围字节'],\n      ['scopeFileCount', '核验仓库范围文件数'],\n      ['capacityCheckedAt', '元数据核验时间'],")
    if "['registeredBytes'" not in page:
        page = page.replace("['capacityCheckedAt', '元数据核验时间'],", "['capacityCheckedAt', '元数据核验时间'],\n      ['registeredBytes', '登记容量字节（非选择容量）'],\n      ['auxiliaryBytes', '索引容量字节（非视频）'],\n      ['publishedApproxBytes', '公开发布近似字节（非精确）'],\n      ['verificationNote', '核验范围说明'],")
    baseline = '<script id="capacity-baseline-json" type="application/json">' + json.dumps(report,ensure_ascii=False).replace('</','<\\/') + '</script>'
    ui = '<script id="capacity-ui">' + (ROOT / 'scripts/capacity-ui.js').read_text() + '</script>'
    if 'id="capacity-baseline-json"' in page:
        page = replace_once(page, r'<script id="capacity-baseline-json".*?</script>', baseline)
        page = replace_once(page, r'<script id="capacity-ui">.*?</script>', ui)
    else:
        page = replace_once(page, r"<script>\(\(\)=>\{const \$=id=>document.getElementById\(id\);const ids=\['lc-hours'.*?</script>", baseline + ui)

    # The archive is deterministic and contains source, exact selection and report.
    # Large all-repository inventories remain separate in reports/data-capacity.
    fields = list(dict.fromkeys(k for row in catalog for k in row))
    with (TOOLKIT / '数据容量核查表.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(catalog)
    archive_files = [(p.name,p) for p in TOOLKIT.iterdir() if p.is_file()]
    archive_files += [('audit/'+name,REPORTS/name) for name in ['capacity_report.json','manifest.json','files.csv','access_checks.json']]
    archive_files += [('audit/evidence/'+p.name,p) for p in (REPORTS/'evidence').glob('*.json')]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,path in sorted(archive_files):
            info = zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0)); info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info,path.read_bytes())
    encoded = base64.b64encode(buffer.getvalue()).decode()
    page = replace_once(page, r'href="data:application/zip;base64,[^"]+"', f'href="data:application/zip;base64,{encoded}"')
    report_encoded = base64.b64encode((REPORTS/'capacity_report.json').read_bytes()).decode()
    report_link = f'<a class="toolbtn" id="download-cap-report" download="capacity_report.json" href="data:application/json;base64,{report_encoded}">下载本次容量核验报告（JSON）</a>'
    if 'id="download-cap-report"' in page:
        page = replace_once(page, r'<a class="toolbtn" id="download-cap-report".*?</a>', report_link)
    else:
        page = page.replace('id="download-cap-toolkit">下载数据获取与核验工具包（ZIP）</a>',
            'id="download-cap-toolkit">下载数据获取与核验工具包（ZIP）</a>' + report_link)
    (ROOT/'index.html').write_text(page)
    print(f'Embedded {len(selected)} selected starter datasets / {files} files / {total} bytes; ZIP {len(buffer.getvalue())} bytes')


if __name__ == '__main__': main()
