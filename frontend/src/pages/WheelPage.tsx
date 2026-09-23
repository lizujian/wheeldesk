import { ReactNode, useState } from 'react'
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  BadgeDollarSign,
  Banknote,
  Check,
  Circle,
  CircleDollarSign,
  Clock3,
  Gauge,
  History,
  Landmark,
  Layers3,
  RefreshCw,
  ShieldAlert,
  Target,
  WalletCards,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import { formatMoney } from '../components/AllocationChart'
import type {
  MarketSnapshot,
  WheelCallLot,
  WheelOverview,
  WheelPutLot,
  WheelShareLot,
} from '../lib/types'
import './WheelPage.css'

const checkLabels: Record<string, string> = {
  above_ma200: 'QQQ 高于 MA200',
  rsi_below_50: 'RSI14 低于 50',
  bearish_candle: '当日收阴线',
}
const putStates: Record<WheelPutLot['state'], string> = {
  open: 'Put 持仓中', closed: '已提前平仓', expired: '已到期归零', assigned: '已接股', rolled: '已展期', voided: '已撤销',
}
const callStates: Record<WheelCallLot['state'], string> = {
  open: 'CC 持仓中', closed: '已买回平仓', expired: '已到期', called_away: '股票已扣走', voided: '已撤销',
}

export function WheelPage({ market, overview }: {
  market: MarketSnapshot | null
  overview: WheelOverview
}) {
  const [strategy, setStrategy] = useState<'tqqq' | 'club'>('tqqq')
  const activeRounds = activeWheelRounds(overview, strategy)
  const activeCount = activeRounds.reduce((count, round) => count + round.puts.length, 0)
  return <div className="page-stack wheel-console">
    <div className="page-heading wheel-heading">
      <div><p className="eyebrow">WHEEL OPERATIONS</p><h1>车轮策略操作台</h1><span>系统提供信号 · 持仓由 IBKR 报表同步</span></div>
      <Link className="secondary-button history-link" to="/wheel/history"><History size={16} />历史记录</Link>
    </div>

    <BudgetBand overview={overview} />

    <nav className="wheel-strategy-tabs" aria-label="车轮子策略">
      <button className={strategy === 'tqqq' ? 'active' : ''} onClick={() => setStrategy('tqqq')}><Layers3 size={17} /><span><strong>TQQQ 两批车轮</strong><small>60 / 40 分批 · 当前 {activeWheelCount(overview, 'tqqq')} 笔</small></span></button>
      <button className={strategy === 'club' ? 'active' : ''} onClick={() => setStrategy('club')}><Landmark size={17} /><span><strong>万亿俱乐部车轮</strong><small>个股独立周期 · 当前 {activeWheelCount(overview, 'club')} 笔</small></span></button>
    </nav>

    {strategy === 'tqqq' ? <>
      <div className="two-column">
        <EntryChecks market={market} />
        <SupportMap market={market} />
      </div>
      <OpportunityBand overview={overview} market={market} />
    </> : <ClubWheelDesk market={market} />}

    {market?.risk.defensive_cc_required_if_holding && <div className="defense-note" role="alert">
      <ShieldAlert size={18} /><span>防御规则已启用：继续持有 TQQQ 时，CC 行权价必须接近现价或位于价内。</span>
    </div>}

    <section className="wheel-register" aria-label="车轮轮次记录">
      <div className="section-title">
        <div><p>LIVE REGISTER</p><h2>当前需要管理</h2></div>
        <span>{activeCount} 笔活动仓位 · 累计已实现 {formatMoney(overview.realized_profit)}</span>
      </div>
      {activeRounds.length === 0
        ? <div className="wheel-empty"><CircleDollarSign size={22} /><div><p>当前没有需要管理的{strategy === 'tqqq' ? ' TQQQ' : '个股'}车轮仓位</p><small>已结束订单已移至历史记录。</small></div></div>
        : activeRounds.map((round) => <section className={`wheel-round ${round.status}`} key={round.id}>
          <header>
            <div><span>第 {round.number} 轮</span><strong>{round.status === 'active' ? '进行中' : '已结束'}</strong></div>
            <div><small>{round.opened_on}{round.closed_on ? ` 至 ${round.closed_on}` : ''}</small><b>{formatMoney(round.realized_profit)}</b></div>
          </header>
          <div className="wheel-lots">
            {round.puts.map((put) => <PutLot key={put.id} put={put} roundNumber={round.number} />)}
          </div>
        </section>)}
    </section>
  </div>
}

export function WheelHistoryPage({ overview }: { overview: WheelOverview }) {
  const [filter, setFilter] = useState<'all' | 'tqqq' | 'club'>('all')
  const rounds = historyWheelRounds(overview, filter)
  const records = rounds.reduce((count, round) => count + round.puts.length, 0)
  return <div className="page-stack wheel-console wheel-history-page">
    <div className="page-heading wheel-heading">
      <div><p className="eyebrow">WHEEL ARCHIVE</p><h1>车轮历史记录</h1><span>已平仓、展期、到期、完成接股闭环与撤销记录</span></div>
      <Link className="secondary-button history-link" to="/wheel"><ArrowLeft size={16} />返回操作台</Link>
    </div>
    <section className="history-summary" aria-label="车轮历史摘要">
      <div><Archive size={18} /><span>历史订单</span><strong>{records}</strong></div>
      <div><Clock3 size={18} /><span>全局完成轮次</span><strong>{overview.rounds.filter((round) => round.status === 'completed').length}</strong></div>
      <div><BadgeDollarSign size={18} /><span>全局累计已实现</span><strong>{formatMoney(overview.realized_profit)}</strong></div>
    </section>
    <div className="history-filter" role="group" aria-label="筛选历史记录">
      {([['all', '全部'], ['tqqq', 'TQQQ'], ['club', '万亿俱乐部']] as const).map(([value, label]) => <button className={filter === value ? 'active' : ''} key={value} onClick={() => setFilter(value)}>{label}</button>)}
    </div>
    <section className="wheel-register history-register" aria-label="车轮历史订单">
      {rounds.length === 0 ? <div className="wheel-empty"><Archive size={22} /><p>当前筛选下没有历史订单</p></div> : rounds.map((round) => <section className={`wheel-round ${round.status}`} key={round.id}>
        <header><div><span>第 {round.number} 轮</span><strong>{round.status === 'voided' ? '已撤销' : '历史'}</strong></div><div><small>{round.opened_on}{round.closed_on ? ` 至 ${round.closed_on}` : ''}</small><b>{formatMoney(round.realized_profit)}</b></div></header>
        <div className="wheel-lots">{round.puts.map((put) => <PutLot key={put.id} put={put} roundNumber={round.number} />)}</div>
      </section>)}
    </section>
  </div>
}

export function BudgetBand({ overview }: { overview: WheelOverview }) {
  const capital = overview.capital ?? {
    assigned: overview.budget.funded,
    put_collateral: overview.budget.exposure,
    share_capital: 0,
    committed: overview.budget.exposure,
    available: Math.max(overview.budget.funded - overview.budget.exposure, 0),
    cash_occupancy: Math.max(overview.budget.exposure - overview.budget.funded, 0),
    cash_available: 0,
    margin_shortfall: 0,
  }
  const over = capital.cash_occupancy > 0
  const cashGap = capital.margin_shortfall > 0
  const targetOver = Math.max(capital.committed - overview.budget.budget, 0)
  const rows = [
    { label: '期权共享目标', value: overview.budget.budget, icon: <Target size={18} />, note: `总资产 ${(overview.budget.target_fraction * 100).toFixed(1)}%` },
    { label: '期权共享本金', value: capital.assigned, icon: <WalletCards size={18} />, note: `共享可用 ${formatMoney(capital.available)}` },
    { label: 'Put 担保', value: capital.put_collateral, icon: <CircleDollarSign size={18} />, note: '从开仓日开始占用' },
    { label: '接股本金', value: capital.share_capital, icon: <BadgeDollarSign size={18} />, note: '行权后继续占用' },
    { label: '共享总占用', value: capital.committed, icon: <Gauge size={18} />, note: '含车轮与 LEAPS 成本' },
    { label: '超过共享目标', value: targetOver, icon: <AlertTriangle size={18} />, note: targetOver > 0 ? '缩减期不建议新增仓位' : '共享目标范围内' },
    { label: '临时占用现金', value: capital.cash_occupancy, icon: <Banknote size={18} />, note: over ? '超过期权共享本金' : '未占用现金' },
    { label: '账户现金覆盖缺口', value: capital.margin_shortfall, icon: cashGap ? <AlertTriangle size={18} /> : <Check size={18} />, note: cashGap ? '核心仓与期权占用合计超过流动现金' : `可用现金 ${formatMoney(capital.cash_available)}` },
  ]
  return <>
    <section className={`wheel-budget ${over || cashGap || targetOver ? 'over-budget' : ''}`} aria-label="车轮预算">
      {rows.map((row) => <div key={row.label} className={(row.label === '超过共享目标' && targetOver > 0) || (row.label === '临时占用现金' && over) || (row.label === '账户现金覆盖缺口' && cashGap) ? 'danger' : ''}>
        {row.icon}<span>{row.label}</span><strong>{formatMoney(row.value)}</strong>{row.note && <small>{row.note}</small>}
      </div>)}
    </section>
    {(over || cashGap || targetOver > 0) && <div className="wheel-budget-alert" role="alert" aria-label="车轮资金风险"><AlertTriangle size={17} /><span>
      {targetOver > 0 && <>车轮与 LEAPS 合计占用超过共享目标 {formatMoney(targetOver)}，进入策略缩减期。</>}
      {over && <>期权共享池临时占用现金 {formatMoney(capital.cash_occupancy)}。</>}
      {cashGap && <>账户现金覆盖缺口 {formatMoney(capital.margin_shortfall)}，请优先补足。</>}
    </span></div>}
  </>
}

function EntryChecks({ market }: { market: MarketSnapshot | null }) {
  return <section className="rule-panel">
    <div className="section-title"><div><p>ENTRY CHECK</p><h2>Sell Put 开仓条件</h2></div>{market?.wheel.eligible && <span className="opportunity-tag">机会已出现</span>}</div>
    {market ? <>
      <div className="condition-list">{Object.entries(market.wheel.checks).map(([key, passed]) => <div key={key}>
        <span className={passed ? 'pass' : 'fail'}>{passed ? <Check size={14} /> : <Circle size={12} />}</span>
        <strong>{checkLabels[key]}</strong><em>{passed ? '满足' : '未满足'}</em>
      </div>)}</div>
      <div className="quote-grid">
        <div><span>QQQ</span><strong>{formatMoney(market.market.qqq.price)}</strong><small>MA200 {formatMoney(market.market.qqq.ma200)}</small></div>
        <div><span>RSI14</span><strong>{market.market.qqq.rsi14.toFixed(1)}</strong><small>{market.market.qqq.bearish ? '阴线' : '阳线'}</small></div>
        <div><span>VIX</span><strong>{market.market.vix.price.toFixed(1)}</strong><small>{market.market.vix.price >= 30 ? '现金评估' : '常态区间'}</small></div>
      </div>
    </> : <EmptyMarket />}
  </section>
}

function SupportMap({ market }: { market: MarketSnapshot | null }) {
  return <section className="support-panel">
    <div className="section-title"><div><p>STRIKE MAP</p><h2>TQQQ 支撑与行权价</h2></div><Target size={20} /></div>
    {market ? <>
      <div className="support-primary"><span>30 多天 Put 首选参考</span><strong>{formatMoney(market.wheel.reference_strike)}</strong><small>{market.wheel.dte_range[0]}–{market.wheel.dte_range[1]} DTE · Delta {market.wheel.delta_range[0]}–{market.wheel.delta_range[1]}</small></div>
      <div className="support-list">{market.wheel.supports.length ? market.wheel.supports.map((level, index) => <div key={`${level.kind}-${index}`}>
        <span>{level.kind === 'swing_cluster' ? '波段低点簇' : level.kind.toUpperCase()}</span><strong>{formatMoney(level.price)}</strong>
        <small>{level.kind === 'swing_cluster' ? `触及 ${level.touches} 次` : '结构支撑'} · 距现价 {(level.distance_pct * 100).toFixed(1)}%</small>
      </div>) : <p className="empty-copy">暂未识别到可靠重复支撑，参考价仅按 10% OTM 计算。</p>}</div>
    </> : <EmptyMarket />}
  </section>
}

function OpportunityBand({ overview, market }: { overview: WheelOverview; market: MarketSnapshot | null }) {
  const reducing = overview.budget.over_budget > 0 || (overview.capital?.committed ?? overview.budget.exposure) >= overview.budget.budget
  return <section className={`wheel-opportunity ${market?.wheel.eligible && !reducing ? 'eligible' : ''} ${reducing ? 'reducing' : ''}`}>
    <div><p className="eyebrow">60 / 40 DEPLOYMENT</p><h2>{reducing ? '策略缩减期' : market?.wheel.eligible ? '当前信号允许评估开仓' : '等待完整开仓信号'}</h2>{reducing && <small>{market?.wheel.eligible ? '技术信号满足，但期权合计占用已超过共享目标，不建议新增 Put。' : '继续管理现有 Put、接股和 Covered Call，等待资金释放。'}</small>}</div>
    <div><span>下一笔第一批上限</span><strong>{formatMoney(overview.recommendations.first)}</strong><small>标准预算 60%</small></div>
    <div><span>同轮第二批上限</span><strong>{formatMoney(overview.recommendations.second)}</strong><small>标准预算 40%</small></div>
  </section>
}

function ClubWheelDesk({ market }: { market: MarketSnapshot | null }) {
  const decisions = [...(market?.wheel_club?.decisions ?? [])].sort((left, right) => {
    if (left.change_fraction == null) return right.change_fraction == null ? left.symbol.localeCompare(right.symbol) : 1
    if (right.change_fraction == null) return -1
    return left.change_fraction - right.change_fraction || left.symbol.localeCompare(right.symbol)
  })
  return <div className="club-wheel-desk">
    <section className="club-wheel-rules">
      <div><Gauge size={18} /><span>趋势与动能</span><strong>QQQ / 个股 &gt; SMA200</strong><small>RSI14 &lt; 40 · 当日跌幅至少 3%</small></div>
      <div><Target size={18} /><span>合约参考</span><strong>支撑位下方</strong><small>30–45 DTE · Delta 0.15–0.25</small></div>
      <div><ShieldAlert size={18} /><span>集中与事件</span><strong>单股最多总资产 5%</strong><small>整个类别每周确认一次 · 到期前无财报</small></div>
    </section>
    <section className="club-wheel-board" aria-label="万亿俱乐部车轮候选">
      <div className="section-title"><div><p>CLUB WATCHLIST</p><h2>个股 Sell Put 候选</h2></div><span>与 LEAPS 共用期权策略额度 · BRK-B 已排除</span></div>
      {!market && <EmptyMarket />}
      {market && decisions.length === 0 && <div className="wheel-empty"><Landmark size={22} /><p>本次没有可评估的公开候选</p></div>}
      {decisions.length > 0 && <div className="club-wheel-table">
        <div className="club-wheel-head" aria-hidden="true"><span>标的 / 状态</span><span>当日行情</span><span>趋势过滤</span><span>支撑 / 担保</span><span>财报</span></div>
        {decisions.map((decision) => {
          const blocked = decision.active_cycle
          const risk = decision.high_risk_put_ids.length > 0
          return <article className={`club-wheel-row ${decision.technical_eligible ? 'eligible' : ''} ${risk ? 'high-risk' : ''}`} aria-label={`${decision.symbol} 万亿俱乐部车轮`} key={decision.symbol}>
            <div className="club-wheel-identity"><b>{decision.symbol}</b><span>{decision.name}</span><small>{blocked ? '已有活动周期' : decision.technical_eligible ? '技术条件满足' : '等待条件'}</small></div>
            <div><span>当前价</span><strong>{decision.current_price == null ? '—' : formatMoney(decision.current_price)}</strong><em className={(decision.change_fraction ?? 0) < 0 ? 'loss' : 'gain'}>{formatChange(decision.change_fraction)}</em></div>
            <div className="club-wheel-checks"><span className={decision.checks.stock_above_ma200 ? 'pass' : ''}>个股 &gt; SMA200</span><span className={decision.checks.qqq_above_ma200 ? 'pass' : ''}>QQQ &gt; SMA200</span><span className={decision.checks.rsi_below_40 ? 'pass' : ''}>RSI {decision.rsi14.toFixed(1)}</span><span className={decision.checks.daily_drop ? 'pass' : ''}>跌幅 ≥ 3%</span></div>
            <div><span>参考行权价</span><strong>{decision.reference_strike == null ? '等待支撑' : formatMoney(decision.reference_strike)}</strong><small>{decision.preferred_support ? `支撑 ${formatMoney(decision.preferred_support.price)} · 担保 ${formatMoney(decision.one_contract_collateral ?? 0)}` : '未识别重复支撑'}</small>{(decision.over_budget || decision.over_concentration) && <em className="loss">{decision.over_budget ? '超过可用预算' : '超过单股 5%'}</em>}</div>
            <div><span>下一财报</span><strong>{decision.earnings_available ? decision.next_earnings_date ?? '45 天外' : '需人工核对'}</strong><small>{decision.checks.earnings_clear ? '当前窗口可评估' : '合约窗口内有财报'}</small></div>
            {risk && <div className="club-wheel-row-alert" role="alert"><ShieldAlert size={15} />连续两日低于个股 SMA200，现有仓位面临行权或持股风险，请优先评估防御。</div>}
          </article>
        })}
      </div>}
      {(market?.wheel_club?.unavailable.length ?? 0) > 0 && <details className="club-wheel-unavailable"><summary>{market!.wheel_club!.unavailable.length} 个候选公开数据不完整</summary>{market!.wheel_club!.unavailable.map((item) => <span key={item.symbol}><b>{item.symbol}</b>{item.error}</span>)}</details>}
    </section>
  </div>
}

export function PutLot({ put, roundNumber }: { put: WheelPutLot; roundNumber: number }) {
  return <article className={`wheel-lot ${put.state}`}>
    <header>
      <div><span>第 {roundNumber} 轮 · {put.symbol === 'TQQQ' ? put.batch_number === 1 ? '第一批' : '第二批' : '独立个股周期'}</span><h3><b className="lot-symbol">{put.symbol}</b> Sell Put #{put.id}</h3></div>
      <strong className={`state-badge ${put.state}`}>{putStates[put.state]}</strong>
    </header>
    <div className="lot-values">
      <Value label="行权价" value={formatMoney(put.strike)} />
      <Value label="权利金 / 股" value={formatMoney(put.premium)} />
      <Value label="合约" value={`${put.open_quantity} / ${put.quantity} 张`} />
      <Value label="到期日" value={put.expiration} />
      <Value label="当前担保" value={formatMoney(put.collateral)} />
      <Value label="已实现" value={formatMoney(put.realized_profit)} />
    </div>
    <PutYieldStrip put={put} />
    {put.rolled_from && <RollLink put={put} direction="from" />}
    {put.rolled_to && <RollLink put={put} direction="to" />}
    <QuoteLine put={put} />
    {put.early_close_code && <div className={`early-close ${put.quote_source === 'public' ? 'actionable' : ''}`} role="alert">
      <BadgeDollarSign size={18} /><div><strong>{put.quote_source === 'public' ? '建议提前平仓' : '进入止盈区'}</strong><span><b>已捕获 {((put.captured_fraction ?? 0) * 100).toFixed(1)}% 权利金 · 估算年化 {formatAnnualized(put.early_close_annualized_return)}</b> · {put.early_close_message}</span></div>
    </div>}
    {put.void_reason && <p className="void-note">撤销原因：{put.void_reason}</p>}
    {put.share_lots.map((share) => <ShareLot key={share.id} share={share} />)}
  </article>
}

function PutYieldStrip({ put }: { put: WheelPutLot }) {
  const actualClose = put.early_close_return_kind === 'actual' || put.state === 'closed' || put.state === 'rolled'
  const earlyLabel = actualClose ? '实际提前平仓年化' : '当前提前平仓估算年化'
  const earlyNote = actualClose
    ? `真实已实现利润 · 持有 ${put.early_close_days} 天`
    : put.early_close_annualized_return == null
      ? '手动刷新行情后按保守买回价计算'
      : `保守买回价 · 持有 ${put.early_close_days} 天`
  return <div className="put-yield-strip" aria-label={`Sell Put #${put.id} 年化收益`}>
    <div><span>开仓年化收益</span><strong>{formatAnnualized(put.opening_annualized_return)}</strong><small>全部权利金 / 初始担保 · {put.opening_dte} DTE</small></div>
    <div className={put.early_close_annualized_return != null && put.early_close_annualized_return < 0 ? 'negative' : ''}><span>{earlyLabel}</span><strong>{formatAnnualized(put.early_close_annualized_return)}</strong><small>{earlyNote}</small></div>
  </div>
}

function RollLink({ put, direction }: { put: WheelPutLot; direction: 'from' | 'to' }) {
  const roll = direction === 'from' ? put.rolled_from : put.rolled_to
  if (!roll) return null
  const netLabel = roll.net_credit >= 0 ? '净收' : '净付'
  return <section className={`put-roll-link ${direction}`} aria-label={`Sell Put #${put.id} 展期记录`}>
    <RefreshCw size={18} />
    <div>
      <strong>{direction === 'from' ? `第 ${put.roll_count ?? 1} 次展期` : '已展期至新合约'}</strong>
      <span>{roll.from_expiration} ${roll.from_strike.toFixed(2)} Put <b>→</b> {roll.to_expiration} ${roll.to_strike.toFixed(2)} Put</span>
    </div>
    <div><small>展期净收付</small><strong className={roll.net_credit < 0 ? 'loss' : ''}>{netLabel} {formatMoney(Math.abs(roll.net_credit))}</strong></div>
    <div><small>旧腿已实现</small><strong className={roll.previous_realized_profit < 0 ? 'loss' : ''}>{formatMoney(roll.previous_realized_profit)}</strong></div>
  </section>
}

function QuoteLine({ put }: { put: WheelPutLot }) {
  if (!put.quote_source || put.quote_source === 'unavailable') return <div className="quote-line"><span className="quote-source unavailable">等待行情刷新</span><small>尚无可用期权报价</small></div>
  if (put.quote_source === 'public') return <div className="quote-line"><span className="quote-source public">公开报价</span><small>Bid {formatMoney(put.quote_bid ?? 0)} · Ask {formatMoney(put.quote_ask ?? 0)} · Last {formatMoney(put.quote_last ?? 0)}</small></div>
  return <div className="quote-line"><span className="quote-source theoretical">理论估算</span><small>{formatMoney(put.theoretical_low ?? 0)} – {formatMoney(put.theoretical_high ?? 0)} · 以区间上沿判断</small></div>
}

function formatAnnualized(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '等待计算'
  return `${value >= 0 ? '' : '-'}${Math.abs(value * 100).toFixed(2)}%`
}

function ShareLot({ share }: { share: WheelShareLot }) {
  return <section className={`share-ledger ${share.state}`}>
    <header><div><span>接股批次 #{share.id}</span><strong>{share.remaining_quantity} 股 · 成本口径 {formatMoney(share.assignment_strike)}</strong></div></header>
    <div className="share-summary"><span>占用 {formatMoney(share.capital)}</span><span>已覆盖 {share.covered_contracts} 张</span><span>可开 {share.available_call_contracts} 张</span></div>
    <div className="call-register">{share.calls.map((call) => <CallLot key={call.id} call={call} />)}</div>
  </section>
}

function CallLot({ call }: { call: WheelCallLot }) {
  return <div className={`call-row ${call.state}`}>
    <div><span>Covered Call #{call.id}</span><strong>{callStates[call.state]}</strong></div>
    <div><small>行权价</small><b>{formatMoney(call.strike)}</b></div>
    <div><small>权利金</small><b>{formatMoney(call.premium)}</b></div>
    <div><small>数量 / 到期</small><b>{call.quantity} 张 · {call.expiration}</b></div>
    <div><span className={`quote-source ${call.quote_source ?? 'unavailable'}`}>{call.quote_source === 'public' ? '公开报价' : '等待报价'}</span>{call.quote_source === 'public' && <small>Bid {formatMoney(call.quote_bid ?? 0)} / Ask {formatMoney(call.quote_ask ?? 0)}</small>}</div>
  </div>
}

export function putHasLiveExposure(put: WheelPutLot) {
  return (put.state === 'open' && put.open_quantity > 0)
    || put.share_lots.some((share) => share.state === 'held' && share.remaining_quantity > 0)
    || put.share_lots.some((share) => share.calls.some((call) => call.state === 'open'))
}

function matchesStrategy(put: WheelPutLot, strategy: 'tqqq' | 'club') {
  return strategy === 'tqqq' ? put.symbol === 'TQQQ' : put.symbol !== 'TQQQ'
}

function activeWheelRounds(overview: WheelOverview, strategy: 'tqqq' | 'club') {
  return [...overview.rounds].reverse().map((round) => ({
    ...round,
    puts: round.puts.filter((put) => matchesStrategy(put, strategy) && putHasLiveExposure(put)),
  })).filter((round) => round.puts.length > 0)
}

function activeWheelCount(overview: WheelOverview, strategy: 'tqqq' | 'club') {
  return activeWheelRounds(overview, strategy).reduce((count, round) => count + round.puts.length, 0)
}

function historyWheelRounds(overview: WheelOverview, filter: 'all' | 'tqqq' | 'club') {
  return [...overview.rounds].reverse().map((round) => ({
    ...round,
    puts: round.puts.filter((put) => {
      const strategyMatches = filter === 'all' || matchesStrategy(put, filter)
      return strategyMatches && !putHasLiveExposure(put)
    }),
  })).filter((round) => round.puts.length > 0)
}

function formatChange(value: number | null) {
  if (value == null) return '等待行情'
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

function Value({ label, value }: { label: string; value: ReactNode }) { return <div><span>{label}</span><strong>{value}</strong></div> }
function EmptyMarket() { return <p className="empty-copy">点击右上角刷新行情后计算。</p> }
