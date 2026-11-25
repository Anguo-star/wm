# WorldModel Predictor 数据获取与容量核验

Python 3.10+。按官方发布范围读取实际文件字节、选择完整文件并生成容量报告。不按视频时长或假设码率推算文件容量。`plan` 只读元数据及响应头，不读取或保存训练文件正文。

```bash
python -m pip install -r requirements.txt
python wm_data.py plan --datasets egodex droid bridgev2 libero --out wm_plan
# 固定 HF commit；扩展范围较大，完整查询可能耗时较长
python wm_data.py plan --config datasets.lock.json --all-datasets --out wm_audit
```

默认检查首批；`--all-datasets` 包含全部 29 项。公开元数据查询不需要 `--approved`，不接受任何许可；gated 仓库能列出文件也不代表已经取得内容访问权。

## 文件与统计口径

- `manifest.json`：选中文件、精确字节、版本与完整清单摘要。手工 URL 可能含临时凭据，分享前应检查。
- `files.csv`：选中文件容量，无下载 URL。
- `capacity_report.json`：可导入 HTML；首批小计、扩展范围、登记容量、索引容量和近似发布值分开。
- `inventories/*.json.gz`：完整指定范围的文件树。报告中的 `inventory_sha256` 是解压后 JSON 的 SHA256。
- `evidence/*.json`：响应头、登记记录或官方来源检查。`evidence_sha256` 对规范化 JSON 计算 SHA256。
- `selected_bytes: null` 表示没有组成此次下载选择，不等于该项未核验，更不是零字节。

| 状态 | 含义 |
| --- | --- |
| `planned` / `local` | 精确选中文件容量 / 本地已有文件 stat |
| `inventoried` | 完整指定范围已逐文件核验，扩展范围单列，不属于未核验项 |
| `partial` | SCAND 登记容量或 Panda 索引已核验；这些容量不充当已选训练视频容量 |
| `published` | HowTo100M 作者公布的约 12 TB 已核对，非逐文件精确字节 |
| `blocked` | 官方清单访问受限；本次为 Ego4D 与 Ego-Exo4D |
| `not_generated` | 自建仿真尚未生成，无现成文件 |

报告的 `download_unresolved` 表示不能直接组成下载清单的条目，不等同“未核验”；不包含 `inventoried`。下载器仍兼容旧报告的 `pending` 字段。返回码 2 表示这些条目仍需单独处理，已取得的容量统计仍有效。查询失败不会用估算值或零字节替代。

## 已固定的范围

- EPIC：作者推荐的两个 torrent **清单描述符**提供 700 个原始视频的长度；不连接 tracker/peer。按官方 AR train ID、固定种子、100 GB 上限选出 67 个完整视频，保留固定 commit 的训练标注；68 个选中文件另经 HTTP HEAD 核对。
- SSv2：两份官方视频分卷和 labels ZIP。服务器 HEAD 返回 403，配置显式允许 `stream=True`、`Range: bytes=0-0` 的响应头查询，读取 **Content-Range 的总长**后立即关闭；不读取正文，不把 Content-Length=1 当作总量。其他 HTTP 源默认不启用此回退。
- Human-1M：`oss_100k_v1` 下一个完整发布批次，包含 data/meta/videos，共 29 个文件。HF bucket 不是不可变 Git 仓库；保留每个对象的 Xet hash，下载前通过只读 paths-info 请求重新比较。不能据此声称核验了整个 100K 小时数据。
- Kinetics：S3 `700_2020` 中 700 个完整 train 归档及 train.csv。
- OXE：官方 `gresearch/robotics` 的 fractal20220817_data 0.1.0、language_table 0.0.1、taco_play 0.1.0；完整 train TFRecord 分片及格式元数据。GCS 清单固定对象 generation，避免与已选 Bridge/DROID 重复。
- RxR：完整 train pose traces、guide/follower 标注及 Matterport3D Habitat 场景包。158,937 文件作为已核验扩展范围写入压缩 inventory；需要组成下载清单时把该项 mode 改为 `all` 后重新 plan。训练仍按 train scan 划分。
- Assembly101、AgiBot Beta/2026、LLaVA-Video、Molmo2-Cap、RoboCasa MimicGen：完整配置仓库范围单列。Molmo2-Cap 仅为该标注仓库。
- SCAND：Dataverse 主站 API 403；官方 DOI 注册机构 DataCite 保存 v5.2 的 284 个文件容量值。Dataverse 源码明确导出文件字节数；登记记录缺少容量与文件路径的映射，不能按 relatedIdentifiers 顺序拼成下载清单。
- Panda：已核验官方 2M 索引 ZIP 的 HEAD 长度；YouTube 源视频取决于可用性、分辨率与裁剪结果，没有统一固定视频归档。
- HowTo100M：作者的预处理视频约 12 TB（原文 12Tb，无音频），需表单申请下载账号；本次只查看入口，没有提交表单。旧公开索引/字幕 ZIP 链接返回 404。
- Ego4D / Ego-Exo4D：官方 v2_1 / v2 清单均返回 403，需已有授权凭据；自建仿真须先生成。

`all` 选择全部指定范围，`fixed` 选择配置列出的文件，`filtered` 选择全部匹配完整文件，`budget` 在上限内确定性选择完整分片，`inventory` 只登记完整范围。预算含必要标注，不是实际容量。归档选择只是下载粒度；训练时仍要按成员、split、时间段和任务过滤。

## 自有清单和本地统计

若已有授权 HTTP(S) 地址，在 `manual_urls_template.csv` 中填写 `dataset,path,url`：

```bash
python wm_data.py plan --datasets scand --manual-csv manual_urls_template.csv --out wm_scand
python wm_data.py plan --datasets ego4d --local ego4d=/data/ego4d_selected --out wm_local
```

本地 stat 只统计所选目录已有文件，跳过隐藏文件和符号链接，不代表远端全集。手工清单需要自行保证分卷、视频、动作、状态、标注完整，不将原文件和解压副本重复计为有效训练数据。

## 下载

本轮未执行下载。下面命令默认仅演示，实际下载需另加 `--execute`：

```bash
python wm_data.py download --manifest wm_plan/manifest.json \
  --dest /data/worldmodel --approved egodex droid bridgev2 libero --max-gb 1000
```

`--approved` 声明你已经确认许可，不会代你接受条款。执行前核对预算和磁盘空间，默认额外预留 50 GB；解压、转码、latent 缓存、检查点空间另算。报告中存在不能直接下载的条目时默认拒绝执行；只执行已选部分需要显式 `--allow-partial`。

HTTP 下载前检查长度、ETag、Last-Modified；GCS 固定 generation，Human bucket 比较 Xet hash，HF 固定 commit。内容变化需重新 plan。RECON 的旧 gzip/x-gzip 响应必须保留归档原始字节，不自动解压。断点续传检查范围与长度；`--sha256` 可校验具有 LFS SHA256 的 HF 文件。长度核验不等同内容哈希核验或样本质量检查。

工具包 `audit/` 包含报告、已选清单、CSV 和补充证据；大型完整文件树保存在 Git 仓库 `reports/data-capacity/inventories/`。本次完成在线元数据核验、离线合成响应测试和页面交互验证，未进行 TB 级真实下载。有效训练量须在筛选、去重和解包后另行统计；同一内容的不同镜像、转码或视角组合不能直接相加。
