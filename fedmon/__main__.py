"""命令行入口。

python -m fedmon update      抓取全部数据并生成看板
python -m fedmon build       只用本地数据重新生成看板
python -m fedmon <模块>      单独跑: fred / calendar / dotplot / implied / dxy
"""
import json
import logging
import sys

from . import altsources, dashboard, dotplot, dxy, fomc_calendar, fred, implied
from .config import DATA

def fred_with_fallback():
    return altsources.fill_missing(fred.update_all())


STEPS = {
    "fred": fred_with_fallback,
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
    # 连政策利率都没拿到视为整体失败，让 Actions 标红
    fr = status.get("fred")
    if isinstance(fr, dict) and not str(fr.get("EFFR", "")).startswith("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
