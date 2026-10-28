"""把关键数值打印到日志，用于核对抓取结果是否合理。"""
import json

import pandas as pd

from . import dotplot, fred
from .config import DATA


def main():
    imp = json.loads((DATA / "implied.json").read_text(encoding="utf-8"))
    print("隐含利率来源:", imp.get("source"), imp.get("asof"), "EFFR:", imp.get("effr_now"))
    for m in imp.get("meetings", []):
        top = sorted(m["probs"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  {m['date']}  预期 {m['exp_rate']:.3f}  较现在 {m['chg_bp_vs_now']:+.1f}bp  前三档 {top}")
    d = dotplot.load()
    if not d.empty:
        med = dotplot.medians(d)
        last = med[med.sep_date == med.sep_date.max()]
        print("最新点阵中位数:", last[["sep_date", "horizon", "median", "n"]].to_string(index=False))
    for sid in ("DFEDTARL", "DFEDTARU", "EFFR", "DGS2", "T5YIFR", "UNRATE", "PAYEMS"):
        s = fred.load(sid)
        if not s.empty:
            print(f"  {sid}: {s.iloc[-1]:.3f} @ {s.index[-1].date()}")
    for sid in ("CPIAUCSL", "CPILFESL", "PPIFIS"):
        s = fred.transform(fred.load(sid), "yoy")
        if not s.empty:
            print(f"  {sid} 同比: {s.iloc[-1]:.2f}% @ {s.index[-1].date():%Y-%m}")
    dx = pd.read_csv(DATA / "dxy.csv").dropna(subset=["dxy_calc"]).tail(1)
    print("DXY 自算:", dx.to_dict("records"))


if __name__ == "__main__":
    main()
