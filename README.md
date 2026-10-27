# ExanteZZH

## 本地 AI 文件整理（Windows / 16GB / 完全断网 / 多模型分工）

- **操作手册（从下载到使用）**：[docs/操作手册.md](docs/操作手册.md)
- 常见疑问（Python 环境、文件夹用途、命令含义）：[docs/常见疑问.md](docs/常见疑问.md)
- 完整方案：[docs/本地AI文件整理方案.md](docs/本地AI文件整理方案.md)
- 模型选型对比：[docs/本地模型选型对比.md](docs/本地模型选型对比.md)
- 整理工具：`file_organizer/organize.py`
  - 先分流（不用模型）：中文文档 / 英文德文文档 / 照片 / 音视频等 / 认不出语言
  - 中文文档：默认只单独分出来（可选 `qwen3:8b` 细分）
  - 英文/德文文档：`llama3.1:8b`；照片：`qwen3-vl:4b`
  - 复制后校验指纹再删原文件，自动生成归档汇总表，可核对、可撤销
  - 依赖装在独立虚拟环境 `venv` 里（`setup_venv.bat` 创建），用 `organize.bat` 运行，系统 Python 保持干净
- 文档工具：`tools/md_toc.py`（给 md 加固定锚点和目录）、`tools/build_html.py`（md 生成带目录、可跳转的网页，自动核对无遗漏）
- 离线安装脚本：`scripts/prepare_offline.ps1`（联网电脑）、`scripts/install_offline.ps1`（断网电脑）

快速使用（在 `file_organizer` 文件夹里）：

```powershell
.\organize.bat scan "D:\待整理" --out plan.csv          # 分流 + 分类，生成计划，不动文件
.\organize.bat apply plan.csv --target "D:\已整理"      # 按计划整理
.\organize.bat verify "D:\已整理"                        # 核对归档文件是否完好
.\organize.bat undo undo_xxx.csv                         # 撤销
```

文档维护（只改 md，需要网页时再生成）：

```bash
python tools/md_toc.py docs/*.md                      # 增删、改名章节后更新目录和锚点
python -m pip install -r tools/requirements.txt       # 第一次生成网页前安装（建议装在虚拟环境里）
python tools/build_html.py docs/操作手册.md docs/常见疑问.md -o 手册.html --title "离线 AI 文件整理手册"
```
