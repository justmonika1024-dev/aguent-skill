import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_BACKEND !== '1', 'Set REAL_BACKEND=1 while local backend is running')

test('reads persisted runs, memes and redacted settings through the Vite proxy', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('heading', { name: '运行历史' })).toBeVisible()
  await expect(page.locator('.ant-table-tbody .ant-table-row').first()).toBeVisible()

  await page.getByText('正式梗库', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '正式梗库' })).toBeVisible()
  await expect(page.locator('.ant-table-tbody .ant-table-row').first()).toBeVisible()

  await page.getByText('设置', { exact: true }).click()
  await expect(page.getByText('deepseek-v4-flash')).toBeVisible()
  await expect(page.getByText('页面不会读取或显示 API Key')).toBeVisible()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
})
