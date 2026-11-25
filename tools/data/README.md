# WorldModel Predictor 数据获取与容量核验

用途：按指定发布版本读取 **真实文件字节数**、选择完整文件、生成可复现下载清单，并将容量报告导入配套 HTML。公开发布页的 GB/TB 数值只作参考，不能当成精确字节；本工具不根据时长或码率推算文件大小。

## 1. 环境与许可

Python 3.10+；在可访问数据源的机器上执行：

```bash
python -m pip install -r requirements.txt
```

下载训练数据前，先核查 `数据容量核查表.csv` 的数据来源和使用许可。公开文件树和 HEAD 元数据查询本身不需要 `--approved`，也不会接受任何许可。对于 Hugging Face gated 仓库，先在官方页面申请访问并登录（`hf auth login`）。`--approved` 是你已经确认许可的明确声明，不会替你接受任何条款。不得将访问令牌写入公开配置、报告或共享清单。

## 2. 先核验实际容量，不下载数据

```bash
python wm_data.py plan \
  --datasets egodex droid bridgev2 libero \
  --out wm_plan
```

结果：

- `manifest.json`：选中文件路径、精确 bytes、HF commit 或 HTTP 元数据、完整清单摘要。这个文件可能包含手工提供的临时 URL，请勿公开。
- `files.csv`：逐文件的字节数和版本，不含下载 URL。
- `capacity_report.json`：每项选择容量、仓库范围容量、文件数、固定版本、核验时间和待处理状态；可导入 HTML。`selected_bytes: null` 表示未选择或未核验，不是零字节。
- `inventories/*.json.gz`：完整文件树或 HTTP 元数据快照；解压后的 JSON SHA256 记录在报告的 `inventory_sha256` 中。
- `starter_selected_bytes` 只计入首批选择；完整扩展仓库范围不能加到首批小计。

如果未指定 `--datasets`，程序会核查配置中的全部首批候选；其中需申请、需指定本地文件的条目保留 pending，返回码 2 表示部分数据未解决。它不会启动下载，也不会把待核验容量记成 0 后冒充全量合计。

## 3. 子集选择

`datasets.json` 是可修改配置。`all` 表示取一个指定发布仓库的所有文件；`fixed` 表示只选择明确列出的完整文件；`budget` 表示基于文件树的真实 `size`，按固定种子选择不超过 `budget_bytes` 的完整分片。固定的元数据也占预算。上限不是实际容量。OpenVid 排除重复高清库和拆分归档，只选独立 ZIP 与主库 CSV；OmniEdit 只选 train 分片；ShareGPT-4o-Image 保留编辑和图文生成对应 JSON 及指定 TAR。选择归档只是下载粒度，随后必须按实际文件成员、时间段、任务与训练 split 过滤。默认只核查首批。`--all-datasets` 会遍历配置中扩展 HF 仓库的完整分页文件树，不下载其数据。Human-1M 的 PB 级 bucket 保持待选择，不自动遍历。

以下示例只读取三个数据集的元数据，生成整分片选择清单：

```bash
python wm_data.py plan \
  --datasets finevideo openvid omniedit \
  --out wm_shard_plan
```

Ego4D/Ego-Exo4D、EPIC、SSv2、Human-1M 等仍需通过官方入口选择版本、完整 episode/分卷和配套标注。SCAND 使用官方 Dataverse API 读取已发布版本清单；源站拒绝访问时保留错误状态。AgiBot、Assembly101、LLaVA-Video、Molmo2-Cap、RoboCasa MimicGen 使用 `inventory` 模式，只有仓库范围字节，不会自动选作首批训练数据。Molmo2-Cap 范围仅含该标注仓库。若已取得直接 HTTP(S) 下载地址，可填写 `manual_urls_template.csv`（每行 `dataset,path,url`，path 是保存到相应数据集目录中的相对路径），用：

```bash
python wm_data.py plan --datasets scand \
  --manual-csv manual_urls_template.csv --out wm_scand_plan
```

脚本只通过 HTTP HEAD 获取数据文件的长度，不回退到 Range GET；未返回可靠长度时失败，不猜测。元数据 API 的 GET 只用于文件列表和版本信息。RECON 的旧式 gzip/x-gzip 响应头需显式允许，下载器保留原始归档字节，禁止自动解压。务必自行确保所有分卷、同一轨迹的动作/状态/视频/标注配套完整，且 URL 来自可信的授权来源。临时签名 URL 可能过期。对需要官方客户端或对象存储凭据的源，优先使用官方客户端的文件清单与 dry-run，保留 UID/版本等选择记录；完成下载后可统计本地实际文件：

```bash
python wm_data.py plan --datasets ego4d \
  --local ego4d=/data/ego4d_selected --out wm_local_plan
```

本地目录 stat 仅代表所选目录中已存在的文件（跳过隐藏文件及符号链接），不是远端全集，不能把原始文件和解压副本重复计为有效数据。

## 4. 确认清单后下载

默认只演示，下载需显式 `--execute`。例如：

```bash
python wm_data.py download --manifest wm_plan/manifest.json \
  --dest /data/worldmodel --approved egodex droid bridgev2 libero \
  --max-gb 1000
```

查看清单和磁盘空间无误后，添加 `--execute`。按实际核验结果调整 `--max-gb`，默认留出 50 GB 额外空间（`--reserve-gb`）；解压、转码、Latent 缓存、检查点需另留空间。若清单存在待核验项，默认拒绝下载；只有明确愿意仅下载已解决部分时才添加 `--allow-partial`。HTTP 下载支持安全长度检查和 Range 续传，HF 下载固定 commit 并通过 Hub 客户端获取；`--sha256` 可对具有发布 LFS SHA256 的文件额外校验内容。默认进行字节长度校验，不等同所有文件的哈希验证或样本质量检查。

## 5. 训练侧使用规范

- 记录源数据版本、原始视频/episode ID、训练 split、视角、时间戳、动作定义、坐标系、频率和配套标注。
- 相同内容的不同转码或镜像择一，避免 OXE 与已有 Bridge/DROID、OpenVid 与 OpenVidHD 重复计量。
- 合成图像编辑只用作语义条件监督，不作为真实物理动力学真值；静态图文不提供连续未来转移。
- 下载容量不等于有效训练数据量；筛选、去重、解包后应再统计有效视频时长、有效轨迹与训练样本数。
- 冻结 Encoder 的 latent 缓存量可在 HTML 交互估算器中计算；不同权重、层、分辨率的特征缓存须独立管理。

## 6. 本次快照与复现

核查日期：2026-11-25。本次只读取远端元数据，未下载训练数据。HTML 已内置核验结果，可直接打开；导入新报告后，「恢复内置核验结果」可还原本次快照。

工具包的 `audit/` 含本次报告、精确选择清单、CSV 和访问失败记录；完整压缩文件树保存在 Git 仓库 `reports/data-capacity/inventories/`，避免将大型元数据快照重复嵌入 HTML。

```bash
# 固定已核验的 HF commit，重新读取元数据；不下载数据
python wm_data.py plan --config datasets.lock.json --all-datasets --out wm_audit
```

HTTP 源无法像 HF commit 一样锁定历史内容。本次清单保存 ETag、Last-Modified 和长度，下载前会重新检查；发生变化应重新 plan。计划中的字节数是所选发布文件大小，不代表解压后的文件大小、去重后的训练量、样本质量或有效授权。返回码 2 表示仍有未选择或未核验条目（包含只列文件树的扩展项）。本次完成了元数据在线核验与本地合成响应测试，未进行 TB 级真实下载测试。
