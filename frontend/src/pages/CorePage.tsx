import { AlertTriangle, Banknote, BarChart3, CalendarClock, CircleDollarSign, Gauge, Landmark, ShieldCheck, TrendingUp, WalletCards } from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { CoreAssetDecision, CoreStrategyDecision, MarketSnapshot, PortfolioSummary, Position, WheelOverview, WheelPutLot } from '../lib/types'
import './CorePage.css'

const coreSymbols = new Set(['BRK.B', 'VOO', 'SCHD'])

export function CorePage({ portfolio, market, positions, overview }: {
  portfolio: PortfolioSummary
  market: MarketSnapshot | null
  positions: Position[]
  overview?: WheelOverview
}) {
  const lots = positions.filter((position) => position.bucket === 'core' && coreSymbols.has(position.symbol))
  const corePuts = overview?.core_puts ?? []
  const putCollateral = corePuts.reduce((total, put) => total + put.collateral, 0)
  const target = portfolio.targets?.core?.amount ?? 0
  const targetFraction = portfolio.targets?.core?.fraction ?? 0
  const funded = portfolio.balances?.core ?? 0
  const recordedCost = lots.reduce((total, position) => total + position.entry_price * position.quantity * position.multiplier, 0)
  const priceBySymbol = new Map<string, number>(market?.core?.assets?.map((asset) => [asset.symbol, asset.price]) ?? [])
  const currentValue = market?.core?.total_value ?? lots.reduce((total, position) => {
    const price = priceBySymbol.get(position.symbol) ?? position.current_price
    return total + position.quantity * position.multiplier * price
  }, 0)
  const remaining = Math.max(target - currentValue, 0)
  const fundingGap = Math.max(target - funded, 0)
  const unfundedCost = Math.max((portfolio.capital?.core.committed ?? recordedCost + putCollateral) - funded, 0)
  const overTarget = Math.max(currentValue - target, 0)
  const coreCapital = portfolio.capital?.core ?? { assigned: funded, committed: recordedCost, available: Math.max(funded - recordedCost, 0), cash_occupancy: 0 }
  const cashAvailable = portfolio.capital?.cash.available ?? (portfolio.balances?.cash ?? 0)

  return <div className="page-stack core-console">
    <div className="page-heading"><div><p className="eyebrow">BRK.B + VOO + SCHD CORE EQUITY</p><h1>核心仓相对定投</h1><span>SCHD 纳入核心配置 · 以低频分批建仓为主</span></div><span>{lots.length} 笔股票 · {corePuts.length} 笔待接股</span></div>

    <section className={`core-budget-band ${overTarget > 0 || unfundedCost > 0 ? 'danger' : ''}`} aria-label="核心仓预算">
      <CoreMetric icon={<WalletCards size={18} />} label="核心仓目标预算" value={target} note={`总资产动态目标 ${(targetFraction * 100).toFixed(1)}%`} />
      <CoreMetric icon={<Landmark size={18} />} label="已分配核心本金" value={coreCapital.assigned} note={fundingGap > 0 ? `距动态目标 ${formatMoney(fundingGap)}` : '本金已达当前目标'} />
      <CoreMetric icon={<CircleDollarSign size={18} />} label="总资金占用" value={coreCapital.committed} note={`股票成本 ${formatMoney(recordedCost)} · Put 担保 ${formatMoney(putCollateral)}`} danger={unfundedCost > 0} />
      <CoreMetric icon={<Banknote size={18} />} label="可用核心本金" value={coreCapital.available} note="新买入优先使用" />
      <CoreMetric icon={<TrendingUp size={18} />} label="最新估算市值" value={currentValue} note="BRK.B、VOO 与 SCHD 合计" danger={overTarget > 0} />
      <CoreMetric icon={<Gauge size={18} />} label="目标剩余容量" value={remaining} note={putCollateral ? `全部接股后约剩 ${formatMoney(Math.max(remaining - putCollateral, 0))}` : market?.core?.mode === 'full' ? '已进入满仓轮换模式' : '按当前市值计算'} />
      <CoreMetric icon={<WalletCards size={18} />} label="可用现金" value={cashAvailable} note="核心本金不足时可转入" />
    </section>

    {(overTarget > 0 || unfundedCost > 0) && <div className="core-budget-alert" role="alert"><AlertTriangle size={17} /><span>{overTarget > 0 && <>核心仓市值超过目标预算 {formatMoney(overTarget)}。</>}{unfundedCost > 0 && <>股票成本与待接股担保超过实到核心资金 {formatMoney(unfundedCost)}。</>}</span></div>}

    <CorePutRegister puts={corePuts} market={market} />

    <CoreRelativeBoard decision={market?.core ?? null} />
    <CoreBuySignal decision={market?.core ?? null} />
    <CorePutSignal decision={market?.core ?? null} />

    <section className="core-lot-register">
      <div className="section-title"><div><p>PURCHASE LOTS</p><h2>核心仓成交批次</h2></div><span>未实现 {formatMoney(currentValue - recordedCost)}</span></div>
      {lots.length ? <div className="core-lot-table">
        <div className="core-lot-row header"><span>标的</span><span>批次 / 成交日</span><span>股数</span><span>成交价</span><span>成本</span><span>估算市值</span><span>未实现</span></div>
        {numberedLots(lots).map(({ position, number }) => {
          const cost = position.entry_price * position.quantity * position.multiplier
          const value = position.quantity * position.multiplier * (priceBySymbol.get(position.symbol) ?? position.current_price)
          return <div className="core-lot-row" key={position.id}>
            <strong className="core-lot-symbol">{position.symbol}</strong><span>第 {number} 笔 · {position.opened_on}</span><span>{position.quantity} 股</span><span>{formatMoney(position.entry_price)}</span><span>{formatMoney(cost)}</span><span>{formatMoney(value)}</span><em className={value - cost >= 0 ? 'positive' : 'negative'}>{formatMoney(value - cost)}</em>
          </div>
        })}
      </div> : <div className="core-empty"><Gauge size={22} /><p>IBKR 报表中暂无 BRK.B、VOO 或 SCHD 持仓</p></div>}
    </section>
  </div>
}

function CorePutRegister({ puts, market }: { puts: WheelPutLot[]; market: MarketSnapshot | null }) {
  const groups = groupCorePuts(puts)
  const collateral = puts.reduce((total, put) => total + put.collateral, 0)
  const contracts = puts.reduce((total, put) => total + put.open_quantity, 0)
  return <section className={`core-put-register ${puts.length ? 'active' : ''}`} aria-label="核心仓 Sell Put 建仓">
    <header>
      <div className="core-put-title"><ShieldCheck size={20} /><div><p>CORE ACQUISITION PUTS</p><h2>核心仓 Sell Put 建仓</h2></div></div>
      <div className="core-put-summary"><span>{groups.length} 个标的 · {puts.length} 笔 · {contracts} 张待接股</span><strong>{formatMoney(collateral)}</strong><small>核心本金担保占用</small></div>
    </header>
    {puts.length ? <div className="core-put-groups">{groups.map((group) => <CorePutGroup key={group.symbol} group={group} market={market} />)}</div> : <div className="core-put-empty"><CalendarClock size={20} /><span>当前没有用于核心仓建仓的 Sell Put</span></div>}
  </section>
}

function CorePutGroup({ group, market }: { group: CorePutGroupData; market: MarketSnapshot | null }) {
  return <article className="core-put-group" aria-label={`${group.symbol} 核心仓 Sell Put`}>
    <header className="core-put-group-header">
      <div className="core-put-group-title"><strong>{group.symbol}</strong><span>{group.puts.length} 笔 · {group.contracts} 张待接股</span></div>
      <div className="core-put-group-stats">
        <div><span>总担保占用</span><strong>{formatMoney(group.collateral)}</strong></div>
        <div><span>已收权利金</span><strong>{formatMoney(group.premiumIncome)}</strong></div>
        <div><span>到期范围</span><strong>{group.expirationRange}</strong></div>
      </div>
    </header>
    <div className="core-put-group-details">
      <div className="core-put-row header"><span>建仓批次</span><span>到期日</span><span>行权 / 有效成本</span><span>权利金</span><span>担保占用</span><span>开仓年化</span><span>接股状态</span></div>
      {group.puts.map((put, index) => <CorePutRow key={put.id} put={put} index={index} market={market} />)}
    </div>
  </article>
}

function CorePutRow({ put, index, market }: { put: WheelPutLot; index: number; market: MarketSnapshot | null }) {
  const spot = market?.core?.assets?.find((asset) => asset.symbol === put.symbol)?.price
    ?? (put.symbol === 'BRK.B' ? market?.market.brk_b.price : put.symbol === 'SCHD' ? market?.market.schd?.price : market?.market.voo?.price)
  const effectiveCost = put.strike - put.premium
  const premiumIncome = put.premium * 100 * put.open_quantity
  const dte = daysBetween(market?.as_of ?? put.trade_date, put.expiration)
  const buffer = spot ? spot / put.strike - 1 : null
  const assignmentRisk = buffer != null && buffer < 0
  return <div className={`core-put-row ${assignmentRisk ? 'assignment-risk' : ''}`}>
    <div><strong>第 {index + 1} 笔</strong><small>{put.open_quantity} 张 · {put.trade_date}</small></div>
    <div><strong>{put.expiration}</strong><small>剩余 {Math.max(dte, 0)} 天</small></div>
    <div><strong>{formatMoney(put.strike)} / {formatMoney(effectiveCost)}</strong><small>每股有效接股成本</small></div>
    <div><strong>{formatMoney(premiumIncome)}</strong><small>{formatMoney(put.premium)} / 股</small></div>
    <div><strong>{formatMoney(put.collateral)}</strong><small>{put.open_quantity * 100} 股潜在接股</small></div>
    <div><strong>{formatPercent(put.opening_annualized_return)}</strong><small>{put.opening_dte} DTE 开仓</small></div>
    <div><strong>{assignmentRisk ? '已低于行权价' : buffer == null ? '等待行情' : `缓冲 ${formatPercent(buffer)}`}</strong><small>{assignmentRisk ? '按核心仓长期持有处理' : '接股后归入核心仓，不卖 CC'}</small></div>
  </div>
}

type CorePutGroupData = {
  symbol: string
  puts: WheelPutLot[]
  contracts: number
  collateral: number
  premiumIncome: number
  expirationRange: string
}

function groupCorePuts(puts: WheelPutLot[]): CorePutGroupData[] {
  const grouped = new Map<string, WheelPutLot[]>()
  for (const put of puts) grouped.set(put.symbol, [...(grouped.get(put.symbol) ?? []), put])
  return [...grouped.entries()].map(([symbol, groupedPuts]) => {
    const sortedPuts = [...groupedPuts].sort((left, right) => left.expiration.localeCompare(right.expiration) || left.id - right.id)
    const expirations = sortedPuts.map((put) => put.expiration)
    return {
      symbol,
      puts: sortedPuts,
      contracts: sortedPuts.reduce((total, put) => total + put.open_quantity, 0),
      collateral: sortedPuts.reduce((total, put) => total + put.collateral, 0),
      premiumIncome: sortedPuts.reduce((total, put) => total + put.premium * 100 * put.open_quantity, 0),
      expirationRange: expirations[0] === expirations[expirations.length - 1] ? expirations[0] : `${expirations[0]} ～ ${expirations[expirations.length - 1]}`,
    }
  })
}

function CoreRelativeBoard({ decision }: { decision: CoreStrategyDecision | null }) {
  const assets = decision?.assets ?? []
  return <section className="core-relative-board" aria-label="核心仓相对状态">
    <header><div><p>CORE ROUTING</p><h2>核心资产相对状态</h2></div><span>{decision ? `Z ${formatSigned(decision.ratio_z, 2)} · BRK.B / VOO 路由确认 ${decision.route_confirmation_days} 日` : '等待刷新行情'}</span></header>
    <div className="core-asset-head" aria-hidden="true"><span>标的 / 当前市值</span><span>价格趋势</span><span>日跌 / 回撤 / RSI</span><span>相对表现</span><span>当前档位</span></div>
    {assets.map((asset) => <CoreAssetRow asset={asset} selected={decision?.selected_symbol === asset.symbol} totalValue={decision?.total_value ?? 0} key={asset.symbol} />)}
    {!assets.length && <div className="core-relative-empty"><BarChart3 size={19} />刷新行情后计算核心资产状态</div>}
  </section>
}

function CoreAssetRow({ asset, selected, totalValue }: { asset: CoreAssetDecision; selected: boolean; totalValue: number }) {
  return <article className={`core-asset-row ${selected ? 'selected' : ''}`} aria-label={`${asset.symbol} 核心仓状态`}>
    <div><b>{asset.symbol}</b><strong>{formatMoney(asset.current_value)}</strong><small>当前占核心仓 {totalValue > 0 ? `${(asset.current_value / totalValue * 100).toFixed(1)}%` : '0.0%'}</small></div>
    <div><span>现价 / MA200</span><strong>{formatMoney(asset.price)} / {formatMoney(asset.ma200)}</strong><small>{asset.below_ma200_two_days ? '连续两日低于 MA200' : '未触发趋势保护'}</small></div>
    <div><span>日涨跌 / 回撤 / RSI14</span><strong>{formatPercent(asset.daily_change)} / {formatPercent(-asset.drawdown)} / {asset.rsi14.toFixed(1)}</strong><small>{(asset.signal_score ?? 0) > 0 ? `机会积分 ${asset.signal_score} / 6` : '暂未积累回调分数'}</small></div>
    <div><span>20 日 / 半年</span><strong>{formatPercent(asset.return_20d)} / {formatPercent(asset.return_126d)}</strong><small>用于相对路由与满仓轮换</small></div>
    <div><span>信号档位</span><strong>{coreBuyLabel(asset)}</strong><small>{selected ? '当前优先标的' : '本次未选中'}</small></div>
  </article>
}

function CoreBuySignal({ decision }: { decision: CoreStrategyDecision | null }) {
  const recommendation = decision?.recommendation
  if (!decision) return <section className="core-signal waiting" aria-label="核心仓买入建议"><Gauge size={19} /><div><span>等待行情</span><strong>刷新后计算新增资金优先标的</strong></div></section>
  if (decision.mode === 'full') return <section className="core-signal waiting" aria-label="核心仓买入建议"><Gauge size={19} /><div><span>核心仓已满</span><strong>暂停普通定投，转入满仓轮换监控</strong><small>满仓阈值 {formatMoney(decision.full_threshold)}</small></div></section>
  if ((decision.pending_put_collateral ?? 0) > 0 && !recommendation?.actionable) return <section className="core-signal waiting" aria-label="核心仓买入建议"><ShieldCheck size={20} /><div><span>已有 Put 建仓安排</span><strong>{decision.unplanned_gap === 0 ? '待接股安排已覆盖目标，暂无新增容量' : '暂停常规定投，等待明显回调机会'}</strong><small>待接股担保 {formatMoney(decision.pending_put_collateral ?? 0)} · 未安排缺口 {formatMoney(decision.unplanned_gap ?? 0)}</small></div></section>
  if (!recommendation) return <section className="core-signal waiting" aria-label="核心仓买入建议"><Gauge size={19} /><div><span>等待</span><strong>当前没有可执行的新增买入建议</strong></div></section>
  const amountNote = `${recommendation.trend_reduced ? '趋势保护减半 · ' : ''}使用${decision.pending_put_collateral ? '扣除待接股后的缺口' : '目标缺口'}的 ${(recommendation.fraction * 100).toFixed(1)}%${recommendation.cash_required > 0 ? ` · 需从现金转入 ${formatMoney(recommendation.cash_required)}` : ''}`
  return <section className={`core-signal ${recommendation.actionable ? 'actionable' : 'waiting'}`} aria-label="核心仓买入建议">
    <TrendingUp size={20} />
    <div><span>{coreBuyLabel(recommendation)} · {recommendation.symbol}</span><strong>{recommendation.actionable ? `下一笔优先买入 ${recommendation.symbol}` : '当前无需新增买入'}</strong><small>日涨跌 {formatPercent(recommendation.daily_change)} · 回撤 {formatPercent(-recommendation.drawdown)} · RSI {recommendation.rsi14.toFixed(1)}</small></div>
    <div><span>建议金额</span><strong>{formatMoney(recommendation.executable_amount)}</strong><small>{amountNote}</small></div>
    <div><span>估算数量</span><strong>约 {recommendation.shares.toFixed(4)} 股</strong><small>按 {formatMoney(recommendation.price)}</small></div>
  </section>
}

function CorePutSignal({ decision }: { decision: CoreStrategyDecision | null }) {
  const put = decision?.sell_put
  if (!put) return null
  const labels: Record<string, string> = {
    waiting: '等待普通回调与上行趋势', pending_puts: '已有待接股安排，暂不追加 Put',
    direct_buy_preferred: '回调较深，优先评估直接买股', no_support: '暂无合适的支撑参考',
    insufficient_reserve: '预留直接买股资金后，不足担保 1 张 Put', opportunity: '可评估 Sell Put 建仓',
  }
  return <section className={`core-signal ${put.actionable ? 'actionable' : 'waiting'}`} aria-label="核心仓 Sell Put 建议">
    <ShieldCheck size={20} />
    <div><span>Sell Put 建仓{put.symbol ? ` · ${put.symbol}` : ''}</span><strong>{labels[put.code] ?? '等待'}</strong><small>7～21 天 · 每次 1 张 · 接股后归核心仓</small></div>
    {put.reference_strike != null && <div><span>参考行权价</span><strong>{formatMoney(put.reference_strike)}</strong><small>{put.strike_cap != null ? `策略上限 ${formatMoney(put.strike_cap)} · ` : ''}按实际挂牌行权价向下选择</small></div>}
    <div><span>{put.reference_strike != null ? '参考接股资金' : '直接买股资金预留'}</span><strong>{formatMoney(put.reference_strike != null ? put.collateral : put.direct_buy_reserve)}</strong><small>{put.reference_strike != null ? `保留直接买股资金至少 ${formatMoney(put.direct_buy_reserve)}` : '可用策略资金的 50%'}</small></div>
  </section>
}

function CoreMetric({ icon, label, value, note, danger = false }: { icon: React.ReactNode; label: string; value: number; note: string; danger?: boolean }) {
  return <div className={danger ? 'danger' : ''}>{icon}<span>{label}</span><strong>{formatMoney(value)}</strong><small>{note}</small></div>
}

function numberedLots(lots: Position[]) {
  const counters = new Map<string, number>()
  return [...lots]
    .sort((left, right) => left.opened_on.localeCompare(right.opened_on) || left.id - right.id)
    .map((position) => {
      const number = (counters.get(position.symbol) ?? 0) + 1
      counters.set(position.symbol, number)
      return { position, number }
    })
    .reverse()
}

function formatPercent(value: number | null | undefined) { return value == null || !Number.isFinite(value) ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%` }
function formatSigned(value: number, digits: number) { return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}` }
function daysBetween(start: string, end: string) { return Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000) }
function coreBuyLabel(asset: Pick<CoreAssetDecision, 'code' | 'fraction'>) {
  if (asset.code === 'monthly' && asset.fraction <= .025) return '高位极轻定投'
  if (asset.code === 'monthly' && asset.fraction <= .05) return '高位轻仓定投'
  const labels: Record<string, string> = { monthly: '常规定投', pullback: '普通回调', correction: '明显调整', deep: '深度回撤', cooldown: '冷却期', waiting: '等待', at_target: '目标已满', pending_puts: '已有 Put 建仓安排', put_preferred: '优先评估 Sell Put' }
  return labels[asset.code] ?? asset.code
}
