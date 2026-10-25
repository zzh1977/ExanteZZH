# ExanteZZH

## 本地 AI 文件整理（Windows / 16GB / 完全断网）

- 完整方案：[docs/本地AI文件整理方案.md](docs/本地AI文件整理方案.md)
- 整理工具：`file_organizer/organize.py`（Ollama + Qwen3 本地模型）
- 离线安装脚本：`scripts/prepare_offline.ps1`（联网电脑）、`scripts/install_offline.ps1`（断网电脑）

快速使用：

```powershell
python organize.py scan "D:\待整理" --out plan.csv          # 生成计划，不动文件
python organize.py apply plan.csv --target "D:\已整理"      # 按计划整理
python organize.py undo undo_xxx.csv                         # 撤销
```
