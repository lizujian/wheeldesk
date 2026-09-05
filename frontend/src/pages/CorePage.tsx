import { AlertTriangle, ArrowRightLeft, Banknote, BarChart3, CalendarClock, CircleDollarSign, Gauge, Landmark, ShieldCheck, TrendingUp, WalletCards } from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { CoreAssetDecision, CoreStrategyDecision, MarketSnapshot, PortfolioSummary, Position, WheelOverview, WheelPutLot } from '../lib/types'
import './CorePage.css'

const coreSymbols = new Set(['BRK.B', 'VOO'])

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
    <div className="page-heading"><div><p className="eyebrow">BRK.B + VOO CORE EQUITY</p><h1>核心仓相对定投</h1><span>无固定内部比例 · 新增资金路由与满仓轮换</span></div><span>{lots.length} 笔股票 · {corePuts.length} 笔待接股</span></div>

    <section className={`core-budget-band ${overTarget > 0 || unfundedCost > 0 ? 'danger' : ''}`} aria-label="核心仓预算">
      <CoreMetric icon={<WalletCards size={18} />} label="核心仓目标预算" value={target} note={`总资产动态目标 ${(targetFraction * 100).toFixed(1)}%`} />
      <CoreMetric icon={<Landmark size={18} />} label="已分配核心本金" value={coreCapital.assigned} note={fundingGap > 0 ? `距动态目标 ${formatMoney(fundingGap)}` : '本金已达当前目标'} />
      <CoreMetric icon={<CircleDollarSign size={18} />} label="总资金占用" value={coreCapital.committed} note={`股票成本 ${formatMoney(recordedCost)} · Put 担保 ${formatMoney(putCollateral)}`} danger={unfundedCost > 0} />
      <CoreMetric icon={<Banknote size={18} />} label="可用核心本金" value={coreCapital.available} note="新买入优先使用" />
      <CoreMetric icon={<TrendingUp size={18} />} label="最新估算市值" value={currentValue} note="BRK.B 与 VOO 合计" danger={overTarget > 0} />
      <CoreMetric icon={<Gauge size={18} />} label="目标剩余容量" value={remaining} note={putCollateral ? `全部接股后约剩 ${formatMoney(Math.max(remaining - putCollateral, 0))}` : market?.core?.mode === 'full' ? '已进入满仓轮换模式' : '按当前市值计算'} />
      <CoreMetric icon={<WalletCards size={18} />} label="可用现金" value={cashAvailable} note="核心本金不足时可转入" />
    </section>

    {(overTarget > 0 || unfundedCost > 0) && <div className="core-budget-alert" role="alert"><AlertTriangle size={17} /><span>{overTarget > 0 && <>核心仓市值超过目标预算 {formatMoney(overTarget)}。</>}{unfundedCost > 0 && <>股票成本与待接股担保超过实到核心资金 {formatMoney(unfundedCost)}。</>}</span></div>}

    <CorePutRegister puts={corePuts} market={market} />

    <CoreRelativeBoard decision={market?.core ?? null} />
    <CoreBuySignal decision={market?.core ?? null} />
    <CoreRotationSignal decision={market?.core ?? null} />

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
      </div> : <div className="core-empty"><Gauge size={22} /><p>IBKR 报表中暂无 BRK.B 或 VOO 持仓</p></div>}
    </section>
  </div>
}

function CorePutRegister({ puts, market }: { puts: WheelPutLot[]; market: MarketSnapshot | null }) {
  const collateral = puts.reduce((total, put) => total + put.collateral, 0)
  return <section className={`core-put-register ${puts.length ? 'active' : ''}`} aria-label="核心仓 Sell Put 建仓">
    <header>
      <div className="core-put-title"><ShieldCheck size={20} /><div><p>CORE ACQUISITION PUTS</p><h2>核心仓 Sell Put 建仓</h2></div></div>
      <div className="core-put-summary"><span>{puts.length} 笔待接股</span><strong>{formatMoney(collateral)}</strong><small>核心本金担保占用</small></div>
    </header>
    {puts.length ? <div className="core-put-table">
      <div className="core-put-row header"><span>建仓批次</span><span>到期日</span><span>行权 / 有效成本</span><span>权利金</span><span>担保占用</span><span>开仓年化</span><span>接股状态</span></div>
      {puts.map((put, index) => <CorePutRow key={put.id} put={put} index={index} market={market} />)}
    </div> : <div className="core-put-empty"><CalendarClock size={20} /><span>当前没有用于核心仓建仓的 Sell Put</span></div>}
  </section>
}

function CorePutRow({ put, index, market }: { put: WheelPutLot; index: number; market: MarketSnapshot | null }) {
  const spot = market?.core?.assets?.find((asset) => asset.symbol === put.symbol)?.price
    ?? (put.symbol === 'BRK.B' ? market?.market.brk_b.price : market?.market.voo?.price)
  const effectiveCost = put.strike - put.premium
  const premiumIncome = put.premium * 100 * put.open_quantity
  const dte = daysBetween(market?.as_of ?? put.trade_date, put.expiration)
  const buffer = spot ? spot / put.strike - 1 : null
  const assignmentRisk = buffer != null && buffer < 0
  return <div className={`core-put-row ${assignmentRisk ? 'assignment-risk' : ''}`}>
    <div><strong>{put.symbol}</strong><small>错峰第 {index + 1} 笔 · {put.open_quantity} 张</small></div>
    <div><strong>{put.expiration}</strong><small>剩余 {Math.max(dte, 0)} 天</small></div>
    <div><strong>{formatMoney(put.strike)} / {formatMoney(effectiveCost)}</strong><small>每股有效接股成本</small></div>
    <div><strong>{formatMoney(premiumIncome)}</strong><small>{formatMoney(put.premium)} / 股</small></div>
    <div><strong>{formatMoney(put.collateral)}</strong><small>{put.open_quantity * 100} 股潜在接股</small></div>
    <div><strong>{formatPercent(put.opening_annualized_return)}</strong><small>{put.opening_dte} DTE 开仓</small></div>
    <div><strong>{assignmentRisk ? '已低于行权价' : buffer == null ? '等待行情' : `缓冲 ${formatPercent(buffer)}`}</strong><small>{assignmentRisk ? '按核心仓长期持有处理' : '接股后归入核心仓，不卖 CC'}</small></div>
  </div>
}

function CoreRelativeBoard({ decision }: { decision: CoreStrategyDecision | null }) {
  const assets = decision?.assets ?? []
  return <section className="core-relative-board" aria-label="核心仓相对状态">
    <header><div><p>RELATIVE ROUTING</p><h2>BRK.B / VOO 相对状态</h2></div><span>{decision ? `Z ${formatSigned(decision.ratio_z, 2)} · 路由确认 ${decision.route_confirmation_days} 日` : '等待刷新行情'}</span></header>
    <div className="core-asset-head" aria-hidden="true"><span>标的 / 当前市值</span><span>价格趋势</span><span>日跌 / 回撤 / RSI</span><span>相对表现</span><span>当前档位</span></div>
    {assets.map((asset) => <CoreAssetRow asset={asset} selected={decision?.selected_symbol === asset.symbol} totalValue={decision?.total_value ?? 0} key={asset.symbol} />)}
    {!assets.length && <div className="core-relative-empty"><BarChart3 size={19} />刷新行情后计算两只标的的相对偏离</div>}
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
  if (!recommendation) return <section className="core-signal waiting" aria-label="核心仓买入建议"><Gauge size={19} /><div><span>等待</span><strong>当前没有可执行的新增买入建议</strong></div></section>
  const amountNote = `${recommendation.trend_reduced ? '趋势保护减半 · ' : ''}使用目标缺口的 ${(recommendation.fraction * 100).toFixed(1)}%${recommendation.cash_required > 0 ? ` · 需从现金转入 ${formatMoney(recommendation.cash_required)}` : ''}`
  return <section className={`core-signal ${recommendation.actionable ? 'actionable' : 'waiting'}`} aria-label="核心仓买入建议">
    <TrendingUp size={20} />
    <div><span>{coreBuyLabel(recommendation)} · {recommendation.symbol}</span><strong>{recommendation.actionable ? `下一笔优先买入 ${recommendation.symbol}` : '当前无需新增买入'}</strong><small>日涨跌 {formatPercent(recommendation.daily_change)} · 回撤 {formatPercent(-recommendation.drawdown)} · RSI {recommendation.rsi14.toFixed(1)}</small></div>
    <div><span>建议金额</span><strong>{formatMoney(recommendation.executable_amount)}</strong><small>{amountNote}</small></div>
    <div><span>估算数量</span><strong>约 {recommendation.shares.toFixed(4)} 股</strong><small>按 {formatMoney(recommendation.price)}</small></div>
  </section>
}

function CoreRotationSignal({ decision }: { decision: CoreStrategyDecision | null }) {
  const rotation = decision?.rotation
  const labels: Record<string, string> = { waiting: '等待核心仓满仓', watch: '相对偏离观察中', cooldown: '轮换冷却期', reset_wait: '等待相对比率回归中性区', standard: '标准轮换', strong: '强轮换', extreme: '极端轮换' }
  return <section className={`core-rotation ${rotation?.actionable ? 'actionable' : ''}`} aria-label="核心仓满仓轮换建议">
    <header><ArrowRightLeft size={19} /><div><span>FULL CORE ROTATION</span><strong>{rotation ? labels[rotation.code] : '等待行情'}</strong><small>{decision?.mode === 'full' ? `轮换确认 ${decision.rotation_confirmation_days} 日 · 半年收益差 ${formatPercent(rotation?.return_spread ?? 0)}` : '核心仓达到目标的 98% 后启用'}</small></div></header>
    <div><span>轮换方向</span><strong>{rotation?.sell_symbol && rotation.buy_symbol ? `${rotation.sell_symbol} → ${rotation.buy_symbol}` : '暂不轮换'}</strong><small>{rotation?.defensive_half ? '目标标的连续两日低于 MA200，建议金额已减半' : '卖出与买入金额等额'}</small></div>
    <div><span>建议金额</span><strong>{formatMoney(rotation?.amount ?? 0)}</strong><small>{rotation?.cooldown_days_remaining ? `冷却期剩余 ${rotation.cooldown_days_remaining} 个交易日` : '系统建议，用户确认'}</small></div>
    <div><span>估算双腿</span><strong>{rotation?.sell_symbol ? `卖 ${rotation.sell_shares.toFixed(4)} · 买 ${rotation.buy_shares.toFixed(4)} 股` : '等待触发'}</strong><small>券商成交后由 IBKR 报表同步</small></div>
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
  const labels: Record<string, string> = { monthly: '常规定投', pullback: '普通回调', correction: '明显调整', deep: '深度回撤', cooldown: '冷却期', waiting: '等待', at_target: '目标已满' }
  return labels[asset.code] ?? asset.code
}
