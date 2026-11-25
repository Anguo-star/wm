# WorldModel 技术调研与数据规划

`index.html` 是独立可打开的中文报告，保留技术调研、通用世界模型设计、29 项数据目录、16 组训练配方及专项探索。

2026-11-25 已完成本轮可访问范围的容量核验，**未读取或保存训练文件正文**。本轮查询文件树、发布清单、DOI 登记和 HTTP 响应头。

| 核验结果 | 项目与范围 |
| --- | --- |
| 23 项逐文件容量 | 16 项已选文件 + 7 项完整指定扩展范围；每项保留范围、版本、逐文件字节和证据 |
| 首批精确选择 | **13 项、2,631 个文件、1,653,563,899,540 bytes（1.653564 TB）** |
| 扩展精确选择 | Human-1M 完整批次、Kinetics-700 train、OXE 三个 train 子集；另计 903,193,743,103 bytes |
| SCAND | 官方 DataCite 登记 v5.2 的 284 个容量值合计 **344,324,920,157 bytes**；没有路径映射，不充当下载清单 |
| Panda-70M | 官方 2M 索引 ZIP **114,255,340 bytes**；索引与源视频容量分开 |
| HowTo100M | 已核对作者公布的预处理视频约 **12 TB**（原文 12Tb）；账号申请入口有效，旧公开索引链接 404，精确清单需授权 |
| 无法读取官方精确清单 | **Ego4D、Ego-Exo4D**：官方清单返回 403，需已获授权的 AWS 凭据 |
| 尚未生成 | 自建仿真没有现成文件，生成后统计；不当作已核验的零字节 |

EPIC 已按原规划 100 GB 配额选择 67 个完整 train 视频及标注，全部 68 个文件的 HEAD 长度与发布清单一致。SSv2 的 HEAD 返回 403，但流式 GET 响应头可读：只取 Content-Range 总长后关闭响应，不读取正文，三个发布文件共 19,450,115,851 bytes。

Human-1M 只核验一个完整 `data/meta/videos` 批次，不能称为整个 100K 小时数据的容量；Molmo2-Cap 只覆盖该标注仓库。RxR 完整 train pose traces、配套标注和 Matterport3D Habitat 场景包共 31,882,527,315 bytes / 158,937 文件，作为扩展范围单列。场景包的训练划分和内容使用许可仍须遵守发布方要求。

| 路径 | 用途 |
| --- | --- |
| `tools/data/` | 数据来源、子集配置和元数据核验器 |
| `tools/data/datasets.lock.json` | 固定 HF commit、EPIC 标注版本、明确的发布范围与子集规则 |
| `reports/data-capacity/capacity_report.json` | 内置于 HTML 的汇总报告，可再次导入 |
| `reports/data-capacity/manifest.json`、`files.csv` | 已选文件清单与精确容量 |
| `reports/data-capacity/inventories/` | 完整指定范围文件树；压缩文件只含元数据 |
| `reports/data-capacity/evidence/` | 响应头、DOI 登记容量、来源核对与访问结果 |
| `scripts/update_capacity_assets.py` | 从本地报告重建 HTML 容量区域和内嵌工具包 |

```bash
python -m pip install -r tools/data/requirements.txt
# 只查询元数据；全部扩展范围的文件树较大
python tools/data/wm_data.py plan --config tools/data/datasets.lock.json --all-datasets --out wm_plan
# 返回码 2 表示有条目不能直接组成下载清单；不把已核验的扩展范围视为失败

# 从本地快照同步 HTML，不访问网络
python scripts/update_capacity_assets.py
python -m pytest -q tests/
```

页面支持离线查看结果、下载完整工具包和报告、导入报告、恢复内置结果及导出目录 CSV。真实数据下载必须另外确认许可并显式使用 `download --execute`。本次未执行真实数据下载、解压或训练样本检查，也未配置 GitHub Pages。
