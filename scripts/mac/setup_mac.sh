#!/bin/bash
# 在 Mac（Apple 芯片）上一次性安装本地文件整理工具。需要联网运行一次；装好后整理时可以完全断网。
#
# 运行前先装好：
#   1. Ollama for macOS   https://ollama.com/download  （拖进“应用程序”，打开一次）
#   2. Python 3.14        https://www.python.org/downloads/macos/  （macOS 64-bit universal2 installer）
#
# 用法（在“终端”里）：
#   bash scripts/mac/setup_mac.sh                      # 装到 ~/AI，下载默认模型
#   bash scripts/mac/setup_mac.sh --with-zh            # 另外下载 qwen3:8b，用于中文文档细分
#   bash scripts/mac/setup_mac.sh --models gemma3:12b,qwen3-vl:8b --dest ~/AI
#
# 可以重复运行：已下载的模型不会重新下载；你改过的 config.json 会保留；Python 环境会重建。

set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/AI"
MODELS="gemma3:12b,qwen3-vl:8b"
EN_DE_MODEL="gemma3:12b"
PHOTO_MODEL="qwen3-vl:8b"
WITH_ZH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --with-zh) WITH_ZH=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "不认识的参数：$1"; exit 1 ;;
  esac
done
[ "$WITH_ZH" = 1 ] && MODELS="$MODELS,qwen3:8b"
DEST="${DEST/#\~/$HOME}"

step() { echo; echo "== $1"; }

step "[1/5] 检查电脑和软件"
if [ "$(uname -s)" = "Darwin" ]; then
  [ "$(uname -m)" = "arm64" ] || echo "  [提示] 这不是 Apple 芯片的 Mac，模型只能用 CPU 运行，会慢很多。"
  MEM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
  echo "  内存：${MEM_GB}GB，芯片：$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
  [ "$MEM_GB" -ge 24 ] || echo "  [提示] 内存小于 24GB，建议改用小一些的模型：--models llama3.1:8b,qwen3-vl:4b"
else
  echo "  [提示] 这不是 macOS，跳过硬件检查（本脚本主要为 Mac 准备）。"
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo "  [错误] 没有找到 ollama 命令。请先安装 Ollama 并打开一次（https://ollama.com/download）。"
  exit 1
fi
if ! curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "  Ollama 没在运行，正在打开 ..."
  open -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &)
  for _ in $(seq 1 30); do
    curl -s -m 2 http://127.0.0.1:11434/api/tags >/dev/null && break
    sleep 1
  done
  curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null || { echo "  [错误] Ollama 启动失败，请手动打开 Ollama 后重试。"; exit 1; }
fi
echo "  Ollama 正常。"

step "[2/5] 下载模型（放在内置硬盘 ~/.ollama/models）"
IFS=',' read -r -a MODEL_LIST <<< "$MODELS"
for m in "${MODEL_LIST[@]}"; do
  [ -n "$m" ] || continue
  echo "  下载 $m ..."
  ollama pull "$m"
done

step "[3/5] 复制整理工具和文档到 $DEST"
mkdir -p "$DEST" "$DEST/计划"
CFG="$DEST/file_organizer/config.json"
KEEP=""
if [ -f "$CFG" ]; then KEEP="$(mktemp)"; cp "$CFG" "$KEEP"; fi
rm -rf "$DEST/file_organizer"
cp -R "$REPO/file_organizer" "$DEST/file_organizer"
rm -rf "$DEST/file_organizer/__pycache__" "$DEST/docs"
cp -R "$REPO/docs" "$DEST/docs"
chmod +x "$DEST/file_organizer/organize.sh" "$DEST/file_organizer/setup_venv.sh"
if [ -n "$KEEP" ]; then
  cp "$KEEP" "$CFG"; rm -f "$KEEP"
  echo "  保留了你原来的 config.json"
  [ "$WITH_ZH" = 1 ] && echo "  [提示] 设置未改动。要让中文文档细分，请把 config.json 里 zh 的 \"model\" 改成 \"qwen3:8b\"。"
fi

step "[4/5] 创建工具专用的 Python 环境 $DEST/venv（系统 Python 不装任何包）"
bash "$DEST/file_organizer/setup_venv.sh"

# 新装时把设置改成 Mac 32GB 的默认模型（英德文 gemma3:12b、照片 qwen3-vl:8b；中文按需）
if [ -z "$KEEP" ]; then
  "$DEST/venv/bin/python" - "$CFG" "$EN_DE_MODEL" "$PHOTO_MODEL" "$WITH_ZH" <<'PYEOF'
import re, sys
path, en_de, photo, with_zh = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
s = open(path, encoding="utf-8").read()
def set_model(s, route, model):
    # 只改对应路线里的 "model": "…"，保留文件其余格式
    pat = re.compile(r'("%s"\s*:\s*\{[^{}]*?"model"\s*:\s*")[^"]*(")' % route, re.S)
    s, n = pat.subn(lambda m: m.group(1) + model + m.group(2), s, count=1)
    assert n == 1, route
    return s
s = set_model(s, "en_de", en_de)
s = set_model(s, "photo", photo)
if with_zh:
    s = set_model(s, "zh", "qwen3:8b")
open(path, "w", encoding="utf-8").write(s)
print(f"  设置：英德文 {en_de}，照片 {photo}，中文 {'qwen3:8b 细分' if with_zh else '只分流'}")
PYEOF
fi

step "[5/5] 检查"
"$DEST/venv/bin/python" - "$CFG" <<'PYEOF'
import json, sys, urllib.request
cfg = json.load(open(sys.argv[1], encoding="utf-8-sig"))
have = {m["name"] for m in json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/tags"))["models"]}
need = {r.get("model") for r in cfg["routes"].values() if r.get("model")}
lack = [m for m in need if (m if ":" in m else m + ":latest") not in have]
print("  设置里用到的模型：" + "、".join(sorted(need)))
if lack:
    print("  [提示] 还没下载：" + "、".join(lack) + "。可运行 ollama pull 模型名，或在 config.json 里换成已有模型。")
else:
    print("  模型都已就绪。")
PYEOF

echo
echo "安装完成。以后这样用（可以先关掉 Wi-Fi 再整理）："
echo "  cd \"$DEST/file_organizer\""
echo "  ./organize.sh scan \"/Volumes/资料盘/待整理\" --out \"$DEST/计划/计划.csv\""
echo "详细步骤见：$DEST/docs/Mac版操作手册.md"
