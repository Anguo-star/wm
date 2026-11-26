#!/usr/bin/env python3
"""Render the reviewed data shortlist and proposed Predictor recipe into the HTML.

Run this before update_capacity_assets.py. No network or training-data access.
"""
import base64
import html
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
esc=lambda x:html.escape(str(x))


def once(page,pattern,value):
    page,n=re.subn(pattern,lambda _:value,page,flags=re.S)
    if n!=1:raise ValueError(f'Expected one match, got {n}: {pattern[:90]}')
    return page


def table(headers,rows):
    head=''.join('<th scope="col">'+esc(x)+'</th>' for x in headers)
    body=''.join('<tr>'+''.join('<td data-label="'+esc(h)+'">'+v+'</td>' for h,v in zip(headers,row))+'</tr>' for row in rows)
    return '<div class="table-wrap"><table class="plan-table"><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div>'


def external(url,label):
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)} ↗</a>'


def catalog_row(row):
    links=' · '.join(external(x['url'],x['label']) for x in row['links'])
    tag='ready' if row['priority']=='start' else 'later'
    return f'''<tr id="d-{row['id']}" data-category="{row['category']}" data-priority="{row['priority']}"><td data-label="数据集与优先级"><span class="tag {tag}">{esc(row['priorityLabel'])}</span><small class="muted">{esc(row['categoryLabel'])}</small><span class="data-name">{esc(row['name'])}</span><span class="scale">{esc(row['scale'])}</span></td><td data-label="训练用途">{esc(row['use'])}<span class="paper-use">{esc(row['trainingRole'])}</span></td><td data-label="交付与获取"><p>{esc(row['contents'])}</p><details class="access"><summary>获取与来源</summary><p>{esc(row['access'])}</p><span class="paper-links">{links}</span></details></td><td data-label="公开发布容量"><b>{esc(row['publicCapacity'])}</b><span class="paper-use">{esc(row['capacityEvidence'])}</span></td><td data-label="项目选择与实际字节"><p>{esc(row['starterSelection'])}</p><div class="cap-actual" data-cap-id="{row['id']}">由容量快照回填</div></td></tr>'''


def review_html(review):
    policy=''.join('<li>'+esc(x)+'</li>' for x in review['selection_policy'])
    rows=[]
    for r in review['reviews']:
        refs=' · '.join(external(u,f'来源 {i+1}') for i,u in enumerate(r['sources']))
        rows.append([esc(r['name'])+'<br><strong>'+esc(r['decision'])+'</strong>',esc(r['evidence'])+'<span class="paper-use">'+refs+'</span>',esc(r['fit'])+'<span class="paper-use">'+esc(r['availability'])+'</span>'])
    return '<div id="dataset-inclusion-policy"><h4>收录逻辑：监督适配、采用证据与实际可用性</h4><p>这是一份服务本项目的候选集，不是 HF 全目录或行业排行榜。此前容量核验只覆盖旧清单；本轮重新搜集并调整优先级。目录收录、默认训练、下载选择和已到手容量分别记录。</p><ol>'+policy+'</ol><p class="note">证据强度要看任务：直接未来预测、人机迁移、数据集基准、发布者字段说明分别判断。“有论文使用”不是准入硬门槛；新数据可通过受控实验进入。未列出不代表不适用。</p><h4 id="dataset-evidence-review">本轮补搜与用途决策 · '+esc(review['reviewed_at'])+'</h4>'+table(['来源与决定','已有采用 / 效果证据','对本 Predictor 的用途与边界'],rows)+'<p class="note">Open-HumanWAM 的最新预印本提供 Gen-HumanEgo 的直接采用证据，但整套混合与模型的收益不能归因为单个来源。HumanNet、EgoSuite、EgoVerse 先作为合集的原始来源追溯；RH20T 已评估，待力控/触觉任务明确后接入。所有新比例均为本项目待验证方案。</p></div>'


def recipe_html(plan,names):
    s1=plan['stages'][1];s2=plan['stages'][2]
    keys=list(dict.fromkeys([*s1['mixture'],*s2['mixture']]))
    rows=[[f'<a href="#d-{k}">{esc(names[k])}</a>',esc(s1['mixture'].get(k,0))+'%',esc(s2['mixture'].get(k,0))+'%'] for k in keys]
    budgets=[]
    for stage in plan['stages']:
        unique=stage['unique_window_budget'];budget=(f'{unique[0]:,}–{unique[1]:,} 个去重窗口' if unique else '复用清单，增加有效控制/失败窗口；不把重复曝光记成新增数据')
        budgets.append([esc(stage['id']+' · '+stage['name']),budget,f'{stage["default_updates"]:,} 步 × 全局 {stage["global_batch_windows"]} 窗口 = {stage["default_updates"]*stage["global_batch_windows"]:,} 窗口曝光',esc(stage['exit'])])
    optional=[[f'<a href="#d-{r["id"]}">{esc(names[r["id"]])}</a><br>'+esc(r['role']),esc(r['rule'])] for r in plan['optional_sources']]
    gates=''.join('<li>'+esc(x)+'</li>' for x in plan['data_gates'])
    metrics='；'.join(esc(x) for x in plan['evaluation']['metrics'])
    download=base64.b64encode(json.dumps(plan,ensure_ascii=False,indent=2).encode()).decode()
    return f'''<h4 id="predictor-data-mix">新版 Predictor 主训练数据与采样方案</h4>
<p><strong>主线：</strong>先用真实交互视频建立共享时序状态，再强化真实控制响应和多步预测。冻结 V-JEPA 2.1 / DINOv3 单帧 Encoder，50M–150M 专用因果 Predictor 起步；Encoder CPT 并行验证。Gen-HumanEgo 已纳入默认训练候选，优先使用用户已有文件；未取得本地目录前不声称已核验本地下载完整性。</p>
<p class="note">这是 <strong>{esc(plan['version'])} 提案，尚未训练验证</strong>。取代此前“通用视频 25%、导航 10%、再加图像辅助”的首轮混合。优先级依据监督与采用证据，不以发布 TB 大小分配权重；原有公开论文配方仍保留在 4.2 作为参考。</p>
<a class="toolbtn" id="download-predictor-plan" download="predictor_plan.json" href="data:application/json;base64,{download}">下载新版 Predictor 训练配置（JSON）</a>
<p><strong>统计分母：</strong>{esc(plan['sampling_unit'])}。默认一个窗口只选一个主视角，其他视角是增强或独立消融，不把六相机当六倍独立交互。图文与编辑在主训练默认 0%，其潜在语义价值放到独立增量实验。</p>
<figure class="diagram plan-ratio"><div class="plan-ratio-bar" role="img" aria-label="S0和S1：人类交互50%，真实机器人30%，操作语义10%，受控仿真10%"><span style="flex:50;background:#157a6e">50%</span><span style="flex:30;background:#65518c">30%</span><span style="flex:10;background:#327090">10%</span><span style="flex:10;background:#738895">10%</span></div><figcaption>S0 / S1：人类交互 50% · 真实机器人 30% · 操作语义 10% · 受控仿真 10%。S2 改为 20% / 60% / 5% / 15%。</figcaption></figure>
{table(['数据来源','S0 / S1 来源概率','S2 来源概率'],rows)}
<p class="note">OXE 只从已核验、与 DROID/Bridge 不重复的版本中取有效 train；不能把合集和单源直接相加。机器人与仿真中的动作必须经过单位、坐标、控制区间和执行时序验证；不满足条件的窗口不占动作配额。</p>
<h4 id="predictor-stage-budget">阶段预算与退出条件</h4>
{table(['阶段','有效数据预算','更新 / 曝光建议','退出条件'],budgets)}
<p class="note">{esc(plan['update_budget_note'])}。S0 的 100k–300k 是去重窗口数，1.28M 是重复训练曝光数，二者不可混写。S1 从同质量的小集增量到 1M–3M；不足时停在已验证规模，不靠提高重复次数声称数据扩展。</p>
<h4>时间轴、监督与条件使用</h4>
{table(['环节','具体设计'],[
['单帧状态与窗口','默认 256px、8 历史帧 + 8 未来帧、4fps，约 2 秒历史 / 2 秒预测。快速手部/接触可用 8fps 同帧数短时窗，显式提供 Δt。Bridge 等低频动作按原控制区间对齐，不插值伪造控制；不同帧率单列评测。'],
['主目标','冻结同一定义的 target Encoder；按有效未来 token 归一化预测损失。先 teacher forcing 单步/短步，再在 S2 增加 2/4/8 步展开。手部/深度等读出是带质量 mask 的辅助监督；起步先做无辅助基线。'],
['机器人条件','具备等价文本的机器人窗口：数值-only 70%、数值+文本 20%、文本-only 5%、被动 5%；至少 90% 保留数值动作条件。没有可信文本时，文本配额退回数值-only，不生成事后条件。每次采样选择一种模式，不把条件副本当新增轨迹。'],
['人类条件',esc(plan['human_condition_rule'])+' Gen-HumanEgo 的 DFM 使用多视角与时序重建；离线重建结果可作为目标辅助，历史输入须另验因果性。'],
['语言泄漏','先区分已知动作/等价指令、历史描述、任务愿望与事后结果。成功字段、未来子任务描述和目标帧不得进入预测输入；可供目标监督或结果读出。对文本做交换/去除对照，并检查固定控制换无关目标的不变性。'],
['历史与反事实','普通成功示范可训练记忆，但不能证明隐藏物理参数辨识。真实同初态分支/不同动力学证据生成后才启用 5% 历史分支配额；当前 selfsim 尚未生成，因此不预先占默认混合。']])}
<h4>增量数据与专项适配</h4>
{table(['候选与作用','接入规则'],optional)}
<p><strong>S3 · 导航：</strong>复用共享状态空间，先单独适配 RECON 的路径/里程计预测；拿到 SCAND 可用控制清单后再加命令条件。RxR 用于语义路径与场景，不冒充底层命令。专项初始建议 80% 导航有效窗口 + 20% S1 交互回放；没有有效控制记录时，只报告路径条件或被动导航能力。</p>
<p><strong>S3 · 语言接口：</strong>Molmo / LLaVA-Video、图文和编辑用于状态读出或单独辅助训练。FineVideo/OpenVid 最多先替换 5 个百分点人类/语义窗口做覆盖实验；编辑/图文分别单独测试，机器人窗口曝光保持固定。S4 再用候选动作与真实执行结果验证系统净收益，不根据预测视频是否好看决定接入。</p>
<h4 id="predictor-data-ablation">最小实验矩阵：数据是否真的有用</h4>
{table(['实验','固定项与唯一主要变化','判断'],[
['A · 控制基线','DROID / Bridge / LIBERO / RoboCasa；机器人/仿真窗口及曝光固定。','建立无额外人类数据的动作响应与下游基线。'],
['B · 加用户已有 Gen-HumanEgo','在 A 相同控制曝光上加入 Gen-HumanEgo；与增加控制重复曝光的同总 token 对照比较。','验证人类交互内容的贡献，不能仅因算力增加就归因数据。'],
['C · 人类来源互补','在 B 的固定人类预算内，比较 Gen-only、Gen+EgoDex 与 S1 全部默认来源；同分组留出。','检验多样性与来源互补；每项同时报告源内和源外表现。'],
['D · 结构化监督','固定 C 的视频和预算，依次加入手部/深度辅助、可信语义条件、多视角。','逐项归因；目标 mask 失真或动作退化则禁用对应增强。'],
['E · 规模化与新库','HoloAssist、Human-1M 或 Open-HumanWAM 每次仅加入一种；替换同层样本，清除重叠源 episode。','先小子集等预算，再扩大；近重复数据不算新覆盖。'],
['F · 辅助与历史','通用视频、编辑、图文各自独立对照；历史用匹配/错配/无历史的真实分支。','不将静态理解提升或低 latent loss 当作物理预测提升。']])}
<p class="note">A/B 需同时报告“同控制曝光”与“同总计算量”两种对照；新增人类数据带来的计算开销单列。正式结论用 {plan['evaluation']['seeds']} 个种子与置信区间；S0 可以先单种子筛查，不能据此声称稳定提升。</p>
<h4 id="predictor-transfer-eval">数据门槛与评测</h4><ol>{gates}</ol>
<p>评测：{metrics}。{esc(plan['evaluation']['comparison_rule'])} {esc(plan['evaluation']['noninferiority_margin'])}</p>
<p><strong>评测隔离：</strong>验证集用于选型；HD-EPIC 整体保留作最终诊断，HoloAssist 按官方 split，DROID/Bridge 按会话、任务/场景留出。最终测试集不进入训练、归一化统计、数据筛选阈值拟合或超参选择。报告区分“特征预测”“物理读出”“策略成功率”和“真机闭环”，不跨设置拼排行榜。</p>
<p class="note">来源证据与接入决定见 <a href="#dataset-evidence-review">4.3 补搜记录</a>。本轮完成的是规划、元数据核验和报告更新，未运行 Predictor 训练、未下载训练文件。</p>
'''


def main():
    page=(ROOT/'index.html').read_text()
    plan=json.loads((ROOT/'tools/data/predictor_plan.json').read_text())
    review=json.loads((ROOT/'reports/predictor-data-review.json').read_text())
    additions=json.loads((ROOT/'reports/catalog_additions.json').read_text())
    match=re.search(r'<script id="catalog-json" type="application/json">(.*?)</script>',page,re.S)
    catalog=json.loads(match[1]);by_id={x['id']:x for x in catalog};new_ids=set()
    for addition in additions:
        if addition['id'] not in by_id:
            row={**addition,'publicSelectedGB':None,'planningCapGB':None,'verifiedSelectedBytes':None,'selectedFileCount':0,'selectedVersion':None,'capacityStatus':'','sizeSourceUrl':addition['links'][0]['url']}
            catalog.append(row);by_id[row['id']]=row;new_ids.add(row['id'])
    active=plan['stages'][1]['mixture'];optional={x['id']:x['role'] for x in plan['optional_sources']}
    for row in catalog:
        k=row['id'];row['priority']='start' if k in active else 'expand'
        row['priorityLabel']='默认主训练' if k in active else ('独立评测' if k in plan['evaluation_only'] else '按需接入')
        row['trainingRole']=f'S1 默认 {active[k]}%' if k in active else optional.get(k,'独立评测，主训练 0%' if k in plan['evaluation_only'] else '默认 S1 为 0%；强化/专项或增量验证后接入')
        row['predictorS1Percent']=active.get(k,0);row['categoryLabel']={'ego':'第一视角','robot':'机器人与仿真'}.get(row['category'],row.get('categoryLabel',''))
        row['sourceUrls']=' | '.join(x['url'] for x in row['links'])
        if k in new_ids:continue
        pattern=r'<tr\b[^>]*\bid="d-'+re.escape(k)+r'"[^>]*>.*?</tr>'
        m=re.search(pattern,page,re.S)
        if not m:raise ValueError('Missing catalog row '+k)
        old=m[0];new=re.sub(r'data-priority="[^"]+"','data-priority="'+row['priority']+'"',old,count=1)
        new=re.sub(r'<span class="tag [^"]+">.*?</span>','<span class="tag '+('ready' if k in active else 'later')+'">'+row['priorityLabel']+'</span>',new,count=1)
        page=page[:m.start()]+new+page[m.end():]
    if new_ids:
        start=page.index('id="dataset-catalog"');end=page.index('</tbody>',start)
        page=page[:end]+''.join(catalog_row(by_id[k]) for k in [a['id'] for a in additions] if k in new_ids)+page[end:]
    page=once(page,r'<script id="catalog-json" type="application/json">.*?</script>','<script id="catalog-json" type="application/json">'+json.dumps(catalog,ensure_ascii=False).replace('</','<\/')+'</script>')
    page=re.sub(r'\b29 项',str(len(catalog))+' 项',page)
    if 'id="dataset-inclusion-policy"' in page:
        page=once(page,r'<div id="dataset-inclusion-policy">.*?</div>\s*<!-- end data review -->','')
    page=once(page,r'<h3>4\.3 数据目录与容量核查（\d+ 项数据条目）</h3><p class="note">.*?</p>',f'<h3>4.3 数据目录与容量核查（{len(catalog)} 项数据条目）</h3><p class="note">共 {len(catalog)} 项来源；新版 S1 默认主训练 {len(active)} 项，其他用于强化、增量、专项或评测。筛选标签反映新版用途；容量“首批”仍指此前文件选择，与训练采样权重分开。<a href="#predictor-data-mix">查看新版配方</a> · <a href="#data-capacity-summary">查看容量证据</a></p>')
    page=page.replace('仅看起步候选','仅看默认主训练')
    needle='<h3>4.3 数据目录与容量核查（'+str(len(catalog))+' 项数据条目）</h3>'
    page=page.replace(needle,needle+review_html(review)+'<!-- end data review -->',1)
    names={k:x['name'] for k,x in by_id.items()}
    page=once(page,r'<h4 id="predictor-data-mix">.*?(?=<section class="subsection" id="data-capacity-summary">)',recipe_html(plan,names)+'\n')
    phase_rows=[[esc(x['id']+' · '+x['name']),esc(x['exit']),'<a href="#predictor-stage-budget">数据比例、更新预算与门槛</a>'] for x in plan['stages']]
    phase_rows += [['S3 · 领域与语言接口','导航单独适配并回放交互数据；语言读出与主预测损失分别验收。','<a href="#predictor-data-mix">专项与增量规则</a>'],['S4 · 系统协同','固定候选与预算比较 Policy / verifier / WM 的净收益；验收实际延迟、成功率和误干预。','<a href="#predictor-transfer-eval">评测与隔离</a>']]
    page=once(page,r'<h4>主模型阶段规划</h4>.*?(?=<h4>预测主干的两条实现路径</h4>)','<h4>主模型阶段规划</h4><p>以人类交互 + 真实机器人 + 操作语义 + 受控仿真建立主干；默认来源和预算以 4.4 新版配置为准。通用视频、导航和图像辅助分别做增量或专项，不在首轮平均铺开。</p>'+table(['阶段','目标与退出条件','详细方案'],phase_rows))
    page=page.replace('Ego · 通用视频 · 图文与编辑 · 机器人与导航','Gen-HumanEgo / EgoDex · DROID / Bridge · EPIC / SSv2 · LIBERO / RoboCasa')
    page=page.replace('Ego4D、SSv2、FineVideo 等连续真实片段。','Gen-HumanEgo、EgoDex、EPIC / SSv2 等连续真实交互片段。')
    page=page.replace('Ego4D / EPIC 的时序标注、重标注 OpenVid、带指令机器人视频。','Gen-HumanEgo / EPIC 的合格动作语义、带指令机器人视频；事后结果只作目标。')
    page=page.replace('EgoDex / Ego-Exo4D / Human-1M-100K</td>','Gen-HumanEgo / EgoDex / Ego-Exo4D / Human-1M-100K</td>')
    page=page.replace('扩大 Ego、实拍视频、机器人及导航覆盖；按去重后的清单增加数据，不按 TB 强制配比。','按新版 S1/S2 扩大人类交互和有效机器人控制；导航专项另计。Gen-HumanEgo 全库约 62 TB，20–30 TB 预算仅支持选取子集，不等于容纳全部新来源。')
    page=page.replace('Human-1M-100K、AgiBot、Panda 等分阶段选取；100 TB+ 存储是中长期规划，不代表足以保存全量密集缓存。','Gen-HumanEgo、Human-1M-100K、Open-HumanWAM 等按完整 episode 分阶段选取；合集中重叠来源不重复保存。100 TB+ 是资源预算，不代表足以保存全量或密集缓存。')
    if 'id="matrix-genhumanego"' not in page:
        pos=page.index('id="data-supervision-matrix"');end=page.index('<tbody>',pos)+len('<tbody>')
        additions_matrix=[
            ('genhumanego','Gen-HumanEgo / Human-1M / Open-HumanWAM','✓','△','—','△','△','—','—','手部/深度为质量可控辅助；人体运动不等于机器人控制，重建历史输入另验因果性。'),
            ('egomimic','EgoMimic','✓','△','✓*','△','△','—','—','仅机器人部分提供对应控制；人类部分分字段，按任务/场景做跨域对齐消融。'),
            ('holoassist','HoloAssist','✓','△','—','△','✓','—','—','train 训练、val/test 评测；错误、干预和手部预测，不补成机器人动作。'),
            ('hdepic','HD-EPIC','评测','评测','—','评测','评测','—','—','整体评测保留，默认训练比例 0%；时序预测和完整视频理解分别评价。')]
        rendered=''.join('<tr id="matrix-'+r[0]+'">'+''.join('<td>'+esc(v)+'</td>' for v in r[1:])+'</tr>' for r in additions_matrix)
        page=page[:end]+rendered+page[end:]
    marker='<p id="predictor-mode-activation" class="note">七种接口表示支持的能力范围；当前主训练默认只启用真实时序、可信语义和连续控制。图文/编辑初期权重为 0，新增数据须通过 <a href="#predictor-data-ablation">独立增量实验</a>；具体来源以 <a href="#predictor-data-mix">新版配方</a> 为准。</p>'
    if 'id="predictor-mode-activation"' not in page:
        page=page.replace('<h4 id="predictor-data-mix">',marker+'<h4 id="predictor-data-mix">',1)
    # Expose training decisions through the existing catalog CSV export.
    if "['trainingRole'" not in page:
        page=page.replace("['capacityStatus',", "['trainingRole', '新版训练用途'],\n      ['predictorS1Percent', 'S1 默认采样百分比'],\n      ['capacityStatus',",1)
    page=page.replace('<h4>数据规模与首批下载容量</h4>','<h4>数据规模与既有文件选择容量</h4>')
    page=page.replace('本节只做可审计的汇总，','本节沿用既有下载规划与核验口径，不代表新版训练比例或本地已到手数据；只做可审计的汇总，') if '不代表新版训练比例或本地已到手数据' not in page else page
    (ROOT/'index.html').write_text(page)
    print(f'Rendered {len(catalog)} catalog entries; {len(active)} S1 sources; {len(review["reviews"])} evidence decisions.')


if __name__=='__main__':main()
