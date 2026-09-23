# BRK.B / QQQ 价格比率展示工具调研

**调研日期：** 2026-09-22  
**目标：** 找到可以展示 `BRK.B / QQQ` 的工具，并明确哪些能力可以直接复用到本机监测系统。

## 结论

最直接的现成工具是 **StockCharts SharpCharts**。StockCharts 的官方文档明确规定：在可以填写单个 ticker 的位置，也可以填写两个 ticker，并用冒号连接；结果就是“第一个数据集 / 第二个数据集”的 Ratio Symbol。因此可以使用类似 `BRK/B:QQQ` 的表达式（StockCharts 对股票类别使用斜杠表示，BRK.B 在该平台应先在代码搜索中确认实际代码）。

**TradingView** 也可以实现，但最稳妥的方式是用 Pine Script 自定义一条比率线：通过 `request.security()` 分别读取 BRK.B 与 QQQ 的收盘价，再用除法绘图。TradingView 官方 Pine 文档支持这两个基础能力。直接在普通图表输入框中使用任意自定义算式的网页 UI 能力，本次没有找到可稳定引用的官方帮助页，因此不把它当成产品依赖。

**Yahoo Finance** 适合提供两只证券的历史价格数据和普通对比图，但本次没有找到 Yahoo 官方文档明确支持在图表中输入自定义 `A/B` 比率公式。Yahoo 的 Compare 更适合叠加比较两条价格/表现线，不能据此假设它会显示价格比率。对于本项目，建议继续把 Yahoo 作为数据源，在本地按同一交易日收盘价计算 `BRK.B_close / QQQ_close`。

## 平台核对

### StockCharts：原生 Ratio Symbol，最适合手工查看

官方文档：

- [Ratio and Difference Symbols](https://help.stockcharts.com/data-and-ticker-symbols/ticker-symbols/ratio-and-difference-symbols)
- [Markdown version](https://help.stockcharts.com/data-and-ticker-symbols/ticker-symbols/ratio-and-difference-symbols.md)
- [Ticker Symbol Conventions](https://help.stockcharts.com/data-and-ticker-symbols/ticker-symbols/ticker-symbol-conventions.md)

关键事实：

- 两个 ticker 用冒号连接表示比率，例如文档中的 `AAPL:$SPX`。
- 比率是第一个 ticker 除以第二个 ticker；上涨表示第一个标的相对跑赢，下降表示第二个标的相对跑赢。
- SharpChart 的 `Price` 指标可以把 Ratio Symbol 加到现有图表中。
- StockCharts 对不同股票类别使用斜杠，例如 `BRK/A`；因此 BRK.B 需要在 StockCharts 搜索框确认其平台代码，预计表达式形态为 `BRK/B:QQQ`。
- 日线比率的 Close 定义为 `Close(first) / Close(second)`。其 Open/High/Low 也有明确计算规则，避免把比率 K 线的高低点弄反。

如果只想观察相对强弱而不关心比率绝对值，可以把它当作 Price Relative line：线向上表示 BRK.B 跑赢 QQQ，线向下表示 QQQ 跑赢 BRK.B。

### TradingView：用 Pine Script 自定义，适合长期保存和加指标

官方文档：

- [Other timeframes and data](https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/)
- [Operators](https://www.tradingview.com/pine-script-docs/language/operators/)

官方 Pine 文档说明，`request.security()` 可以针对指定 symbol 和 timeframe 请求数据；Pine 的算术运算支持除法。因此可以建立一条完全由 BRK.B 和 QQQ 收盘价计算的比率线，并在同一脚本内增加移动平均、阈值和提醒。

示例（实际使用前在 TradingView 的 Symbol Search 中确认交易所前缀）：

```pine
//@version=6
indicator("BRK.B / QQQ", format = format.price)

brk = request.security("NYSE:BRK.B", timeframe.period, close)
qqq = request.security("NASDAQ:QQQ", timeframe.period, close)
ratio = brk / qqq

plot(ratio, "BRK.B / QQQ", color = color.blue, linewidth = 2)
plot(ta.sma(ratio, 50), "Ratio SMA 50", color = color.orange)
```

注意：交易所前缀、股票类别代码和数据权限可能因 TradingView 数据源而不同；脚本能否取数应以 Symbol Search 实际返回的完整代码为准。

### Yahoo Finance：数据源可以继续用，网页图表不宜作为比率工具

可核对的公开入口：

- [BRK-B chart](https://finance.yahoo.com/quote/BRK-B/chart/)
- [QQQ chart](https://finance.yahoo.com/quote/QQQ/chart/)

Yahoo 的网页图表适合分别查看 `BRK-B` 和 `QQQ`，也可以做普通比较；但本次没有找到 Yahoo 官方说明允许用户输入两个 ticker 的自定义除法表达式。因此不要把网页 Compare 当成 `BRK.B/QQQ` 比率图。

对本项目而言，最简单且可复现的做法是：请求两个标的的同一频率、同一交易日价格，在应用内计算：

```text
ratio[t] = adjusted_or_unadjusted_close("BRK.B", t)
           / adjusted_or_unadjusted_close("QQQ", t)
```

必须统一使用 adjusted 或 unadjusted 价格，不能一边使用复权收盘价、一边使用未复权收盘价。由于系统只手动刷新，日线收盘价足够满足轮动监测，不需要实时行情。

## 对本项目的建议

1. **先在系统内直接增加比率指标展示。** 复用现有 Yahoo 刷新结果，保存 BRK.B 和 QQQ 的日线收盘价后，在后端计算 `BRK.B / QQQ`，前端展示当前值、20/50 日均线和近 20/60 日变化。这样不依赖第三方登录，也不会引入新的行情接口。
2. **StockCharts 作为人工复核工具。** 需要快速查看历史相对强弱时使用 Ratio Symbol；代码先确认 BRK/B 的平台写法。
3. **TradingView 作为可选的可视化/提醒工具。** 如果以后需要在图表上叠加阈值、回撤和提醒，可使用 Pine Script；不建议让系统依赖 TradingView 页面抓取。
4. **比率不能单独决定轮动。** 比率应和各自的回撤、相对收益、核心仓是否已满以及最短冷却时间一起判断，并保留人工确认。

## 限制和待确认项

- 本笔调研没有把 StockCharts 或 TradingView 的登录后付费数据权限作为前提；免费账户能看到的历史范围和实时性应以账号实际权限为准。
- StockCharts 的 BRK.B ticker 需要在其代码搜索中确认，因其官方符号约定使用斜杠表示股票类别。
- Yahoo Finance 没有找到本次所需的官方“自定义比率图公式”文档；因此结论是“可作为数据源，本身不作为原生比率图工具”，而不是断言 Yahoo 内部绝对不存在相关实验功能。
