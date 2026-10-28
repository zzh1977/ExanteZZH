# ExanteZZH

## 美元流动性指数（第一步：FRED 免费数据）

用 FRED 免费数据构建三个周度子指数，正值 = 流动性偏松，并与芝加哥联储 NFCI 对比验证。
方案依据见审查文档《美元流动性指标构建方案审查》。

### 运行

```bash
pip install -r requirements.txt
python -m liquidity --out output          # 下载数据、计算、输出
python -m pytest -q                       # 测试
```

- 不需要 API key（使用 fredgraph.csv 公开接口）；有 key 可设 `FRED_API_KEY` 改走官方 API。
- 数据缓存在 `data/raw/`，加 `--refresh` 重新下载。
- 输出：`output/liquidity_index.csv`（各分项、z 分数、子指数）、`validation_nfci.csv`、`lead_lag_nfci.csv`、`liquidity_index.png`。

### 指标

| 子指数 | 分项 | FRED 序列 | 标准化 |
| --- | --- | --- | --- |
| 存量 | 准备金 / 名义GDP | WRESBAL, GDP | 扩展窗口 z |
| 存量 | 政策性证券净买入（13周）/ GDP，储备管理购买期间剔除短债和MBS变动 | WSHOSHO, WSHOBL, WSHOMCB | 3年滚动 z |
| 预期 | −(1年期国债 − 有效联邦基金利率)，即已定价的降息幅度 | DGS1, DFF | 扩展窗口 z |
| 压力 | SOFR − IORB（2021年7月前用 IOER），取反 | SOFR, IORB, IOER | 3年滚动 z |
| 压力 | 联储贷款 + 央行互换 + 隔夜回购（含SRF）/ GDP，取反 | WLCFLL, SWPT, RPONTSYD | 3年滚动 z |

另输出“净流动性”（总资产 − 4周平均TGA − 逆回购）作参考，不计入指数。
合成指数 = 三个子指数等权平均（至少两个有值），仅供参考，权重待验证后再定。

### 防止前视偏差

- 每个序列按发布日重新标日期（H.4.1 周三数据→周四；日度利率→次日；GDP→季度初+120天；NFCI→+5天），每周五一行，只含当周五前已公布的数据。
- z 分数只用当期及以前的数据。
- GDP 用的是最新修订值，不是当时的实时值（ALFRED 版本待接入）。

### 已知限制

- USD 序列的单位（百万/十亿美元）按近5年峰值自动识别，对不上会直接报错。
- 储备管理购买的时间窗口写在 `liquidity/config.py`，需对照 FOMC 执行说明核对。
- 文本鹰鸽分数、议息会议意外（Jarociński-Karadi）属于后续步骤。
