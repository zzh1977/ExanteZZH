#!/bin/bash
# Create or rebuild the organizer's own Python environment in ../venv.  macOS / Linux.
# The system Python stays clean: all packages go into ../venv only.
# Offline: installs from ../wheels if that folder exists. Online: downloads from PyPI.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../venv"
WHEELS="$HERE/../wheels"

# Find a Python 3.10 or newer (macOS's built-in python3 is often too old)
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[错误] 没有找到 Python 3.10 或更新的版本。请从 python.org 安装 Python 3.14（macOS 64-bit universal2 installer）。"
  exit 1
fi
echo "使用 Python：$PY（$("$PY" --version)）"

rm -rf "$VENV"
echo "创建 Python 环境：$VENV"
"$PY" -m venv "$VENV"
if [ -d "$WHEELS" ]; then
  echo "从 $WHEELS 离线安装依赖包 ..."
  "$VENV/bin/python" -m pip install --disable-pip-version-check --no-index --find-links "$WHEELS" -r "$HERE/requirements.txt"
else
  echo "联网下载并安装依赖包 ..."
  "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$HERE/requirements.txt"
fi
"$VENV/bin/python" -c "import pypdf, docx, openpyxl, pptx, PIL, pillow_heif; print('Packages OK')"
echo "完成。Python 环境：$VENV"
