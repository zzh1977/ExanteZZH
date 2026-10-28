# 美联储监测方案与待办

## 监测范围
| 方向 | 数据 | 来源 | 状态 |
|---|---|---|---|
| 点阵图 | 历次 SEP 完整点阵分布 + 中位数 | 美联储 SEP 网页版（fomcprojtabl*.htm），FRED `FEDTARMD` 兜底 | 第一步 ✅ |
| 市场隐含利率 | 逐次会议隐含利率、目标区间概率、预期漂移 | ① FedWatch 抓取 ② ZQ 期货（雅虎）自算 ③ 短端美债代理 | 第一步 ✅ |
| 通胀 | CPI/核心CPI/PCE/核心PCE/PPI/核心PPI，5Y/10Y/5y5y 盈亏平衡 | FRED | 第一步 ✅ |
| 就业 | 失业率 U-3/U-6、非农、初请、职位空缺、时薪、萨姆规则 | FRED | 第一步 ✅ |
| 美元 | DXY（ICE）+ 按公式自算、广义贸易加权美元 | 雅虎 / FRED | 第一步 ✅ |
| 讲话 | 讲话/证词/声明/纪要，鹰鸽打分、要点、措辞对比、市场反应 | 美联储 RSS + Claude API | 第二步 |

## 待办
- [ ] **期货数据 API**：目前没有。有了 Exante / 盈透等 API 账户后，接入 ZQ / SR3 实时报价，作为 FedWatch 抓取的替代（雅虎在 GitHub 服务器上被限流，不可用）。
- [ ] **第二步：讲话分析**——抓美联储 RSS（讲话、证词、声明）、纪要、发布会文字稿；Claude 打鹰鸽分（-2~+2）与要点；FOMC 声明逐句对比；委员立场表（标注票委）；事件前后 2 年期美债 / 隐含利率 / DXY 变化衡量市场反应。需要 `ANTHROPIC_API_KEY`。
- [ ] **第三步：提醒推送**——FOMC 决议、CPI/非农发布、讲话立场明显转向时推送（Telegram 或邮件）。
- [ ] 2012–2015 年只有 PDF 的 SEP：补解析（或手工录入），让点阵历史从 2012 年开始完整。
- [ ] 数据发布的“预期 vs 实际”（意外值）：需要市场一致预期数据源。
- [ ] **未来可能做**：Streamlit 交互式看板（目前用静态网页）。

## 可考虑：FRED API key
现在用 FRED 网站的图表下载地址（fredgraph.csv），不需要 key，已验证 34 个序列都能取到。
加上仓库 Secret `FRED_API_KEY` 后，代码自动优先走官方 API（api.stlouisfed.org），出错时退回免 key 方式。

| | 现在：图表下载地址（免 key） | 申请 key：官方 API |
|---|---|---|
| 配置 | 零配置 | 注册、申请 key、加到 Secrets，约 3 分钟 |
| 稳定性 | 网页功能，不是对外承诺的接口，可能随时变（曾因请求头设置被拦） | 有文档、有版本的正式接口 |
| 限流 | 无公开额度，被限时只会超时 | 每个 key 每分钟 120 次，超限有明确报错 |
| 修订历史 | 只有最新值 | 可取历史版本（ALFRED）：首发值 vs 修订值、历次点阵中位数 |
| 发布日历 | 没有 | 有发布日程和更新时间，可直接用于第三步提醒 |
| 下载效率 | 每次整段重下 | 可增量下载 |
| 维护 | 无 | 要保管 key，遵守 FRED API 使用条款 |

建议：现在不急。免 key 方式再次失效、做第三步提醒需要发布日历、或想看数据修订时再申请。

## 架构
```
fedmon/
  config.py        序列清单、FOMC 兜底日程
  fred.py          FRED 下载（有 FRED_API_KEY 走 API，否则走免 key 的 fredgraph.csv）
  fomc_calendar.py FOMC 日程
  dotplot.py       历史点阵图解析
  implied.py       隐含利率（三层来源）
  dxy.py           美元指数
  dashboard.py     生成 docs/index.html
data/              数据（由 GitHub Actions 每个交易日更新并提交）
docs/index.html    静态看板（GitHub Pages）
```
