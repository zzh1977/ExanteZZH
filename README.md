# ExanteZZH

## 本地 AI 文件整理（Windows / 16GB / 完全断网 / 多模型分工）

- 完整方案：[docs/本地AI文件整理方案.md](docs/本地AI文件整理方案.md)
- 模型选型对比：[docs/本地模型选型对比.md](docs/本地模型选型对比.md)
- 整理工具：`file_organizer/organize.py`
  - 先分流（不用模型）：中文文档 / 英文德文文档 / 照片 / 音视频等 / 认不出语言
  - 中文文档：默认只单独分出来（可选 `qwen3:8b` 细分）
  - 英文/德文文档：`llama3.1:8b`；照片：`qwen3-vl:4b`
  - 复制后校验指纹再删原文件，自动生成归档汇总表，可核对、可撤销
- 离线安装脚本：`scripts/prepare_offline.ps1`（联网电脑）、`scripts/install_offline.ps1`（断网电脑）

快速使用：

```powershell
python organize.py scan "D:\待整理" --out plan.csv          # 分流 + 分类，生成计划，不动文件
python organize.py apply plan.csv --target "D:\已整理"      # 按计划整理
python organize.py verify "D:\已整理"                        # 核对归档文件是否完好
python organize.py undo undo_xxx.csv                         # 撤销
```
