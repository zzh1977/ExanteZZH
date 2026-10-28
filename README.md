# ExanteZZH · 美联储监测

持续跟踪美联储：点阵图（含历史）、市场隐含利率、通胀（CPI/PPI/PCE/盈亏平衡）、就业、美元指数。
方案与待办见 [PLAN.md](PLAN.md)。

## 使用
```bash
pip install -r requirements.txt
python -m playwright install chromium   # FedWatch 抓取需要
python -m fedmon update                 # 抓数据 + 生成 docs/index.html
python -m fedmon build                  # 只用本地数据重新生成看板
python -m pytest -q tests
```

## 自动更新
`.github/workflows/update.yml` 在每个交易日 UTC 13:30 和 22:30 运行，把数据和看板提交回 main。

一次性设置：
1. （可选）仓库 Settings → Secrets → Actions 添加 `FRED_API_KEY`（不加也能用）。
2. Settings → Pages → Source 选 “Deploy from a branch”，分支 `main`，目录 `/docs`。
