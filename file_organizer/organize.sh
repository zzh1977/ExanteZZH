#!/bin/bash
# Run the organizer with its own Python environment (../venv).  macOS / Linux.
# Usage: ./organize.sh scan "/Volumes/资料盘/待整理" --out ~/AI/计划/计划.csv
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[错误] 没有找到工具专用的 Python 环境：$HERE/../venv"
  echo "请先运行：bash \"$HERE/setup_venv.sh\""
  exit 1
fi
exec "$PY" "$HERE/organize.py" "$@"
