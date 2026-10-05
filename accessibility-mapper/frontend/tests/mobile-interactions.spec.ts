/* Mobile interaction tests: drawer open/close via FAB and nav view switching.
 * Runs without API mocks — the drawer/nav DOM does not depend on data.
 * The FAB test is skipped at >=1024px where the sidebar is static.
 * Run: npx playwright test tests/mobile-interactions.spec.ts --project=mobile */
import { test, expect } from '@playwright/test'

test('FAB opens drawer, close button is clickable and closes it', async ({ page }) => {
  test.skip(page.viewportSize()!.width >= 1024, 'Desktop shows the sidebar statically (FAB is lg:hidden)')
  await page.goto('/')
  const fab = page.locator('button[aria-label="Open route planner"]')
  await expect(fab).toBeVisible()
  await fab.click()

  const aside = page.locator('aside')
  await expect(aside).toBeVisible()
  await expect(async () => {
    const x = (await aside.boundingBox())?.x ?? 999
    expect(x).toBeLessThan(100)
  }).toPass()

  // Regression: the drawer's close button must be the top element at its
  // own position (previously the z-600 header intercepted the click).
  const close = page.locator('button[aria-label="Close route planner"]')
  await expect(close).toBeVisible()
  const topAtClose = await close.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
    return el.contains(top) || top === el
  })
  expect(topAtClose).toBe(true)

  await close.click()
  await expect(async () => {
    const x = (await aside.boundingBox())?.x ?? 0
    expect(x).toBeGreaterThan(300)
  }).toPass()
})

test('nav view switching swaps the main content', async ({ page }) => {
  await page.goto('/')
  const nav = page.locator('nav[aria-label="Primary"]')
  await expect(nav).toBeVisible()

  const rooms = nav.locator('button').nth(1)
  await rooms.click()
  await expect(page.locator('#main-content')).toContainText(/room/i)

  const back = nav.locator('button').nth(0)
  await back.click()
  await expect(page.locator('#main-content .leaflet-container')).toBeVisible()
})
