(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ids = ['lc-hours','lc-fps','lc-res','lc-tokens','lc-dim','lc-bytes','lc-view','lc-model'];
  function calc() {
    const [h,f,r,t,d,b,v,m] = ids.map(id => $(id).value);
    const n = t === 'dense' ? (+r / 16) ** 2 : +t;
    const frame = n * +d * +b, hour = 3600 * +f * frame * +v * +m, total = hour * +h;
    if (!Number.isFinite(total) || [h,f,d,v,m].some(x => x === '' || +x < 0) || +f === 0 || +d === 0 || +v < 1 || +m < 1) {
      $('lc-total').textContent = '参数无效'; return;
    }
    $('lc-total').textContent = (total / 1e12).toLocaleString('zh-CN',{maximumFractionDigits:3}) + ' TB';
    $('lc-hourly').textContent = (hour / 1e9).toFixed(3) + ' GB';
    $('lc-frame').textContent = (frame / 1e6).toFixed(3) + ' MB';
  }
  ids.forEach(id => $(id).addEventListener('input',calc)); calc();
  const baseline = JSON.parse($('capacity-baseline-json').textContent);
  const original = JSON.parse($('catalog-json').textContent);
  const known = new Set(original.map(x => x.id));
  const starter = new Set(baseline.datasets.filter(x => x.phase === 'starter').map(x => x.id));
  const valid = n => Number.isSafeInteger(n) && n >= 0;
  const statuses = new Set(['pending','error','inventoried','planned','local','partial','published','blocked','not_generated']);
  const labels = {partial:'可核验部分已完成',published:'公开发布容量已核对（舍入值）',blocked:'无法核验文件清单（访问受限）',not_generated:'尚未生成 · 无现成文件',error:'元数据查询失败',pending:'旧报告未提供核验结果'};
  const gb = n => (n / 1e9).toFixed(3) + ' GB';
  const tb = n => (n / 1e12).toFixed(3) + ' TB';
  function validate(report) {
    if (report.schema !== 'wm-data-report-v1' || !Array.isArray(report.datasets) || !valid(report.selected_bytes)) throw Error('不支持的容量报告结构');
    const map = new Map(); let sum = 0;
    for (const row of report.datasets) {
      if (!known.has(row.id) || map.has(row.id)) throw Error('未知或重复数据集 ID');
      if (!statuses.has(row.status) || !valid(row.files)) throw Error('文件数或状态不符合规范');
      if (row.scope_bytes != null && !valid(row.scope_bytes)) throw Error('仓库范围字节无效');
      if (row.scope_files != null && !valid(row.scope_files)) throw Error('仓库范围文件数无效');
      for (const field of ['auxiliary_bytes','auxiliary_files','registered_bytes','registered_files','published_bytes_approx']) {
        if (row[field] != null && !valid(row[field])) throw Error('补充容量字段无效');
      }
      if (row.selected_bytes !== null) {
        if (!valid(row.selected_bytes) || row.files < 1 || !['planned','local'].includes(row.status)) throw Error('选择字节或状态不符合规范');
        if (row.scope_bytes != null && row.selected_bytes > row.scope_bytes) throw Error('选择容量超过核验范围');
        sum += row.selected_bytes;
      } else if (row.files !== 0 || ['planned','local'].includes(row.status)) throw Error('未选择条目包含选择文件');
      if (row.status === 'inventoried' && (!valid(row.scope_bytes) || !valid(row.scope_files) || row.scope_files < 1)) throw Error('完整文件树缺少范围统计');
      if (row.status === 'partial' && !valid(row.auxiliary_bytes) && !valid(row.registered_bytes)) throw Error('部分核验缺少容量依据');
      if (row.status === 'published' && !valid(row.published_bytes_approx)) throw Error('发布值缺少容量依据');
      map.set(row.id,row);
    }
    if (!valid(sum) || sum !== report.selected_bytes || !valid(report.transfer_bytes) || report.transfer_bytes > sum) throw Error('汇总字节不一致');
    const starterSum = [...map.values()].filter(x => starter.has(x.id)).reduce((n,x) => n + (x.selected_bytes ?? 0),0);
    if (report.starter_selected_bytes != null && report.starter_selected_bytes !== starterSum) throw Error('首批小计不一致');
    return {map,sum,starterSum};
  }
  function apply(report, builtin = false) {
    const {map,sum,starterSum} = validate(report);
    const rows = original.map(x => ({...x}));
    let selected = 0, files = 0, inventories = 0, starterOK = 0;
    for (const row of rows) {
      const item = map.get(row.id), el = document.querySelector('[data-cap-id="' + row.id + '"]');
      row.verifiedSelectedBytes = null; row.selectedFileCount = null; row.selectedVersion = '';
      row.verifiedScopeBytes = null; row.scopeFileCount = null; row.capacityCheckedAt = '';
      row.auxiliaryBytes = null; row.registeredBytes = null; row.publishedApproxBytes = null; row.verificationNote = '';
      row.capacityStatus = '本报告未覆盖'; el.textContent = '本报告未覆盖，未计入本次小计';
      if (!item) continue;
      row.selectedVersion = String(item.version || '').slice(0,120);
      row.capacityCheckedAt = String(item.checked_at || report.created_at || '').slice(0,50);
      row.verifiedScopeBytes = item.scope_bytes ?? null; row.scopeFileCount = item.scope_files ?? null;
      row.auxiliaryBytes = item.auxiliary_bytes ?? null; row.registeredBytes = item.registered_bytes ?? null;
      row.publishedApproxBytes = item.published_bytes_approx ?? null; row.verificationNote = String(item.note || '').slice(0,700);
      if (item.selected_bytes !== null) {
        selected++; files += item.files; if (starter.has(row.id)) starterOK++;
        row.verifiedSelectedBytes = item.selected_bytes; row.selectedFileCount = item.files;
        row.capacityStatus = item.status === 'local' ? '本地文件 stat' : '远端文件元数据（未下载）';
        el.textContent = '';
        const strong = document.createElement('strong'); strong.textContent = gb(item.selected_bytes);
        el.append(strong,document.createTextNode(' · ' + item.files + ' 文件 · ' + row.capacityStatus));
        const small = document.createElement('span'); small.className = 'paper-use';
        small.textContent = '精确 ' + item.selected_bytes.toLocaleString('zh-CN') + ' bytes；版本 ' + row.selectedVersion;
        el.append(small);
      } else if (item.status === 'inventoried') {
        inventories++; row.capacityStatus = '完整指定范围已核验';
        el.textContent = row.capacityStatus + ' · ' + gb(item.scope_bytes) + ' · ' + item.scope_files + ' 文件；扩展范围单列';
      } else {
        row.capacityStatus = labels[item.status];
        if (valid(item.registered_bytes)) row.capacityStatus = '登记容量已核验';
        if (valid(item.auxiliary_bytes)) row.capacityStatus = '索引容量已核验';
        el.textContent = row.capacityStatus;
        if (valid(item.registered_bytes)) el.append(' · ' + item.registered_bytes.toLocaleString('zh-CN') + ' bytes / ' + item.registered_files + ' 个容量记录');
        if (valid(item.auxiliary_bytes)) el.append(' · ' + item.auxiliary_bytes.toLocaleString('zh-CN') + ' bytes / ' + item.auxiliary_files + ' 文件（非视频）');
        if (valid(item.published_bytes_approx)) el.append(' · 约 ' + tb(item.published_bytes_approx) + '（非精确字节）');
      }
      if (valid(item.scope_bytes)) {
        const scope = document.createElement('span'); scope.className = 'paper-use';
        scope.textContent = '核验范围：' + item.scope_bytes.toLocaleString('zh-CN') + ' bytes' + (valid(item.scope_files) ? ' / ' + item.scope_files + ' 文件' : '') + (item.status === 'inventoried' ? '；版本 ' + row.selectedVersion : '') + '；' + row.capacityCheckedAt.slice(0,10);
        el.append(scope);
      }
      const note = document.createElement('span'); note.className = 'paper-use'; note.textContent = row.verificationNote; el.append(note);
    }
    $('catalog-json').textContent = JSON.stringify(rows);
    $('cap-selected-total').textContent = starterOK ? tb(starterSum) : '待清单';
    $('cap-selected-detail').textContent = '首批 ' + starterOK + ' 项精确选择；所选扩展项 ' + tb(sum - starterSum) + '；其他范围与登记/索引容量单列';
    const count = status => [...map.values()].filter(x => x.status === status).length;
    $('cap-import-status').textContent = (builtin ? '内置核验快照 ' : '已导入 ') + String(report.created_at || '').slice(0,25) + '：' + (selected + inventories) + ' 项完整指定范围已核验；' + count('partial') + ' 项登记/索引已核验；' + count('published') + ' 项发布值已核对；' + count('blocked') + ' 项清单访问受限；' + count('not_generated') + ' 项尚未生成。选中文件 ' + files + ' 个，预计传输 ' + tb(report.transfer_bytes) + '；远端元数据不代表已下载。';
  }
  $('cap-report').addEventListener('change',async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 10 * 1024 * 1024) throw Error('请导入汇总 capacity_report.json，而非完整 manifest');
      apply(JSON.parse(await file.text()));
    } catch (error) { $('cap-import-status').textContent = '导入失败：' + error.message + '；已保留当前结果。'; }
  });
  $('cap-reset').addEventListener('click',() => { $('cap-report').value = ''; apply(baseline,true); });
  apply(baseline,true);
})();
