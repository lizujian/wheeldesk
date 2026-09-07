export type Bucket = 'core' | 'cash' | 'wheel' | 'leaps' | 'unallocated'

export interface TargetRow {
  fraction: number
  amount: number
  actual: number
  variance: number
}

export interface StrategyCapital {
  assigned: number
  committed: number
  available: number
  cash_occupancy: number
}

export interface CashCapital {
  total: number
  cash_equivalent?: number
  liquid?: number
  occupied: number
  available: number
  margin_shortfall: number
}

export interface CapitalSnapshot {
  core: StrategyCapital
  wheel: StrategyCapital
  leaps: StrategyCapital
  options?: StrategyCapital
  cash: CashCapital
}

export interface PortfolioSummary {
  initialized: boolean
  age?: number
  currency?: string
  total_equity?: number
  net_external_capital?: number
  investment_profit?: number
  other_holdings_value?: number
  balances?: Record<Bucket, number>
  targets?: Partial<Record<Exclude<Bucket, 'unallocated'> | 'options', TargetRow>>
  capital?: CapitalSnapshot
  deployments?: Partial<Record<Exclude<Bucket, 'unallocated'> | 'options', number>>
}

export interface SupportLevel {
  price: number
  kind: 'swing_cluster' | 'ma50' | 'ma200'
  touches: number
  distance_pct: number
}

export interface RiskDecision {
  severity: 'critical' | 'warning' | 'opportunity' | 'info'
  stop_required: boolean
  defensive_cc_required_if_holding: boolean
  message: string
}

export interface TrancheDecision {
  tranche: number
  eligible: boolean
  allocation_fraction: number
  suggested_amount: number
  checks: Record<string, boolean>
}

export interface ClubEntryDecision {
  symbol: string
  name: string
  technical_eligible: boolean
  eligible: boolean
  suggested_slot: number | null
  suggested_amount: number
  over_shared_budget: boolean
  checks: Record<string, boolean>
  current_price: number | null
  previous_close: number
  change_fraction: number | null
  close: number
  ma200: number
  rsi14: number
  market_cap: number | null
  market_cap_as_of: string | null
  market_cap_currency: string | null
  open_slots: number[]
  fifo_candidate_position_id: number | null
  fifo_candidate_slot: number | null
  risk_position_ids: number[]
}

export interface ClubWheelDecision {
  symbol: string
  name: string
  technical_eligible: boolean
  eligible: boolean
  checks: Record<string, boolean>
  current_price: number | null
  previous_close: number
  change_fraction: number | null
  close: number
  ma200: number
  rsi14: number
  preferred_support: SupportLevel | null
  supports: SupportLevel[]
  reference_strike: number | null
  dte_range: [number, number]
  delta_range: [number, number]
  minimum_annualized_return: number
  one_contract_collateral: number | null
  concentration_limit: number
  budget_available: number
  over_concentration: boolean
  over_budget: boolean
  active_cycle: boolean
  next_earnings_date: string | null
  earnings_available: boolean
  earnings_confirmation_required: boolean
  high_risk_put_ids: number[]
}

export interface MarketSnapshot {
  source: 'sample' | 'yahoo' | 'mixed'
  as_of: string
  stale: boolean
  market: {
    qqq: { price: number; ma20: number; ma200: number; rsi14: number; bearish: boolean; drawdown: number }
    tqqq: { price: number }
    brk_b: { price: number }
    voo?: { price: number }
    vix: { price: number }
  }
  wheel: {
    eligible: boolean
    checks: Record<string, boolean>
    dte_range: [number, number]
    delta_range: [number, number]
    reference_strike: number
    preferred_support: SupportLevel | null
    supports: SupportLevel[]
  }
  wheel_club?: {
    decisions: ClubWheelDecision[]
    unavailable: Array<{ symbol: string; name: string; error: string }>
    weekly_limit_days: number
    single_stock_fraction: number
  }
  risk: RiskDecision
  leaps: TrancheDecision[]
  leaps_fifo?: {
    required: boolean
    candidate: { position_id: number; slot: number; opened_on: string } | null
  }
  leaps_technical_ready?: boolean
  leaps_shared_budget?: {
    target: number
    current: number
    available: number
    over: number
  }
  leaps_club?: {
    decisions: ClubEntryDecision[]
    unavailable: Array<{ symbol: string; name: string; error: string }>
    exclusions: string[]
  }
  leaps_session?: {
    available: boolean
    price: number | null
    previous_close: number
    change_fraction: number | null
    quoted_at: string | null
    market_date: string
    session: 'pre' | 'regular' | 'post' | 'sample' | 'unavailable'
    source: string | null
  }
  equities?: Record<string, EquityQuote>
  core?: CoreStrategyDecision
}

export interface EquityQuote {
  price: number | null
  source: string | null
  as_of: string | null
  status: 'updated' | 'stale' | 'unavailable'
  error: string | null
}

export interface CoreAssetDecision {
  symbol: 'BRK.B' | 'VOO'
  current_value: number
  price: number
  rsi14: number
  drawdown: number
  daily_change?: number
  ma200: number
  below_ma200_two_days: boolean
  return_20d: number
  return_126d: number
  code: 'monthly' | 'pullback' | 'correction' | 'deep' | 'cooldown' | 'waiting' | 'at_target' | 'pending_puts' | 'put_preferred'
  actionable: boolean
  fraction: number
  strategy_amount: number
  executable_amount: number
  funding_required: number
  shares: number
  signal_score?: number
  trend_reduced?: boolean
}

export interface CoreStrategyDecision {
  mode: 'accumulating' | 'full'
  total_target: number
  total_value: number
  target_gap: number
  pending_put_collateral?: number
  unplanned_gap?: number
  sell_put?: {
    code: string
    actionable: boolean
    symbol: string | null
    reference_strike: number | null
    collateral: number
    direct_buy_reserve: number
    contracts: number
    dte_range: [number, number]
  }
  full_threshold: number
  ratio_z: number
  route_confirmation_days: number
  rotation_confirmation_days: number
  selected_symbol: 'BRK.B' | 'VOO' | null
  daily_limit_open: boolean
  recommendation: (CoreAssetDecision & { cash_required: number }) | null
  rotation: {
    code: string
    actionable: boolean
    sell_symbol: 'BRK.B' | 'VOO' | null
    buy_symbol: 'BRK.B' | 'VOO' | null
    amount: number
    sell_shares: number
    buy_shares: number
    return_spread?: number
    defensive_half?: boolean
    cooldown_days_remaining?: number
    ratio?: number | null
    ratio_as_of?: string | null
    band?: string | null
    confirmation_days?: number
    current_brk_weight?: number
    projected_brk_weight?: number
    target_brk_weight?: number
    next_brk_weight?: number
    weight_change?: number
    used_weight?: number
    remaining_weight?: number
    executions?: Array<{ id: number; symbol: string; traded_at: string; quantity: number; price: number; proceeds: number; weight_change: number | null }>
  }
  assets: CoreAssetDecision[]
  core_available: number
  cash_available: number
}

export interface OtherHolding {
  id: number
  category: 'cash_equivalent' | 'other'
  symbol: string
  asset_type: 'equity' | 'option'
  direction: 'long' | 'short'
  option_type: 'call' | 'put' | null
  quantity: number
  multiplier: number
  entry_price: number | null
  current_price: number | null
  current_value: number | null
  absolute_value: number | null
  unrealized_profit: number | null
  opened_on: string | null
  expiration: string | null
  strike: number | null
  status: 'open' | 'closed'
  closed_on: string | null
  exit_price: number | null
  realized_profit: number | null
  quote_source: string | null
  quote_as_of: string | null
  quote_status: 'updated' | 'stale' | 'unavailable'
  last_error: string | null
}

export interface OtherHoldingListing {
  records: OtherHolding[]
  total_value: number
  cash_equivalent_value: number
  other_value: number
  unpriced_count: number
}

export interface WheelCycle {
  id?: number
  state: 'waiting_put' | 'put_open' | 'shares_held' | 'call_open' | 'closed'
  opened_on?: string
  closed_on?: string | null
  put_expiration?: string
  put_strike?: number
  put_premium?: number
  put_quantity?: number
  share_quantity?: number
  share_cost_total?: number
  adjusted_share_basis?: number | null
  call_expiration?: string | null
  call_strike?: number | null
  call_premium?: number | null
  call_quantity?: number
  realized_profit?: number | null
}

export interface WheelBudgetStatus {
  budget: number
  target_fraction: number
  funded: number
  funding_gap: number
  funding_excess: number
  unfunded_exposure: number
  exposure: number
  available: number
  over_budget: number
  usage_fraction: number | null
}

export interface WheelCallLot {
  id: number
  share_lot_id: number
  trade_date: string
  expiration: string
  strike: number
  premium: number
  quantity: number
  state: 'open' | 'closed' | 'expired' | 'called_away' | 'voided'
  closed_on: string | null
  close_premium: number | null
  realized_profit: number
  quote_source: 'public' | 'theoretical' | 'unavailable' | null
  quote_bid: number | null
  quote_ask: number | null
  quote_last: number | null
  quote_iv: number | null
  quote_as_of: string | null
  voided_at: string | null
  void_reason: string | null
}

export interface WheelShareLot {
  id: number
  put_lot_id: number
  assigned_on: string
  assignment_strike: number
  original_quantity: number
  remaining_quantity: number
  state: 'held' | 'closed' | 'voided'
  realized_profit: number
  capital: number
  covered_contracts: number
  available_call_contracts: number
  voided_at: string | null
  void_reason: string | null
  calls: WheelCallLot[]
}

export interface WheelPutLot {
  id: number
  round_id: number
  capital_bucket?: 'wheel' | 'core'
  symbol: string
  batch_number: 1 | 2
  trade_date: string
  expiration: string
  strike: number
  premium: number
  quantity: number
  open_quantity: number
  assigned_contracts: number
  entry_tqqq_price: number
  entry_underlying_price?: number
  earnings_confirmed: boolean
  state: 'open' | 'closed' | 'expired' | 'assigned' | 'rolled' | 'voided'
  closed_on: string | null
  close_premium: number | null
  realized_profit: number
  collateral: number
  opening_dte: number
  opening_annualized_return: number | null
  early_close_days: number | null
  early_close_annualized_return: number | null
  early_close_return_kind: 'estimated' | 'actual' | null
  quote_source: 'public' | 'theoretical' | 'unavailable' | null
  quote_bid: number | null
  quote_ask: number | null
  quote_last: number | null
  quote_iv: number | null
  quote_as_of: string | null
  theoretical_low: number | null
  theoretical_base: number | null
  theoretical_high: number | null
  captured_fraction: number | null
  early_close_code: 'regular_profit' | 'expiry_profit' | 'fast_profit' | null
  early_close_message: string | null
  voided_at: string | null
  void_reason: string | null
  roll_count?: number
  rolled_from?: WheelPutRoll | null
  rolled_to?: WheelPutRoll | null
  share_lots: WheelShareLot[]
}

export interface WheelPutRoll {
  from_put_id: number
  to_put_id: number
  rolled_on: string
  from_expiration: string
  from_strike: number
  to_expiration: string
  to_strike: number
  buyback_premium: number | null
  new_premium: number
  quantity: number
  net_credit: number
  previous_realized_profit: number
}

export interface WheelRound {
  id: number
  number: number
  opened_on: string
  closed_on: string | null
  status: 'active' | 'completed' | 'voided'
  realized_profit: number
  voided_at: string | null
  void_reason: string | null
  puts: WheelPutLot[]
}

export interface WheelOverview {
  capital?: {
    assigned: number
    put_collateral: number
    share_capital: number
    committed: number
    strategy_committed?: number
    available: number
    cash_occupancy: number
    cash_available: number
    margin_shortfall: number
  }
  budget: WheelBudgetStatus
  recommendations: { first: number; second: number }
  realized_profit: number
  rounds: WheelRound[]
  core_puts?: WheelPutLot[]
}

export interface RebalancingBucket {
  value: number
  fraction: number
  target_fraction: number
  deviation: number
}

export interface RebalancingSnapshot {
  as_of: string
  schedule: {
    last_rebalanced_on: string | null
    next_review_on: string
    due: boolean
  }
  assigned: {
    total: number
    buckets: Record<Exclude<Bucket, 'unallocated'>, number>
  }
  capital: CapitalSnapshot
  economic: {
    total: number
    buckets: Record<'core' | 'cash' | 'options', RebalancingBucket>
    unrealized: Record<'core' | 'wheel' | 'leaps', number>
  }
  core_price: number
  core_symbol: 'BRK.B' | 'VOO'
  core_decision: {
    code: 'underweight' | 'pause' | 'observe' | 'sell'
    actionable: boolean
    target_after_sale: number
    sell_amount: number
    estimated_shares: number
    symbol: 'BRK.B' | 'VOO'
  }
  recommendations: Array<{
    priority: number
    code: string
    bucket: Exclude<Bucket, 'unallocated'>
    amount: number
    message: string
  }>
}

export type IbkrImportStatus = 'ready' | 'matched' | 'review' | 'unsupported' | 'duplicate'

export interface IbkrImportRow {
  fingerprint: string
  section: string
  row_index: number
  instrument: string
  action: string
  status: IbkrImportStatus
  confidence: 'exact' | 'estimated' | 'low'
  selected: boolean
  can_import: boolean
  message: string
  details: {
    symbol?: string
    asset_type?: 'equity' | 'option'
    option_type?: 'put' | 'call' | null
    quantity?: number
    reported_quantity?: number
    cost_price?: number
    close_price?: number
    opened_on?: string
    expiration?: string | null
    strike?: number | null
    bucket?: Bucket
    tranche?: number | null
    underlying_entry_price?: number | null
    earnings_confirmed?: boolean
    amount?: number
    occurred_on?: string
    note?: string
    report_as_of?: string
    old_expiration?: string
    old_strike?: number
    buyback_premium?: number
    new_premium?: number
    net_credit?: number
  }
  source: Record<string, string>
}

export interface IbkrImportPreview {
  filename: string
  report_as_of?: string | null
  recognized_sections: string[]
  statement_rows: number
  rows: IbkrImportRow[]
  summary: Record<IbkrImportStatus, number> & { selected: number }
}

export interface IbkrAutoImportResult {
  filename: string
  report_as_of?: string | null
  statement_rows: number
  imported: number
  unchanged: number
  needs_attention: number
  results: Array<{
    fingerprint: string
    instrument: string
    action: string
    entity_type: string | null
    entity_id: number | null
  }>
  notices: Array<{
    instrument: string
    status: 'review' | 'unsupported'
    message: string
  }>
}

export interface IbkrImportHistoryRow {
  id: number
  filename: string
  section: string
  row_index: number
  action: string
  entity_type: string | null
  entity_id: number | null
  instrument: string
  created_at: string
}

export interface Position {
  id: number
  rolled_from_position_id?: number | null
  bucket: Bucket
  symbol: string
  asset_type: 'equity' | 'option'
  quantity: number
  multiplier: number
  entry_price: number
  current_price: number
  current_value: number
  unrealized_profit: number | null
  opened_on: string
  expiration: string | null
  strike: number | null
  delta: number | null
  tranche: number | null
  leaps_category?: 'qqq' | 'club' | null
  underlying_entry_price?: number | null
  status: 'open' | 'closed'
  closed_on?: string | null
  total_loss_impact: number | null
  realized_profit?: number | null
  quote_source?: string | null
  quote_bid?: number | null
  quote_ask?: number | null
  quote_last?: number | null
  quote_iv?: number | null
  quote_as_of?: string | null
  peak_bid?: number | null
  exit_decision?: LeapsExitDecision | null
}

export interface LeapsExitDecision {
  code: 'force_exit' | 'take_profit' | 'hold' | 'quote_unavailable'
  actionable: boolean
  days_held: number
  dte: number | null
  return_fraction: number | null
  target_return: number | null
}

export interface Signal {
  id: number
  code: string
  title: string
  message: string
  severity: 'critical' | 'warning' | 'opportunity' | 'info'
  market_date: string
  acknowledged: boolean
}

export interface LedgerEvent {
  id: number
  event_type: string
  bucket: Bucket
  amount: number
  occurred_on: string
  details: Record<string, unknown>
}

export interface DistributionRecommendation {
  allocations: Record<Exclude<Bucket, 'unallocated'>, number>
  unallocated: number
}

export interface ProfitLedgerSummary {
  wheel_realized: number
  leaps_realized: number
  other_realized: number
  net_realized: number
  allocated: number
  available: number
}

export interface ProfitLedgerEntry {
  id: string
  entry_type: 'realized' | 'allocation'
  source: 'wheel' | 'leaps' | 'other' | 'allocation'
  occurred_on: string
  amount: number
  note: string
  automatic: boolean
  deletable: boolean
  allocations: Partial<Record<Exclude<Bucket, 'unallocated'>, number>>
}

export interface ProfitLedgerSnapshot {
  summary: ProfitLedgerSummary
  entries: ProfitLedgerEntry[]
}
