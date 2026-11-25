# WorldModel 技术调研与数据规划

`index.html` 是独立可打开的中文报告，包含技术调研、通用世界模型设计、29 项数据目录、16 组训练配方及专项探索。

2026-11-25 的数据容量补充只访问公开元数据与 HTTP HEAD，**未下载训练数据**。

- 首批已核验选择：**11 项、2,560 个文件、1,534,120,202,186 bytes（1.534120 TB）**。
- 另有 **6 项扩展资源**完成完整文件树核验，未计入首批选择小计。
- 首批未完成：Ego4D、EPIC-KITCHENS 需选择授权文件，SSv2 和 SCAND 的官方入口本次返回 403，自建仿真尚未生成。
- 仓库范围、选中文件容量、公开舍入值、预算上限和有效训练量分开记录。

文件与复现入口：

| 路径 | 用途 |
| --- | --- |
| `tools/data/` | 从原 HTML 内嵌工具包展开、修复后的源码和使用说明 |
| `tools/data/datasets.lock.json` | 本次核验的固定 Hugging Face commit |
| `reports/data-capacity/capacity_report.json` | 已内置于 HTML 的汇总报告，也可手动导入 |
| `reports/data-capacity/manifest.json`、`files.csv` | 精确选择清单与逐文件字节数 |
| `reports/data-capacity/inventories/` | 完整文件树与 HTTP 元数据快照，只有元数据 |
| `reports/data-capacity/access_checks.json` | 官方接口访问失败及替代官方入口的记录 |
| `scripts/update_capacity_assets.py` | 从本地报告重建 HTML 的容量区域和内嵌工具包 |

```bash
python -m pip install -r tools/data/requirements.txt
# 只查询元数据；扩展仓库文件树可能很大
python tools/data/wm_data.py plan --config tools/data/datasets.lock.json --all-datasets --out wm_plan
# 返回码 2 表示仍有待选择/待核验项，不表示已知容量统计无效

# 同步 HTML，不访问网络
python scripts/update_capacity_assets.py

# 单元测试与本地快照校验
python -m pytest -q tests/
```

页面支持离线查看内置结果、下载完整工具包、导入新报告、恢复内置结果及导出目录 CSV。真实数据下载必须另外确认许可并显式使用 `download --execute`。本次未执行 TB 级下载、解压、训练样本检查或 GitHub Pages 发布。
