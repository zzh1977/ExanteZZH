"""全局配置：FRED 序列清单、路径、FOMC 日程兜底。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
RAW = DATA / "raw"          # 抓取失败时保存的原始页面（调试用，不入库）

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# FRED 序列：id -> (中文名, 分组, 变换)
# 变换: level 原值 / yoy 同比% / mom 环比% / diff 月度变化
FRED_SERIES = {
    # 政策利率
    "DFEDTARU": ("目标区间上限", "policy", "level"),
    "DFEDTARL": ("目标区间下限", "policy", "level"),
    "EFFR": ("有效联邦基金利率 EFFR", "policy", "level"),
    "SOFR": ("SOFR", "policy", "level"),
    # 国债（隐含利率兜底用）
    "DTB3": ("3个月国库券", "rates", "level"),
    "DTB6": ("6个月国库券", "rates", "level"),
    "DGS1": ("1年期美债", "rates", "level"),
    "DGS2": ("2年期美债", "rates", "level"),
    "DGS10": ("10年期美债", "rates", "level"),
    # 点阵图（FRED 只保留最新一期 SEP，历史靠 dotplot 模块解析美联储网页）
    "FEDTARMD": ("点阵图中位数", "sep", "level"),
    "FEDTARMDLR": ("点阵图长期中位数", "sep", "level"),
    # 盈亏平衡通胀
    "T5YIE": ("5年盈亏平衡通胀", "breakeven", "level"),
    "T10YIE": ("10年盈亏平衡通胀", "breakeven", "level"),
    "T5YIFR": ("5y5y 远期通胀预期", "breakeven", "level"),
    # 通胀
    "CPIAUCSL": ("CPI", "inflation", "yoy"),
    "CPILFESL": ("核心 CPI", "inflation", "yoy"),
    "PCEPI": ("PCE", "inflation", "yoy"),
    "PCEPILFE": ("核心 PCE", "inflation", "yoy"),
    "PPIFIS": ("PPI 最终需求", "inflation", "yoy"),
    "WPSFD4131": ("核心 PPI（除食品能源贸易）", "inflation", "yoy"),
    # 就业
    "UNRATE": ("失业率", "labor", "level"),
    "U6RATE": ("U-6 失业率", "labor", "level"),
    "PAYEMS": ("非农新增（千人）", "labor", "diff"),
    "ICSA": ("初请失业金（人）", "labor", "level"),
    "JTSJOL": ("职位空缺（千）", "labor", "level"),
    "CES0500000003": ("平均时薪", "labor", "yoy"),
    "SAHMREALTIME": ("萨姆规则指标", "labor", "level"),
    # 美元
    "DTWEXBGS": ("广义贸易加权美元", "fx", "level"),
    "DEXUSEU": ("EURUSD", "fx_raw", "level"),
    "DEXJPUS": ("USDJPY", "fx_raw", "level"),
    "DEXUSUK": ("GBPUSD", "fx_raw", "level"),
    "DEXCAUS": ("USDCAD", "fx_raw", "level"),
    "DEXSDUS": ("USDSEK", "fx_raw", "level"),
    "DEXSZUS": ("USDCHF", "fx_raw", "level"),
}

# 历史数据起点（够看两轮加息/降息周期）
START_DATE = "2007-01-01"

# FOMC 日程兜底（第二天 = 决议日）。抓取官网成功时以官网为准。
# 标 True 的会议发布 SEP（点阵图）。
FOMC_FALLBACK = [
    ("2026-01-27", "2026-01-28", False),
    ("2026-03-17", "2026-03-18", True),
    ("2026-04-28", "2026-04-29", False),
    ("2026-06-16", "2026-06-17", True),
    ("2026-07-28", "2026-07-29", False),
    ("2026-09-15", "2026-09-16", True),
    ("2026-10-27", "2026-10-28", False),
    ("2026-12-08", "2026-12-09", True),
]
