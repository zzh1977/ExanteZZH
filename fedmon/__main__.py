"""命令行入口。

python -m fedmon update      抓取全部数据并生成看板
python -m fedmon build       只用本地数据重新生成看板
python -m fedmon <模块>      单独跑: fred / calendar / dotplot / implied / dxy
"""
import json
import logging
import sys

from . import dashboard, dotplot, dxy, fomc_calendar, fred, implied
from .config import DATA

STEPS = {
    "fred": fred.update_all,
    "calendar": fomc_calendar.update,
    "dotplot": dotplot.update,
    "dxy": dxy.update,
    "implied": implied.update,  # 依赖 fred + calendar，放在后面
}


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cmd = argv[1] if len(argv) > 1 else "update"
    status = {}
    if cmd == "update":
        for name, fn in STEPS.items():
            try:
                r = fn()
                status[name] = r if name == "fred" else "ok"
            except Exception as e:
                logging.exception("%s 失败", name)
                status[name] = f"失败: {e}"
        DATA.mkdir(exist_ok=True)
        (DATA / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
        dashboard.build()
    elif cmd == "build":
        dashboard.build()
    elif cmd in STEPS:
        STEPS[cmd]()
    else:
        print(__doc__)
        return 2
    # FRED 全部失败视为整体失败，让 Actions 标红
    fr = status.get("fred")
    if isinstance(fr, dict) and fr and all(v != "ok" for v in fr.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
