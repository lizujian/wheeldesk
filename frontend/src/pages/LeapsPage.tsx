import { useState } from 'react'
import {
  Activity,
  ArrowDownRight,
  Banknote,
  Building2,
  CalendarClock,
  Check,
  CircleDashed,
  Gauge,
  Landmark,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  WalletCards,
} from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { ClubEntryDecision, MarketSnapshot, OtherHolding, PortfolioSummary, Position, TrancheDecision } from '../lib/types'
import './LeapsPage.css'

const slotFractions = [.2, .2, .2, .2, .2]

export function LeapsPage({ market, positions, portfolio, leapsCalls = [] }: {
  market: MarketSnapshot | null
  positions: Position[]
  portfolio: PortfolioSummary
  leapsCalls?: OtherHolding[]
}) {
  const [strategy, setStrategy] = useState<'qqq' | 'club'>('qqq')
  const leapsHistory = positions.filter((position) => position.bucket === 'leaps')
  const leaps = leapsHistory.filter((position) => position.status === 'open')
  const closedById = new Map(leapsHistory
    .filter((position) => position.status === 'closed')
    .map((position) => [position.id, position]))
  const qqqLeaps = leaps.filter((position) => !isClubPosition(position))
  const clubLeaps = leaps.filter(isClubPosition)
  const qqqLeapsCalls = leapsCalls.filter((record) => record.symbol === 'QQQ' || record.symbol === 'QLD')
  const clubLeapsCalls = leapsCalls.filter((record) => record.symbol !== 'QQQ')
  const target = portfolio.targets?.options?.amount ?? ((portfolio.targets?.wheel?.amount ?? 0) + (portfolio.targets?.leaps?.amount ?? 0))
  const targetFraction = portfolio.targets?.options?.fraction ?? ((portfolio.targets?.wheel?.fraction ?? 0) + (portfolio.targets?.leaps?.fraction ?? 0))
  const slotTarget = (portfolio.targets?.leaps?.amount ?? 0) * .2
  const funded = (portfolio.balances?.wheel ?? 0) + (portfolio.balances?.leaps ?? 0)
  const invested = leaps.reduce((total, position) => total + position.current_value, 0)
  const capital = portfolio.capital?.options ?? {
    assigned: funded,
    committed: leaps.reduce((total, position) => total + position.entry_price * position.quantity * position.multiplier, 0),
    available: 0,
    cash_occupancy: 0,
  }
  const cashMargin = portfolio.capital?.cash.margin_shortfall ?? 0
  const overTarget = Math.max(capital.committed - target, 0)
  const unfundedExposure = capital.cash_occupancy
  const decisions = market?.leaps ?? defaultDecisions()
  const fifo = market?.leaps_fifo
  const qqqOccupiedSlots = new Set(qqqLeaps.map((position) => position.tranche)).size
  const clubSymbols = new Set(clubLeaps.map((position) => position.symbol)).size

  const selectStrategy = (next: 'qqq' | 'club') => {
    setStrategy(next)
  }

  return <div className="page-stack leaps-console">
    <div className="page-heading">
      <div><p className="eyebrow">QQQ / QLD + TRILLION CLUB</p><h1>LEAPS 双策略台</h1><span>共享预算 · 独立信号与持仓管理</span></div>
      {market && <span className={`source-badge ${market.source}`}>{market.source === 'sample' ? '模拟数据' : '公开行情'}</span>}
    </div>

    <section className={`leaps-budget-band ${overTarget || unfundedExposure ? 'danger' : ''}`} aria-label="LEAPS 预算">
      <BudgetMetric icon={WalletCards} label="期权共享本金" value={capital.assigned} note={`车轮与 LEAPS 共同目标 ${(targetFraction * 100).toFixed(1)}% · ${formatMoney(target)}`} />
      <BudgetMetric icon={Landmark} label="共享成本占用" value={capital.committed} note={`其中 LEAPS 当前估值 ${formatMoney(invested)}`} danger={overTarget > 0} />
      <BudgetMetric icon={Gauge} label="共享可用本金" value={capital.available} note="车轮与 LEAPS 均可使用" />
      <BudgetMetric icon={Banknote} label="临时占用现金" value={capital.cash_occupancy} note={capital.cash_occupancy > 0 ? '合计成本超过期权共享本金' : '未占用现金'} danger={capital.cash_occupancy > 0} />
      <BudgetMetric icon={ShieldCheck} label="Margin 缺口" value={cashMargin} note={cashMargin > 0 ? '账户现金不足以覆盖占用' : '现金覆盖正常'} danger={cashMargin > 0} />
    </section>

    {(overTarget > 0 || unfundedExposure > 0 || cashMargin > 0) && <div className="leaps-budget-alert" role="alert">
      <ShieldAlert size={17} />
      <span>{overTarget > 0 && <>车轮与 LEAPS 合计成本超过共享目标 {formatMoney(overTarget)}。</>}{unfundedExposure > 0 && <>期权共享池临时占用现金 {formatMoney(unfundedExposure)}。</>}{cashMargin > 0 && <>Margin 缺口 {formatMoney(cashMargin)}。</>}</span>
    </div>}

    <nav className="leaps-strategy-tabs" aria-label="LEAPS 子策略">
      <button className={strategy === 'qqq' ? 'active' : ''} aria-pressed={strategy === 'qqq'} onClick={() => selectStrategy('qqq')}>
        <Landmark size={17} />
        <span><strong>QQQ / QLD 五槽位</strong><small>每日限频 · 已占 {qqqOccupiedSlots} / 5 槽</small></span>
      </button>
      <button className={strategy === 'club' ? 'active' : ''} aria-pressed={strategy === 'club'} onClick={() => selectStrategy('club')}>
        <Building2 size={17} />
        <span><strong>万亿俱乐部 Long Call</strong><small>每周限频 · {clubLeaps.length} 笔持仓 / {clubSymbols} 只标的</small></span>
      </button>
    </nav>

    {strategy === 'qqq' ? <>
      <EntrySignalBand market={market} decisions={decisions} />

      {fifo?.required && fifo.candidate && <div className="leaps-fifo-alert" role="alert">
        <RefreshCw size={17} />
        <div><strong>FIFO 换仓候选：槽位 {fifo.candidate.slot}</strong><span>最早持仓 {fifo.candidate.opened_on}。如在券商完成换仓，下一份 IBKR 报表会同步槽位记录。</span></div>
      </div>}

      <section className="leaps-policy-strip" aria-label="LEAPS 合约规则">
        <div><span>单槽目标</span><strong>总资产 5% · 最多 5 槽</strong></div>
        <div><span>QQQ Call 选约</span><strong>建议 330–400 DTE · Delta 约 0.60</strong></div>
        <div><span>平替资产</span><strong>QLD 正股 · 独立止盈阶梯</strong></div>
        <div className="guardrail"><ShieldCheck size={17} /><span>禁止 TQQQ LEAPS</span></div>
      </section>

      <LeapsHoldingsRegister
        positions={qqqLeaps}
        rollSources={closedById}
        callWheels={qqqLeapsCalls}
        marketDate={market?.as_of}
        title="QQQ / QLD 当前持仓"
        eyebrow="LIVE REGISTER"
        fifoPositionId={fifo?.required ? fifo.candidate?.position_id : null}
        emptyMessage="尚无 QQQ Call 或 QLD 持仓"
      />

      <LeapsCapacityBand
        decisions={decisions}
        positions={qqqLeaps}
        slotTarget={slotTarget}
        fifoSlot={fifo?.required ? fifo.candidate?.slot : null}
      />
    </> : <ClubConsole market={market} positions={clubLeaps} rollSources={closedById} callWheels={clubLeapsCalls} sharedTarget={target} slotTarget={slotTarget} />}
  </div>
}

function EntrySignalBand({ market, decisions }: { market: MarketSnapshot | null; decisions: TrancheDecision[] }) {
  const session = market?.leaps_session
  const commonChecks = decisions[0]?.checks ?? {}
  const formalSignal = Boolean(market?.leaps_technical_ready) || decisions.some((decision) => decision.eligible) || Boolean(market?.leaps_fifo?.required)
  const budgetFull = (market?.leaps_shared_budget?.available ?? 1) <= 0
  const sessionLabel = session?.session === 'pre' ? '盘前' : session?.session === 'regular' ? '盘中' : session?.session === 'post' ? '盘后' : '不可用'
  return <section className={`leaps-signal-band ${formalSignal ? 'active' : ''}`} aria-label="LEAPS 入场信号">
    <div className="leaps-signal-verdict">
      <Activity size={20} />
      <div><span>QQQ LEAPS 入场判断</span><strong>{formalSignal ? budgetFull ? '技术条件满足，共享额度已满' : '条件满足，可评估 1 个槽位' : market ? '条件未完全满足' : '等待手动刷新行情'}</strong><small>{budgetFull && formalSignal ? '保留信号，请自行决定 FIFO' : '同一交易日最多执行 1 次新开仓或 FIFO 替换'}</small></div>
    </div>
    <SignalMetric label="完成日线" primary={market ? `完成收盘 ${formatMoney(market.market.qqq.price)}` : '等待行情'} secondary={market ? `SMA200 ${formatMoney(market.market.qqq.ma200)}` : '使用已完成交易日'} pass={commonChecks.above_ma200} />
    <SignalMetric label="动能过滤" primary={market ? `RSI14 ${market.market.qqq.rsi14.toFixed(1)}` : 'RSI14 —'} secondary="要求 RSI14 < 45" pass={commonChecks.rsi_below_45} />
    <SignalMetric label={`${sessionLabel}行情`} primary={session?.price != null ? `当前 ${formatMoney(session.price)}` : '当前价不可用'} secondary={session?.change_fraction != null ? formatPercent(session.change_fraction) : '跌幅不可计算'} pass={commonChecks.daily_drop && commonChecks.live_quote} />
    <SignalMetric label="当日频率" primary={commonChecks.daily_limit === false ? '同一交易日已执行' : '同一交易日尚未执行'} secondary={session?.market_date ?? market?.as_of ?? '等待行情日期'} pass={commonChecks.daily_limit} />
  </section>
}

function SignalMetric({ label, primary, secondary, pass = false }: { label: string; primary: string; secondary: string; pass?: boolean }) {
  return <div className={`leaps-signal-metric ${pass ? 'pass' : ''}`}><span>{label}</span><strong>{primary}</strong><small>{pass ? <Check size={12} /> : <ArrowDownRight size={12} />}{secondary}</small></div>
}

function ClubConsole({ market, positions, rollSources, callWheels, sharedTarget, slotTarget }: {
  market: MarketSnapshot | null
  positions: Position[]
  rollSources: Map<number, Position>
  callWheels: OtherHolding[]
  sharedTarget: number
  slotTarget: number
}) {
  const unavailable = market?.leaps_club?.unavailable ?? []
  const decisions = clubRows(market?.leaps_club?.decisions ?? [], positions, unavailable)
  const shared = market?.leaps_shared_budget
  const weeklyOpen = decisions.length === 0 || decisions.every((decision) => decision.checks.weekly_limit !== false)
  return <section className="club-console" aria-label="万亿俱乐部 LEAPS">
    <div className="club-rule-band">
      <div><Building2 size={17} /><span>资格门槛</span><strong>公开市值 ≥ $1T</strong><small>至少 252 个完成交易日</small></div>
      <div><Activity size={17} /><span>入场组合</span><strong>RSI14 &lt; 45 · 当日跌超 5%</strong><small>QQQ 与个股均位于 SMA200 上方</small></div>
      <div><CalendarClock size={17} /><span>本周频率</span><strong>{weeklyOpen ? '尚未确认开仓' : '本周已经执行'}</strong><small>按美股自然周统一限频</small></div>
      <div className={shared && shared.available <= 0 ? 'danger' : ''}><WalletCards size={17} /><span>共享可用额度</span><strong>{formatMoney(shared?.available ?? Math.max(sharedTarget - positions.reduce((sum, position) => sum + position.current_value, 0), 0))}</strong><small>{shared && shared.over > 0 ? `已超目标 ${formatMoney(shared.over)}` : '与车轮共用完整期权额度'}</small></div>
    </div>

    <LeapsHoldingsRegister
      positions={positions}
      rollSources={rollSources}
      callWheels={callWheels}
      marketDate={market?.as_of}
      title="万亿俱乐部当前持仓"
      eyebrow="CLUB LIVE REGISTER"
      emptyMessage="尚无万亿俱乐部 Long Call 持仓"
    />

    <div className="club-universe-note">
      <span>股票池</span><strong>GOOG 仅 Class C · 伯克希尔仅 BRK-B</strong><small>明确排除 MU、ORCL、WMT、SK 海力士和 SpaceX；资格仅影响新开仓，不强制处理已有持仓。</small>
    </div>

    <div className="club-table">
      <div className="club-table-head" aria-hidden="true"><span>标的 / 资格</span><span>行情触发</span><span>趋势过滤</span><span>独立槽位</span></div>
      {decisions.length === 0 && <div className="club-empty"><CircleDashed size={18} /><div><strong>{market ? '暂时没有可评估的公开候选' : '等待手动刷新行情'}</strong><small>单只股票的数据失败不会影响其他策略。</small></div></div>}
      {decisions.map((decision) => {
        const symbolPositions = positions.filter((position) => position.symbol === decision.symbol)
        const openSlots = new Set(symbolPositions.map((position) => position.tranche))
        const firstEmpty = [1, 2].find((slot) => !openSlots.has(slot)) ?? null
        const entrySlot = decision.suggested_slot ?? firstEmpty
        const fifoPosition = symbolPositions.find((position) => position.id === decision.fifo_candidate_position_id)
        const highRisk = decision.risk_position_ids.length > 0
        return <article className={`club-row ${decision.technical_eligible ? 'eligible' : ''} ${decision.over_shared_budget ? 'over-budget' : ''} ${highRisk ? 'high-risk' : ''}`} aria-label={`${decision.symbol} 万亿俱乐部`} key={decision.symbol}>
          <div className="club-identity"><div className="club-symbol">{decision.symbol}</div><div><strong>{decision.name}</strong><span>{decision.market_cap == null ? '市值等待公开数据' : `${formatTrillion(decision.market_cap)} · ${decision.market_cap_as_of ?? '日期未知'}`}</span><em>{decision.checks.market_cap ? '万亿资格有效' : '当前不可开仓'}</em></div></div>
          <div className="club-quote"><span>当前 / 日变动</span><strong>{decision.current_price == null ? '—' : formatMoney(decision.current_price)}</strong><em className={(decision.change_fraction ?? 0) < 0 ? 'loss' : 'gain'}>{decision.change_fraction == null ? '等待当前价' : formatPercent(decision.change_fraction)}</em><small>基准收盘 {formatMoney(decision.previous_close)}</small></div>
          <div className="club-checks"><span className={decision.checks.stock_above_ma200 ? 'pass' : ''}>个股 &gt; SMA200</span><span className={decision.checks.qqq_above_ma200 ? 'pass' : ''}>QQQ &gt; SMA200</span><span className={decision.checks.rsi_below_45 ? 'pass' : ''}>RSI {decision.rsi14.toFixed(1)}</span><span className={decision.checks.daily_drop ? 'pass' : ''}>跌幅 &gt; 5%</span>{symbolPositions.length === 1 && <span className={decision.checks.second_entry ? 'pass' : ''}>第二槽加严</span>}</div>
          <div className="club-slots">
            {[1, 2].map((slot) => {
              const position = symbolPositions.find((item) => item.tranche === slot)
              return <div className={`club-slot ${position ? 'occupied' : ''}`} key={slot}><b>{slot}</b>{position ? <><strong>{position.quantity} 张 · {formatMoney(position.current_value)}</strong><small>{position.opened_on} · {exitLabel(position)}</small></> : <><strong>空槽位</strong><small>{slot === 2 ? '第二槽需 RSI < 40' : `参考目标 ${formatMoney(slotTarget)}`}</small></>}</div>
            })}
            {fifoPosition && <small className="club-fifo">FIFO 候选：槽位 {fifoPosition.tranche} · {fifoPosition.opened_on}</small>}
          </div>
          {decision.technical_eligible && (decision.over_shared_budget || entrySlot == null) && <div className="club-row-alert" role="alert"><ShieldAlert size={15} /><span>{entrySlot == null ? '该股票两个槽位已满，请先手工卖出 FIFO 候选。' : '技术条件满足，但期权共享额度已满；请自行决定是否 FIFO。'}</span></div>}
          {highRisk && <div className="club-row-alert critical" role="alert"><ShieldAlert size={15} /><span>连续两个完成交易日低于个股 SMA200，且相关 Call 浮亏达到 35%；请优先评估手工平仓。</span></div>}
        </article>
      })}
    </div>
    {unavailable.length > 0 && <details className="club-unavailable"><summary>{unavailable.length} 个候选本次公开数据不完整</summary><div>{unavailable.map((item) => <span key={item.symbol}><b>{item.symbol}</b>{item.error}</span>)}</div></details>}
  </section>
}

function LeapsHoldingsRegister({ positions, rollSources, callWheels, marketDate, title, eyebrow, fifoPositionId, emptyMessage }: {
  positions: Position[]
  rollSources: Map<number, Position>
  callWheels: OtherHolding[]
  marketDate?: string
  title: string
  eyebrow: string
  fifoPositionId?: number | null
  emptyMessage: string
}) {
  const sorted = [...positions].sort((left, right) => (left.tranche ?? 99) - (right.tranche ?? 99) || left.opened_on.localeCompare(right.opened_on))
  const actionable = positions.filter((position) => position.exit_decision?.actionable).length
  return <section className="leaps-holdings-register" aria-label={title}>
    <header>
      <div className="section-title"><div><p>{eyebrow}</p><h2>{title}</h2></div><span>{positions.length} 笔持仓{actionable ? ` · ${actionable} 笔卖出信号` : ''}</span></div>
    </header>
    {sorted.length
      ? <div className="leaps-lot-list">{sorted.map((position) => <LeapsPositionCard position={position} rolledFrom={position.rolled_from_position_id ? rollSources.get(position.rolled_from_position_id) : undefined} marketDate={marketDate} fifoCandidate={position.id === fifoPositionId} key={position.id} />)}</div>
      : <div className="leaps-register-empty"><CircleDashed size={22} /><strong>{emptyMessage}</strong><span>下一次成交由 IBKR 报表自动同步</span></div>}
    <LeapsCallWheelRegister calls={callWheels} />
  </section>
}

function LeapsCallWheelRegister({ calls }: { calls: OtherHolding[] }) {
  const active = calls.filter((call) => call.status === 'open')
  const history = calls.filter((call) => call.status !== 'open')
  if (!calls.length) return null
  return <section className="leaps-call-wheel-register" aria-label="LEAPS Sell Call 轮动">
    <header><div><p>CALL WHEEL</p><h3>LEAPS Sell Call 轮动</h3></div><span>{active.length} 笔活动{history.length ? ` · ${history.length} 笔历史` : ''}</span></header>
    {active.map((call) => <LeapsCallWheelCard call={call} key={call.id} />)}
    {history.length > 0 && <details><summary>查看已平仓 Sell Call（{history.length} 笔）</summary>{history.map((call) => <LeapsCallWheelCard call={call} key={call.id} />)}</details>}
  </section>
}

function LeapsCallWheelCard({ call }: { call: OtherHolding }) {
  const open = call.status === 'open'
  const profit = open ? call.unrealized_profit : call.realized_profit
  const value = call.current_value == null ? null : Math.abs(call.current_value)
  return <article className={`leaps-call-wheel-card ${profit != null && profit < 0 ? 'loss' : ''}`} aria-label={`${call.symbol} LEAPS Sell Call ${call.id}`}>
    <div className="leaps-call-wheel-title"><b>{call.symbol}</b><strong>${call.strike ?? '—'} Call</strong><span>{open ? '持仓中' : `已${call.status === 'closed' ? '平仓' : '结束'}`}</span></div>
    <div><small>合约</small><strong>{call.quantity} 张</strong></div>
    <div><small>收取权利金 / 股</small><strong>{formatMoney(call.entry_price ?? 0)}</strong></div>
    <div><small>{open ? '当前买回价' : '退出价格'}</small><strong>{formatMoney((open ? call.current_price : call.exit_price) ?? 0)}</strong></div>
    <div><small>{open ? '当前负债估值' : '已实现盈亏'}</small><strong>{open ? value == null ? '等待报价' : formatMoney(value) : formatMoney(profit ?? 0)}</strong></div>
    <div><small>到期日</small><strong>{call.expiration ?? '—'}</strong></div>
    {call.linked_position_id && <small className="leaps-call-wheel-link">关联 Long Call #{call.linked_position_id}</small>}
  </article>
}

function LeapsPositionCard({ position, rolledFrom, marketDate, fifoCandidate }: { position: Position; rolledFrom?: Position; marketDate?: string; fifoCandidate: boolean }) {
  const cost = position.entry_price * position.quantity * position.multiplier
  const returnFraction = position.exit_decision?.return_fraction
    ?? (position.unrealized_profit == null || cost <= 0 ? null : position.unrealized_profit / cost)
  const actionable = Boolean(position.exit_decision?.actionable)
  const status = fifoCandidate ? 'FIFO 待轮动' : actionable ? '卖出信号' : '持仓中'
  const isEquity = position.asset_type === 'equity'
  const quote = isEquity ? position.current_price : position.quote_bid ?? position.current_price
  const heldDays = position.exit_decision?.days_held ?? daysBetween(position.opened_on, marketDate)
  const dte = position.exit_decision?.dte ?? daysUntil(position.expiration, marketDate)
  return <article className={`leaps-lot ${actionable ? 'exit-ready' : ''} ${fifoCandidate ? 'fifo-candidate' : ''}`} aria-label={`LEAPS 持仓 ${position.id}`}>
    <header>
      <div><span>槽位 {position.tranche ?? '—'} · {isEquity ? 'QLD 平替仓' : isClubPosition(position) ? '万亿俱乐部' : 'QQQ LEAPS'}</span><h3><b className="lot-symbol">{position.symbol}</b>{isEquity ? '正股' : `$${position.strike} Call`} #{position.id}</h3></div>
      <strong className={`state-badge ${fifoCandidate ? 'fifo' : actionable ? 'actionable' : 'open'}`}>{status}</strong>
    </header>

    <div className="leaps-lot-values">
      <LotMetric label={isEquity ? '持股数量' : '合约数量'} value={`${position.quantity} ${isEquity ? '股' : '张'}`} />
      <LotMetric label={isEquity ? '成本 / 股' : '权利金 / 股'} value={formatMoney(position.entry_price)} />
      <LotMetric label={isEquity ? '当前价格' : position.quote_bid == null ? '当前估值' : '当前 Bid'} value={quote == null ? '等待报价' : formatMoney(quote)} />
      <LotMetric label="当前市值" value={formatMoney(position.current_value)} />
      <LotMetric label="当前收益" value={returnFraction == null ? '等待报价' : formatPercent(returnFraction)} tone={returnFraction != null && returnFraction < 0 ? 'loss' : 'gain'} />
      <LotMetric label={isEquity ? '持有时间' : '到期 / DTE'} value={isEquity ? `${heldDays} 天` : `${position.expiration ?? '—'} · ${dte} DTE`} />
    </div>

    {rolledFrom
      ? <LeapsRollSummary position={position} rolledFrom={rolledFrom} />
      : position.rolled_from_position_id && <div className="leaps-roll-link"><RefreshCw size={16} /><div><span>展期关系</span><strong>由持仓 #{position.rolled_from_position_id} 展期至当前合约</strong></div></div>}

    <div className={`leaps-exit-monitor ${actionable ? 'actionable' : ''}`}>
      <TrendingUp size={17} />
      <div><span>{actionable ? '退出动作' : '退出监控'}</span><strong>{exitLabel(position)}</strong><small>{returnFraction == null ? '收益率等待报价' : `当前收益 ${formatPercent(returnFraction)}`} · 已持有 {heldDays} 天</small></div>
    </div>
  </article>
}

function LeapsRollSummary({ position, rolledFrom }: { position: Position; rolledFrom: Position }) {
  const contractQuantity = position.quantity
  const netDebit = (position.entry_price - rolledFrom.current_price) * contractQuantity * position.multiplier
  const realized = rolledFrom.realized_profit ?? 0
  const netLabel = netDebit >= 0 ? '净支出' : '净收入'
  return <section className="leaps-roll-summary" aria-label={`${position.symbol} 展期记录 ${rolledFrom.id} 到 ${position.id}`}>
    <div className="leaps-roll-heading">
      <RefreshCw size={16} />
      <div><span>展期记录 · {rolledFrom.closed_on ?? position.opened_on}</span><strong>旧合约已平仓，已实现盈亏保留在本次轮动中</strong></div>
    </div>
    <div className="leaps-roll-metrics">
      <div><span>展期前合约</span><strong>{rolledFrom.expiration ?? '—'} ${rolledFrom.strike ?? '—'} Call</strong><small>持仓 #{rolledFrom.id} → #{position.id}</small></div>
      <div><span>旧腿平仓</span><strong>平仓 {formatMoney(rolledFrom.current_price)}</strong><small>原权利金 {formatMoney(rolledFrom.entry_price)}</small></div>
      <div><span>旧腿损益</span><strong className={realized < 0 ? 'negative' : 'positive'}>已实现 {formatMoney(realized)}</strong><small>已计入 LEAPS 已实现流水</small></div>
      <div><span>展期资金</span><strong className={netDebit < 0 ? 'positive' : ''}>{netLabel} {formatMoney(Math.abs(netDebit))}</strong><small>新权利金 {formatMoney(position.entry_price)}</small></div>
    </div>
  </section>
}

function LotMetric({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return <div><span>{label}</span><strong className={tone}>{value}</strong></div>
}

function LeapsCapacityBand({ decisions, positions, slotTarget, fifoSlot }: {
  decisions: TrancheDecision[]
  positions: Position[]
  slotTarget: number
  fifoSlot?: number | null
}) {
  return <section className="leaps-capacity-band" aria-label="LEAPS 槽位容量">
    <header><div><p>CAPACITY MAP</p><h2>五槽位容量</h2></div><span>{new Set(positions.map((position) => position.tranche)).size} / 5 已占用</span></header>
    <div className="leaps-capacity-columns" aria-hidden="true"><span>编号</span><span>槽位 / 目标金额</span><span>当前状态</span><span>下一步提示</span></div>
    <div className="leaps-capacity-list">{decisions.map((decision) => {
      const slotPositions = positions.filter((position) => position.tranche === decision.tranche)
      const fifoCandidate = fifoSlot === decision.tranche
      const entryEligible = decision.eligible && slotPositions.length === 0
      return <article className={`${slotPositions.length ? 'occupied' : ''} ${entryEligible ? 'eligible' : ''} ${fifoCandidate ? 'fifo' : ''}`} aria-label={`LEAPS 容量槽位 ${decision.tranche}`} key={decision.tranche}>
        <b>{String(decision.tranche).padStart(2, '0')}</b>
        <div><span>槽位 {decision.tranche}</span><strong>{formatMoney(slotTarget)}</strong></div>
        <div><span>当前状态</span><strong>{slotPositions.length ? `${slotPositions.length} 笔持仓` : entryEligible ? '当前买入信号' : '空闲'}</strong></div>
        <div><span>{fifoCandidate ? '轮动提示' : '下一步'}</span><small>{fifoCandidate ? 'FIFO 待轮动' : entryEligible ? `建议开仓 ${formatMoney(decision.suggested_amount)}` : decision.checks.daily_limit === false ? '本交易日已执行，等待下一交易日' : '等待下一次入场信号'}</small></div>
      </article>
    })}</div>
  </section>
}

function BudgetMetric({ icon: Icon, label, value, note, danger = false }: { icon: typeof WalletCards; label: string; value: number; note: string; danger?: boolean }) {
  return <div className={danger ? 'danger' : ''}><Icon size={18} /><span>{label}</span><strong>{formatMoney(value)}</strong><small>{note}</small></div>
}

function defaultDecisions(): TrancheDecision[] {
  return slotFractions.map((fraction, index) => ({ tranche: index + 1, eligible: false, allocation_fraction: fraction, suggested_amount: 0, checks: {} }))
}

function clubRows(decisions: ClubEntryDecision[], positions: Position[], unavailable: Array<{ symbol: string; name: string }> = []) {
  const bySymbol = new Map(decisions.map((decision) => [decision.symbol, decision]))
  const missing = [
    ...unavailable,
    ...positions.map((position) => ({ symbol: position.symbol, name: position.symbol })),
  ]
  for (const item of missing) {
    if (bySymbol.has(item.symbol)) continue
    const position = positions.find((candidate) => candidate.symbol === item.symbol)
    bySymbol.set(item.symbol, {
      symbol: item.symbol,
      name: item.name,
      technical_eligible: false,
      eligible: false,
      suggested_slot: null,
      suggested_amount: 0,
      over_shared_budget: false,
      checks: {},
      current_price: null,
      previous_close: 0,
      change_fraction: null,
      close: 0,
      ma200: 0,
      rsi14: 0,
      market_cap: null,
      market_cap_as_of: null,
      market_cap_currency: null,
      open_slots: [],
      fifo_candidate_position_id: null,
      fifo_candidate_slot: null,
      risk_position_ids: [],
    })
  }
  return [...bySymbol.values()].sort((left, right) => {
    if (left.change_fraction == null && right.change_fraction != null) return 1
    if (left.change_fraction != null && right.change_fraction == null) return -1
    return (left.change_fraction ?? 0) - (right.change_fraction ?? 0)
      || left.symbol.localeCompare(right.symbol)
  })
}

function isClubPosition(position: Position) {
  if (position.leaps_category) return position.leaps_category === 'club'
  return position.bucket === 'leaps' && position.symbol !== 'QQQ' && position.symbol !== 'QLD'
}

function exitLabel(position: Position) {
  const decision = position.exit_decision
  if (!decision) return '等待刷新'
  if (decision.code === 'force_exit') return '持仓超过 270 天，强制平仓'
  if (decision.code === 'take_profit') return `达到 ${((decision.target_return ?? 0) * 100).toFixed(0)}% 止盈线`
  if (decision.code === 'quote_unavailable') return '报价不可用，仅按持仓天数监控'
  return `继续持有 · 目标 ${((decision.target_return ?? 0) * 100).toFixed(0)}%`
}

function daysUntil(value: string | null, asOf?: string) {
  if (!value) return '—'
  return Math.max(0, Math.ceil((new Date(value).getTime() - new Date(asOf ?? today()).getTime()) / 86400000))
}

function daysBetween(value: string, asOf?: string) {
  return Math.max(0, Math.floor((new Date(asOf ?? today()).getTime() - new Date(value).getTime()) / 86400000))
}

function formatPercent(value: number) { return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%` }
function formatTrillion(value: number) { return `$${(value / 1_000_000_000_000).toFixed(2)}T` }
function today() { return new Date().toISOString().slice(0, 10) }
