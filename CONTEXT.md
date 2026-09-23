# WheelDesk Domain Glossary

## Core Allocation

核心仓是长期持有的 BRK.B、VOO、SCHD 股票组合。它承担账户的主要方向性权益暴露，目标占总资产 70%。核心仓的低频轮动观察不等同于期权策略开仓信号。

## Options Pool

期权共享池是 LEAPS、PMCC 与历史 Wheel 持仓共同占用的账户风险预算，目标占总资产 25%。Wheel 与 LEAPS 保留独立的运营记录，但共享池目标不代表可以把全部额度重复用于两种策略。

## Wheel Transition

Wheel 是 Sell Put、行权接股、再卖 Covered Call 的策略闭环。已有 Wheel 仓位属于过渡仓，需要继续记录、结算和管理；在策略迁移期间，新增资金不再以扩大 Wheel 目标为优先。当前 AVGO 的未平仓 Sell Put 明确保留在 Wheel 中，不迁移到 PMCC，也不主动清除或平仓；后续只按 Wheel 规则继续结算和管理。Wheel 在前端并入“其他持仓与过渡仓”页面，只展示已有仓位管理状态，不再生成新的 Wheel 开仓或个股 Wheel 风险信号。

## PMCC

PMCC 是 Long LEAPS Call 加上由该 LEAPS 覆盖的 Short Call。它不是 Sell Put，也不是由 100 股现货覆盖的普通 Covered Call。PMCC 的风险边界取决于 LEAPS 的权利金损失、短 Call 的上行封顶、提前行权、展期和到期管理。

PMCC 的期权池目标是账户总资产的 25%，其中 QQQ/QLD 目标为 10%，万亿俱乐部等个股合计为 15%，单只个股最多占 3%。预算按 Long LEAPS 的借方成本计算；Short Call 权利金作为现金流和收益记录，不重复增加资本占用。

**PMCC 状态**:

`covered` 表示 Short Call 数量不超过 Long LEAPS 的覆盖量；`uncovered` 表示缺少 Long LEAPS 或卖出数量超出覆盖量；`needs_roll` 表示任一腿进入展期窗口；`assignment_risk` 表示标的价格达到 Short Call 行权价；`expired` 表示任一腿已到期。

## Cash Reserve

现金仓是账户的流动性与保证金安全缓冲，目标占总资产 5%。它不应因为期权策略的名义本金或未实现权利金而被视为已经可自由使用。
