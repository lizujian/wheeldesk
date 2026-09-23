# NiubiTrader Gamma 页面调研

**调研日期：** 2026-09-23  
**目标：** 判断 `https://niubitrader.com/zh/gamma` 是否适合为本系统的 QQQ/TQQQ 车轮、QQQ/个股 LEAPS 和核心仓信号提供数据或决策依据。

## 结论

NiubiTrader Gamma 页面可以作为**人工盘中风险背景参考**，但目前不适合接入本系统作为自动或半自动信号源，也不能直接替代 QQQ 日线指标或个股期权链数据。

原因有三点：

1. 产品覆盖的是 **CME 的 NQ 期货 0DTE 期权**，不是 QQQ、TQQQ 或个股期权。NQ 与 QQQ 有较强相关性，但标的、交易场所、合约乘数、到期结构和价格口径都不同；NQ 的 Gamma 水平不能直接当作 QQQ/TQQQ 的 Gamma，也不能据此直接选择 30--45 天 Sell Put 或 1 年期 LEAPS 行权价。
2. 页面展示的是市场微结构状态，包括 Gamma/Vanna/Charm、ZGL、结构位和状态概率；页面及公开条款没有给出足以复现的完整公式、过滤规则或阈值定义。它适合做“当前市场可能更容易稳定/加速”的上下文，不适合直接产出本系统所需的开仓、止盈或止损结论。
3. 前端确实调用了一个无需登录即可读取的 JSON/WebSocket 端点，但这更像网站内部接口，不是公开承诺的开发者 API。站点 `robots.txt` 禁止 `/api/`，条款也明确禁止抓取、批量采集、转售/再分发指标，以及用自动化手段模拟正常用户访问。因此不应在本机应用中轮询或依赖它，除非运营方另行提供明确授权和正式 API 文档。

对当前系统的建议是：**暂不集成 NiubiTrader；保留为人工打开查看的可选参考链接。** 本系统继续以 IBKR 活动报表记录、现有行情刷新和 QQQ 日线 MA200/RSI/跌幅等已定义规则为主。

## 页面实际展示的内容

官方页面的标题和描述将产品定义为“NQ Gamma 监测”和“NQ 0DTE 期权 gamma / vanna / charm 实时监测”。页面的工作台包含以下内容：

- **NQ 价格（current forward）**：指数点。
- **ATM IV**：年化隐含波动率；页面在接近到期时还可能标记为“临到期 IV 发散”。
- **净 Gamma**：页面标注为“美元 / 标的 1% 变动”。
- **净 Vanna**：页面标注为“美元 / 1 个波动点”。
- **净 Charm**：页面标注为“美元 / 日”。
- **Gamma 状态**：正 Gamma、负 Gamma 或不确定，并显示 `P(正)` 和 `P(负)`。
- **ZGL**：显示 `baseline_selected_root`；如果有数据，还显示 IV 敏感带的低值、中位值和高值。
- **结构位**：支撑线和阻力线。
- **行权价剖面**：Gamma、Vanna、Charm 分别按行权价展示剖面，可看到每档 strike 及对应的总暴露。
- **时间轴**：页面支持 `5m`、`15m`、`30m`、`1h`、`2h` 和全部区间；默认最近 30 分钟。

页面还明确写着“当日实时 · 无重播”，因此它的产品定位是当前交易时段的盘中观察，而不是长期历史回测数据源。

页面来源：

- [Gamma 工作台（中文）](https://niubitrader.com/zh/gamma)
- [关于 NiubiTrader](https://niubitrader.com/zh/about)

## 数据来源和指标口径

### 官方声明的来源

NiubiTrader 的关于页面称其使用“官方交易所行情，逐事件级处理”。服务条款进一步说明，网站指标是对 **Databento, Inc. 提供的 CME 市场数据**加工计算后的衍生结果，不转发或出售原始行情数据。

这意味着：

- 数据底层是 CME 市场，不是 Nasdaq 上的 QQQ 期权链，也不是 Cboe/NYSE 上的个股期权链。
- 页面输出是运营方计算的衍生指标；不能仅凭页面数值重建其完整计算过程。
- `Gamma`、`Vanna`、`Charm` 的页面单位是明确的，但正负号、仓位方向、是否按 open interest/成交量/盘口、筛选哪些到期合约、如何处理缺失报价等细节，公开页面没有完整说明。
- “正 Gamma/负 Gamma”的状态标签和概率值是网站自己的分类结果，不能未经验证地当作可交易概率或统计胜率。

来源：

- [关于 NiubiTrader：真数据与逐事件级处理](https://niubitrader.com/zh/about)
- [服务条款：数据来源与使用边界](https://niubitrader.com/zh/terms)

### 页面前端可验证的接口结构

截至调研日，页面 JavaScript 中可见以下接口路径（域名为 `https://api.niubitrader.com`）：

~~~text
GET /api/gamma/v2/snapshot
GET /api/gamma/v2/session-history
WebSocket /ws/gamma/v2
~~~

这些路径来自页面公开加载的前端 chunk：

- [Gamma 页面前端 chunk](https://niubitrader.com/_next/static/chunks/app/%5Blocale%5D/gamma/page-ec4c85c5259b9d93.js)

实际请求在调研时无需登录即可返回 JSON。`session-history` 返回当前 `trading_session_id` 的 frames；在一次抽样中返回了 `NQ-2026-09-22-RTH` 的 779 帧，帧间隔约 30 秒。单个 frame 的公开字段包括：

~~~text
input_as_of; current_forward; atm_iv
gamma.net_usd_per_1pct; gamma.profile.strikes; gamma.profile.total_usd_per_1pct
vanna.net_usd_per_1vol_point; charm.net_usd_per_day
zgl.baseline_selected_root; zgl.iv_sensitivity_band.low/median/high
structure_levels.support/resistance
regime.label; regime.p_positive_gamma/p_negative_gamma
~~~

抽样 endpoint：

- [当前快照](https://api.niubitrader.com/api/gamma/v2/snapshot)
- [当日 session history](https://api.niubitrader.com/api/gamma/v2/session-history)

重要边界：

- 这些是前端正在使用的内部接口，不等于有版本保证、配额说明、认证方案、商业授权或兼容性承诺的公开 API。
- 页面端点返回的是当前/当日 session，不是面向回测的稳定历史数据库。
- 公开 JSON 在收盘或没有发布 Gamma 帧时会出现 `gamma: null` 等空值；不能把空值当作中性信号。
- 本次没有找到官方的 OpenAPI、开发者文档、计算公式说明、历史数据下载说明或 rate limit/服务等级说明。

## 对本系统各策略的适用性

### QQQ/TQQQ Wheel

**结论：低到中等的辅助价值，不能做主信号。**

可作为盘中背景的内容：

- `regime.label` 可以提示当前 NQ 期权市场被分类为正 Gamma、负 Gamma 或不确定。仅作为风险环境标签时，正 Gamma 可理解为更偏向对冲稳定/价格回归的环境，负 Gamma 可理解为价格波动可能被对冲流放大的环境；但这只是市场微结构的解释方向，不是网站对未来价格的预测。
- `structure_levels.support/resistance` 和 ZGL 可以帮助人工观察 NQ 附近的盘中结构位。
- `net Gamma`、Vanna、Charm 和 ATM IV 可以辅助判断事件日或快速波动日的风险背景。

不能直接用于现有 Wheel 规则的地方：

- 本系统的 Sell Put 信号基于 QQQ 日线 `close > SMA200`、`RSI14 < 50`（或配置后的阈值）、阴线/跌幅等条件；NiubiTrader 没有提供这些 QQQ 日线指标。
- 本系统卖的是 TQQQ 或万亿俱乐部个股的 30--45 天期权，而 NiubiTrader 监测 NQ 的 0DTE 期权。NQ 支撑位不能直接当作 TQQQ 或个股行权价支撑位。
- 对 TQQQ 来说还存在三倍杠杆、ETF 跟踪误差、分红/融资和期权链差异，不能从 NQ 的 Gamma 数值推导 TQQQ 的安全距离或保证金。
- `gamma` 的正负若只看一个瞬时帧，容易在 30 秒级噪声中频繁变化；网站本身也显示“不确定”和收盘未发布状态。

如果未来在获得授权的前提下使用，最保守的产品化方式也应只是增加一个“盘中 Gamma 背景”字段：记录快照时间、NQ forward、状态标签、Gamma/Vanna/Charm、ZGL、支撑/阻力，并在数据过期或为空时显示“不可用”。不要把它并入 Sell Put 的自动触发条件，更不要用它替代 QQQ/TQQQ 的期权链和用户手工确认。

### QQQ LEAPS

**结论：不适合作为 QQQ LEAPS 入场、止盈或强制平仓规则的直接输入。**

QQQ LEAPS 规则需要 QQQ 本身的价格、SMA200、RSI14、日跌幅、持仓收益率、持仓天数和到期时间。NiubiTrader 提供的是 NQ 0DTE 期权的盘中暴露，无法回答：

- QQQ 1 年期 Call 应选哪个行权价或 Delta；
- 某个 QQQ 期权的实际权利金、IV、Bid/Ask 或收益率；
- 现有 LEAPS 是否达到 +50%/+30%/+10% 阶梯止盈；
- 某个合约距离到期是否进入强制退出区间。

最多只能作为“广义 Nasdaq 风险环境”的人工参考，而且需要明确标注 NQ/QQQ 基差和 0DTE/1Y 到期结构不同。它不能被当作 QQQ LEAPS 的定价或退出数据源。

### 万亿俱乐部个股 Wheel/LEAPS

**结论：不适合直接使用。**

网站当前产品没有个股期权链、单股 Gamma、单股 IV 或单股结构位。NQ 的市场微结构可能反映大型科技股共同风险，但无法替代每只股票自己的 RSI、价格、期权链、Delta、IV 和到期日数据。尤其不能用 NQ 结构位给 AVGO、GOOG、NVDA 等个股 Sell Put 选行权价。

### 核心仓 BRK.B / 其他长期仓

**结论：没有直接价值。**

BRK.B、VOO/GPIQ 等核心仓的 DCA、回撤和目标配比需要各自的日线行情及账户持仓；NQ 0DTE Gamma 与这些资产不存在足够直接的标的对应关系。

## 是否应该接入本机应用

当前不建议接入，理由如下：

1. **标的不匹配：** NQ 0DTE 不是 QQQ/TQQQ/个股期权。
2. **频率不匹配：** 页面是盘中实时 session，本系统是手动刷新、以日线和活动报表为主。
3. **接口不稳定：** 找到的是网页内部端点，没有公开 API 版本/配额/字段兼容承诺。
4. **使用边界明确：** [服务条款](https://niubitrader.com/zh/terms) 要求不得抓取、批量采集、转售/再分发展示的数据和指标，不得使用自动化手段模拟正常用户访问；[robots.txt](https://api.niubitrader.com/robots.txt) 也没有将 API 作为适合抓取的公开资源。
5. **缺少可复现口径：** 如果把一个未公开公式的状态标签写入交易信号，后续无法可靠回测、解释或校验。

可以保留一个不影响业务逻辑的人工入口，例如在“外部参考”或帮助文案中链接到：

~~~text
https://niubitrader.com/zh/gamma
~~~

这只允许用户自行查看，不在本系统后台轮询，不保存或再分发其指标，不把其输出写入交易信号。

## 限制和待确认项

- 本调研基于 2026-09-23 访问时可公开读取的网页、前端 JavaScript、条款和 JSON 响应；页面处于公测期，覆盖品种、阈值和接口都可能改变。
- 没有公开文档解释 Gamma/Vanna/Charm 的完整公式、仓位符号、合约筛选和数据清洗规则，因此不能把页面读数作为可审计的交易模型。
- “正 Gamma 通常降低短期实现波动、负 Gamma 可能放大短期波动”是对 Gamma 暴露含义的通用市场解释，不是 NiubiTrader 对未来走势的承诺，也不是本网站公开验证的胜率。
- 如未来希望正式集成，应先向运营方索取书面授权、API 文档、字段定义、历史数据政策、刷新频率、错误/空值语义、rate limit、数据再分发许可和服务稳定性说明；在此之前不应自动化调用内部端点。

