# 本地 AI 文件整理方案（Windows / 16GB 内存 / 完全断网）

## 一、结论先看

| 项目 | 选择 | 说明 |
|---|---|---|
| 运行软件 | **Ollama for Windows** | 免费、一键安装、自带本地接口，断网可用 |
| 主力模型 | **Qwen3-8B（4bit 量化，`qwen3:8b`）** | 约 5.2GB，中文理解好，16GB 内存跑得动 |
| 备用模型 | **Qwen3-4B（`qwen3:4b`）** | 约 2.5GB，速度约快一倍，机器卡时用 |
| 整理工具 | 本仓库 `file_organizer/organize.py` | 扫描 → 生成计划表 → 人工确认 → 整理 → 可一键撤销 |
| 文件格式 | txt / md / csv / pdf / docx / xlsx / pptx / 代码等读内容；图片、视频、安装包、压缩包按扩展名分类 | 老格式 .doc/.xls 只按文件名判断 |

工作方式：

```
待整理文件夹 ──扫描──> 读取文件开头内容 ──> 本地模型(Ollama) 判断类别/起新名字
                                                    │
         整理后文件夹 <──执行── 你用 Excel 检查/修改 plan.csv
              │
              └── 撤销日志 undo_xxx.csv（随时可还原）
```

全程只访问本机 `127.0.0.1`，不需要也不会联网。

> 各模型的特色、优缺点对比，以及“准确性 + 不丢文件”的保障机制，见 [本地模型选型对比.md](本地模型选型对比.md)。

---

## 二、硬件评估（16GB 内存）

| 部分 | 占用 |
|---|---|
| Windows 系统 + 常用软件 | 约 4–6 GB |
| Qwen3-8B 模型（Q4 量化）+ 上下文 4096 | 约 6–7 GB |
| 剩余 | 约 3–5 GB，够用 |

- **不建议** 14B 及以上的模型：14B 量化后约 9GB，加上系统会频繁卡顿。
- **有没有独立显卡**：没有也能跑（纯 CPU）。有 NVIDIA 显卡（6GB 显存以上）会自动加速，速度可提高 3–5 倍。
- **速度参考**（每个文件约 2000 字内容）：

| 机器 | qwen3:8b | qwen3:4b |
|---|---|---|
| 纯 CPU（近几年 i5/i7、R5/R7） | 每个文件约 15–40 秒 | 约 8–20 秒 |
| NVIDIA 显卡 8GB 显存 | 约 2–5 秒 | 约 1–3 秒 |

1000 个文档用 CPU 跑大约要几个小时，可以晚上挂着跑；工具支持**中断后接着跑**。图片、视频、安装包按扩展名直接分类，不调用模型，几乎不花时间。

---

## 三、离线部署步骤

因为目标电脑完全断网，需要先在一台**能上网的 Windows 电脑**上准备好安装包，用 U 盘拷过去。

### 第 1 步：在联网电脑上准备（约 30 分钟，需下载约 9GB）

1. 下载两个安装程序，放进一个文件夹（如 `E:\offline_ai`）：
   - Ollama：<https://ollama.com/download> → `OllamaSetup.exe`
   - Python 3.12 64 位：<https://www.python.org/downloads/windows/> → `python-3.12.x-amd64.exe`
2. 在这台联网电脑上也安装好 Ollama 和**同一版本**的 Python（勾选 “Add python.exe to PATH”）。
3. 把本仓库下载到这台电脑，在 PowerShell 中运行：

   ```powershell
   cd 仓库目录\scripts
   powershell -ExecutionPolicy Bypass -File prepare_offline.ps1 -Out E:\offline_ai
   ```

   脚本会自动：下载 `qwen3:8b` 和 `qwen3:4b` 模型 → 复制模型文件 → 下载 Python 依赖包 → 复制整理工具。

4. 完成后 `E:\offline_ai` 里应有：

   ```
   OllamaSetup.exe
   python-3.12.x-amd64.exe
   ollama_models\        ← 模型文件（约 8GB）
   wheels\               ← Python 依赖包
   file_organizer\       ← 整理工具
   install_offline.ps1
   ```

5. 把整个文件夹拷到 U 盘。

> 只想要一个模型时：`-Models qwen3:8b`。
> 想按《本地模型选型对比》试点对比两个模型：`-Models qwen3:8b,qwen3.5:9b`（共约 12GB）。

### 第 2 步：在断网电脑上安装（约 15 分钟）

1. 双击安装 `OllamaSetup.exe`。
2. 双击安装 Python，**勾选 “Add python.exe to PATH”**。
3. 在 U 盘的 `offline_ai` 文件夹里打开 PowerShell，运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File install_offline.ps1 -Dest D:\AI
   ```

   脚本会：把模型复制到 `D:\AI\ollama_models`、设置 Ollama 的环境变量（只监听本机、单并发省内存）、离线安装 Python 依赖。
   想额外用防火墙禁止 Ollama 联网：以管理员身份运行，并加参数 `-BlockFirewall`。

4. 右下角托盘图标里**退出 Ollama，再重新打开**（让环境变量生效）。

### 第 3 步：验证

```powershell
ollama list                      # 应能看到 qwen3:8b、qwen3:4b
ollama run qwen3:4b "你好，用一句话介绍你自己"
```

能正常回答就说明本地模型已可用。

### 手动安装方式（不想用脚本时）

- 模型：把联网电脑 `C:\Users\用户名\.ollama\models` 整个文件夹，复制到断网电脑同样位置即可。
- 依赖：联网电脑运行 `pip download -r requirements.txt -d wheels`，断网电脑运行
  `pip install --no-index --find-links wheels -r requirements.txt`。
- 也可以在 ModelScope / HuggingFace 下载 `.gguf` 模型文件，断网电脑上用 Modelfile 导入：
  ```
  # Modelfile 内容
  FROM D:\AI\Qwen3-8B-Q4_K_M.gguf
  ```
  ```powershell
  ollama create qwen3:8b -f Modelfile
  ```

---

## 四、使用整理工具

工具位置：`D:\AI\file_organizer\organize.py`。**扫描阶段不会动任何文件**。

### 1. 扫描，生成整理计划

```powershell
cd D:\AI\file_organizer
python organize.py scan "D:\待整理" --out plan.csv
```

- 中途关掉也没关系，再运行同一命令会**跳过已处理的文件**，接着跑。
- 机器慢时换小模型：`python organize.py --model qwen3:4b scan "D:\待整理" --out plan.csv`
- 只想快速按扩展名分类 + 查重（不用模型）：加 `--no-llm`

### 2. 用 Excel 打开 plan.csv 检查

| 列 | 含义 | 可以改吗 |
|---|---|---|
| action | `move` = 整理，`skip` = 不动 | 可以 |
| source | 原文件路径 | 不要改 |
| category | 归入的文件夹（类别） | 可以 |
| new_name | 新文件名，默认 `日期_标题.扩展名` | 可以 |
| summary / tags | 模型给的摘要和关键词，方便你检查 | 仅参考 |
| confidence | 把握：高/中/低，“规则”表示按扩展名或关键词定类 | 仅参考 |
| note | 标“建议人工确认”的行请重点检查 | 仅参考 |
| duplicate_of | 内容完全相同的文件，默认 `skip` | 仅参考 |

改完直接保存（保持 CSV 格式）。

### 3. 先预览，再执行

```powershell
python organize.py apply plan.csv --target "D:\已整理" --dry-run   # 只打印，不动文件
python organize.py apply plan.csv --target "D:\已整理"             # 移动文件
python organize.py apply plan.csv --target "D:\已整理" --copy      # 复制（原文件保留，最保险）
```

整理结果：

```
D:\已整理\
  合同协议\2024-03-01_房屋租赁合同.pdf
  财务票据\2024-05-12_办公用品采购发票.pdf
  会议纪要\2024-06-03_季度销售复盘会议.docx
  照片图片\2023-08-15_IMG_0012.jpg
  ...
```

同名文件会自动加 `(1)`、`(2)`，不会覆盖。

**防丢失**：同一磁盘直接改名；跨磁盘先复制、核对 SHA-256 指纹一致后才删除原文件。任何一步出错，原文件不动。执行完会对账：计划总数 = 已归档 + 跳过 + 失败。

**汇总归档**：目标目录下自动生成 `_归档索引` 文件夹：

- `归档汇总_日期时间.xlsx`：汇总页（各类别文件数、大小）、明细页（新旧位置、摘要、标签、指纹）、未归档页（跳过/失败原因）
- `归档清单_日期时间.csv`：本次明细
- `归档总索引.csv`：历次累计总表

### 4. 核对归档是否完好

```powershell
python organize.py verify "D:\已整理"     # 按累计总索引重新核对每个文件的指纹
```

会列出“不存在”或“内容已变”的文件。建议整理完、拷贝到移动硬盘后各核对一次。

### 5. 撤销

执行后会生成 `undo_日期_时间.csv`：

```powershell
python organize.py undo undo_20261025_103000.csv
```

### 6. 自定义类别和命名

编辑 `config.json`：

- `categories`：类别列表，改成你自己的（如 “客户A”、“项目B”、“报销”）。模型只会在这些类别中选择。
- `ext_rules`：按扩展名直接分类的规则。
- `keyword_rules`：文件名含某关键词就直接归入某类（优先于模型），如 `"财务票据": ["发票", "报销"]`。
- `name_template`：命名格式，可用 `{date}` 和 `{title}`，如改成 `{title}_{date}`。
- `model`：默认模型。
- `max_chars`：每个文件读取多少字给模型看，越大越准、越慢（建议 1500–3000）。

---

## 五、内存与速度优化

1. **只开一个模型**：安装脚本已设置 `OLLAMA_MAX_LOADED_MODELS=1`、`OLLAMA_NUM_PARALLEL=1`。
2. **上下文不要开太大**：`config.json` 里 `num_ctx` 保持 4096；每增加一倍约多占 0.5–1GB。
3. **关闭思考模式**：Qwen3 默认会先“思考”再回答，工具已自动关闭，速度快好几倍。
4. **跑大批量时**关掉浏览器等占内存的软件，接通电源，电源模式设为“最佳性能”。
5. **分批处理**：按子文件夹分几次扫描，方便检查。

---

## 六、断网与数据安全

- Ollama 和整理工具都只连接 `127.0.0.1:11434`（本机），文件内容不出电脑。
- `OLLAMA_HOST=127.0.0.1` 确保不对局域网开放。
- 可选：`install_offline.ps1 -BlockFirewall` 给 Ollama 加防火墙出站拦截，双保险。
- 工具只做“移动/复制”，不删除文件；有撤销日志。第一次使用建议先用 `--copy` 或先拿一个小文件夹试。
- 重要资料整理前先备份。

---

## 七、可选扩展

| 需求 | 做法 |
|---|---|
| 按**图片内容**分类（证件照、截图、发票照片等） | 再准备 `qwen2.5vl:7b` 视觉模型（约 6GB）。注意 16GB 内存下不要和 8B 文本模型同时加载 |
| **扫描件 PDF**（图片型，读不出文字） | 目前按文件名判断；需要时可加离线 OCR（如 RapidOCR），可以再扩展 |
| 老格式 `.doc` / `.xls` / `.ppt` | 用 WPS/Office 批量另存为新格式后再扫描 |
| 整理后**用自然语言搜文件、问问题**（本地知识库） | 准备向量模型 `bge-m3`（约 1.2GB），配合 AnythingLLM 桌面版等离线知识库软件，安装包同样需在联网电脑下载 |
| 想要图形界面聊天 | 可改用 / 加装 LM Studio（也支持离线，模型为 .gguf 文件）。本工具调用的是 Ollama 接口 |

---

## 八、常见问题

**Q：运行时报“连不上 Ollama”？**
A：确认右下角有 Ollama 图标；或在命令行运行 `ollama serve`。

**Q：报“本机没有模型 qwen3:8b”？**
A：运行 `ollama list` 看实际名字；检查 `OLLAMA_MODELS` 路径是否指向复制过来的 `ollama_models` 文件夹，改完要重启 Ollama。

**Q：电脑很卡 / 很慢？**
A：换 `--model qwen3:4b`；把 `max_chars` 调到 1000；关闭其他软件。

**Q：分类不准？**
A：① 把 `categories` 改得更贴近你的实际文件；② 换 8B 模型；③ 调大 `max_chars`；④ 在 plan.csv 中手动改，再执行。

**Q：plan.csv 用 Excel 打开是乱码？**
A：工具已用带 BOM 的 UTF-8 保存，一般不会乱码；若仍乱码，用 Excel “数据 → 从文本/CSV” 导入并选 UTF-8。

**Q：pip 离线安装失败？**
A：联网电脑和断网电脑的 Python 版本（如都是 3.12、64 位）必须一致，因为部分依赖包与版本绑定。
