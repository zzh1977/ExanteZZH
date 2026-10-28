# 项目约定（给 Claude 会话）

本地 AI 文件整理工具：用 Ollama 本地模型把中文、英文/德文文档和照片分流归档。Windows 和 Mac 两套。
进度、未验证事项和待办见 `docs/工作进度与交接.md`，接手时先读它。

## 必须守住的

- **不丢文件**：工具不删除任何唯一的文件；移动 = 同盘改名，或复制 → 核对 SHA-256 → 再删原文件；每次执行都有撤销日志和对账。改 `organize.py` 时不要破坏这些。
- 模型只给建议（受 JSON 枚举约束），文件操作由程序完成。
- 用户文档全部用中文，面向非技术用户：先结论、步骤清楚、不用术语。

## 改动后

- 改代码：`<装好依赖的 python> tests/smoke_test.py`，全部通过再提交。
- 改文档：只改 `docs/*.md` 和 `README.md`（md 是唯一来源，网页由 `tools/build_html.py` 生成）；增删或改名章节后运行 `python tools/md_toc.py docs/*.md README.md`。不要手改 `<a id="sec-N">` 锚点。
- Windows 和 Mac 两份手册要同步：一边改了流程，另一边对应的地方也要改。
- 手册网页需要更新时，重新生成并发布，命令见交接文档第八节。

## 文件格式

- `.bat`：CRLF 换行、纯 ASCII（`.gitattributes` 里设了 `-text`）。
- `.ps1`：纯 ASCII、英文提示（Windows PowerShell 5.1 读无 BOM 文件会把中文弄乱）。
- `.sh`：可执行权限已记录在 git 里；用户手册里统一写 `bash xxx.sh` 或 `./organize.sh`。
- `config.json`：UTF-8；工具读取时兼容带 BOM。计划表 CSV 用带 BOM 的 UTF-8 写，读时兼容 GBK。
