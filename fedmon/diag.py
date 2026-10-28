"""连通性和页面结构诊断，结果打印到日志（调试抓取问题用）。"""
import re
import sys

import requests

from .config import USER_AGENT

H = {"User-Agent": USER_AGENT}


def probe(url, n=300, **kw):
    try:
        r = requests.get(url, headers=H, timeout=(10, 20), **kw)
        body = r.text
        print(f"[{r.status_code}] {url} len={len(body)} ct={r.headers.get('content-type')}")
        return body
    except Exception as e:
        print(f"[ERR] {url}: {e}")
        return ""


def main():
    print("=== FRED ===")
    probe("https://api.stlouisfed.org/fred/series/observations?series_id=UNRATE&file_type=json")
    probe("https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE")
    probe("https://fred.stlouisfed.org/")
    print("=== 美联储历史页 ===")
    for y in (2015, 2019):
        b = probe(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm")
        links = sorted(set(re.findall(r'href="([^"]*proj[^"]*)"', b, re.I)))
        print(f"  {y} proj 链接: {links[:20]}")
    print("=== 雅虎 ===")
    for host in ("query1", "query2"):
        b = probe(f"https://{host}.finance.yahoo.com/v8/finance/chart/ZQZ26.CBT?range=5d&interval=1d")
        print("  ", b[:200].replace("\n", " "))
    print("=== 其他候选源 ===")
    probe("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/1.json")
    probe("https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000")
    probe("https://stooq.com/q/l/?s=dx.f&f=sd2t2ohlcv&h&e=csv")


if __name__ == "__main__":
    sys.exit(main())
