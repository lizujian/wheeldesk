import { expect, test, type Page } from '@playwright/test'

const syntheticStatement = `Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 1, 2026 - August 28, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,BRK B,,10,1,500,5000,510,5100,100,,,,
Open Positions,Data,Summary,Stocks,USD,BOXX,,50,1,100,5000,100.1,5005,5,,,,
Open Positions,Data,Summary,Stocks,USD,IBM,,5,1,200,1000,210,1050,50,,,,
Open Positions,Data,Summary,Equity and Index Options,USD,QQQ  270618C00400000,QQQ,1,100,100,10000,105,10500,500,2027-06-18,400,C,
Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount
Deposits & Withdrawals,Data,USD,2026-08-12,Synthetic test deposit,25000
`

test.beforeEach(async ({ request }) => {
  await request.post('/api/system/reset', { data: { confirmation: 'RESET' } })
})

async function initialize(page: Page) {
  await page.goto('/')
  await expect(page.locator('.page-loading')).toBeHidden()
  await page.getByLabel('年龄').fill('30')
  await page.getByLabel('初始总金额').fill('100000')
  await expect(page.getByText('核心仓 · 70%')).toBeVisible()
  await expect(page.getByText('现金储备 · 5%')).toBeVisible()
  await expect(page.getByText('期权策略共享池 · 25%')).toBeVisible()
  await page.getByRole('button', { name: '确认并建立账本' }).click()
  await expect(page.getByRole('heading', { name: '资产总览' })).toBeVisible()
}

test('initializes the local read-only strategy console and protects reset', async ({ page }) => {
  await initialize(page)

  await page.getByRole('link', { name: '核心仓' }).first().click()
  await expect(page.getByRole('heading', { name: '核心仓相对定投' })).toBeVisible()
  await expect(page.getByText('IBKR 报表中暂无 BRK.B 或 VOO 持仓')).toBeVisible()
  await expect(page.getByRole('form')).toHaveCount(0)

  await page.getByRole('link', { name: '车轮' }).first().click()
  await expect(page.getByRole('heading', { name: '车轮策略操作台' })).toBeVisible()
  await expect(page.getByRole('form')).toHaveCount(0)

  await page.getByRole('link', { name: 'LEAPS' }).first().click()
  await expect(page.getByRole('heading', { name: 'LEAPS 双策略台' })).toBeVisible()
  await expect(page.getByRole('form')).toHaveCount(0)

  await page.getByRole('link', { name: '设置' }).first().click()
  await page.getByRole('button', { name: '重置全部数据' }).click()
  await expect(page.getByRole('button', { name: '永久清空数据' })).toBeDisabled()
  await page.getByLabel('输入 RESET 继续').fill('RESET')
  await page.getByRole('button', { name: '永久清空数据' }).click()
  await expect(page.getByRole('heading', { name: '建立账户基线' })).toBeVisible()
})

test('imports a synthetic IBKR statement and deduplicates a repeated file', async ({ page }) => {
  await initialize(page)
  await page.getByRole('link', { name: '导入' }).first().click()
  await expect(page.getByRole('heading', { name: 'IBKR 报表同步' })).toBeVisible()

  const input = page.getByLabel('选择 IBKR CSV')
  const file = {
    name: 'synthetic-activity.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(syntheticStatement),
  }
  await input.setInputFiles(file)
  await expect(page.getByText('已同步 5 条新增记录')).toBeVisible()
  await expect(page.getByRole('heading', { name: '本次写入' })).toBeVisible()
  await expect(page.getByText('BRK.B')).toBeVisible()
  await expect(page.getByText('QQQ 2027-06-18 $400 Call')).toBeVisible()

  await page.getByRole('link', { name: '核心仓' }).first().click()
  await expect(page.locator('.core-lot-table')).toContainText('10 股')

  await page.getByRole('link', { name: 'LEAPS' }).first().click()
  await expect(page.getByRole('article', { name: /LEAPS 持仓/ })).toContainText('QQQ')

  await page.getByRole('link', { name: '其他' }).first().click()
  await expect(page.getByRole('table', { name: '当前其他持仓' })).toContainText('BOXX')
  await expect(page.getByRole('table', { name: '当前其他持仓' })).toContainText('IBM')

  await page.getByRole('link', { name: '导入' }).first().click()
  await input.setInputFiles(file)
  await expect(page.getByText('没有需要新增的记录')).toBeVisible()
})
