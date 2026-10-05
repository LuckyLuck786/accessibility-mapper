import { test, expect, type Page } from '@playwright/test'

/* ──────────────────────────────────────────────
 * Mock API data — minimal but valid payloads for
 * every endpoint the frontend fetches on load.
 * ────────────────────────────────────────────── */

const mockOverview = {
  app: 'Campus Accessibility Mapper',
  version: '1.0.0',
  database: 'postgresql',
  graph: {
    nodes: 48,
    edges: 57,
    step_free_edges: 30,
    stairs_edges: 12,
    buildings: 15,
    lift_nodes: 5,
    entrances: 20,
    barrier_severed_edges: 3,
    algorithm: 'astar',
    speed_mps: { walk: 1.4, wheelchair: 0.8 },
  },
  cv: { engine: 'heuristic', opencv_available: false, hint: 'mock' },
  presets: [],
  bounds: {
    min_latitude: 47.64,
    max_latitude: 47.66,
    min_longitude: -122.32,
    max_longitude: -122.30,
    center_latitude: 47.6555,
    center_longitude: -122.306,
  },
  formula: 'mock formula',
  policies: { auto_verify_confidence: 0.85, consensus_confirmations: 2, duplicate_radius_m: 15 },
}

const mockNetwork = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[-122.306, 47.6555], [-122.3, 47.655]] },
      properties: {
        id: 'e1',
        name: 'Main Walk',
        kind: 'footpath',
        source_node_id: 'n1',
        target_node_id: 'n2',
        distance_m: 100,
        is_step_free: true,
        width_m: 3,
        incline_pct: 0,
        active_barriers_count: 0,
        weight: 1,
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-122.306, 47.6555] },
      properties: {
        id: 'n1',
        name: 'Red Square',
        kind: 'building',
        has_elevator: false,
        is_entrance: true,
        is_step_free: true,
        building_code: 'B1',
        campus_zone: 'north',
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-122.3, 47.655] },
      properties: {
        id: 'n2',
        name: 'Library',
        kind: 'building',
        has_elevator: true,
        is_entrance: true,
        is_step_free: true,
        building_code: 'B2',
        campus_zone: 'north',
      },
    },
  ],
  meta: { nodes: 2, edges: 1, step_free_edges: 1, generated_at: '2024-01-01T00:00:00Z' },
}

const mockBarriers = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [-122.305, 47.6553] },
      properties: {
        id: 1,
        category: 'obstacle',
        label: 'Test barrier',
        severity: 5,
        color: '#ef4444',
        latitude: 47.6553,
        longitude: -122.305,
        confidence: 0.9,
        status: 'verified',
        description: 'A test barrier',
        redacted_faces: 0,
        redacted_plates: 0,
        detection_source: 'test',
        edge_id: 'e1',
        reporter_label: 'test',
        confirmations: 1,
        ticket_id: null,
        is_active: true,
        is_hard_block: false,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        verified_at: '2024-01-01T00:00:00Z',
        resolved_at: null,
        expires_at: null,
        age_hours: 1,
        resolution_hours: null,
      },
    },
  ],
  meta: {
    count: 1,
    generated_at: '2024-01-01T00:00:00Z',
    categories: ['obstacle'],
    verified: 1,
    unverified: 0,
    in_progress: 0,
  },
}

const mockPresets = {
  presets: [
    { node_id: 'n1', label: 'Red Square', latitude: 47.6555, longitude: -122.306, has_elevator: false, is_step_free: true, campus_zone: 'north' },
    { node_id: 'n2', label: 'Library', latitude: 47.655, longitude: -122.3, has_elevator: true, is_step_free: true, campus_zone: 'north' },
  ],
  bounds: mockOverview.bounds,
}

const mockCategories = {
  categories: [
    { category: 'obstacle', label: 'Obstacle', color: '#ef4444', severity: 5, step_free_blocking: true, active_count: 1 },
    { category: 'construction', label: 'Construction', color: '#f59e0b', severity: 4, step_free_blocking: true, active_count: 0 },
  ],
}

/** Intercept every /api/v1/* call and return the matching mock payload. */
async function mockApi(page: Page) {
  await page.route('**/api/v1/overview', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockOverview) }),
  )
  await page.route('**/api/v1/campus/network', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNetwork) }),
  )
  await page.route('**/api/v1/routes/presets', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPresets) }),
  )
  await page.route('**/api/v1/barriers/active', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockBarriers) }),
  )
  await page.route('**/api/v1/barriers/categories', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockCategories) }),
  )
  // Leaflet tile requests — return a 1×1 transparent PNG so the map renders without network.
  await page.route('**/tile.openstreetmap.org/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64'),
    }),
  )
}

/** Wait until the overview stats text has loaded (loading spinner gone, not "Connecting…"). */
async function waitForAppReady(page: Page) {
  await page.waitForFunction(() => {
    const loading = document.querySelector('svg.animate-spin')
    const stats = document.querySelector('p.text-slate-500')
    return !loading && stats && !stats.textContent?.includes('Connecting')
  }, { timeout: 15_000 })
}

/* ──────────────────────────────────────────────
 * Tests
 * ────────────────────────────────────────────── */

test.describe('Mobile layout — 375×812', () => {
  test.beforeEach(async ({ page }) => {
    const { width } = page.viewportSize() ?? { width: 0, height: 0 }
    if (width !== 375) test.skip('Mobile-only test suite (375×812)')
    await mockApi(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('header is compact (under 100px), not the 137px bug', async ({ page }) => {
    const header = page.locator('header')
    const box = await header.boundingBox()
    expect(box).not.toBeNull()
    if (box) expect(Math.round(box.height)).toBeLessThan(100)
  })

  test('stats text renders as JSX, not literal template-literal HTML', async ({ page }) => {
    const stats = page.locator('header p.text-slate-500')
    await expect(stats).toBeVisible()
    const text = await stats.innerText()
    // The old bug rendered raw `<span>` tags as visible text
    expect(text).not.toContain('<span')
    // CV label is hidden below 400px via `hidden xs:inline` — innerText drops it,
    // but a rendered-visible CV label (or the old literal-text bug) would show it.
    expect(text).not.toContain('CV:')
  })

  test('nav button labels are icon-only below 400px (xs breakpoint)', async ({ page }) => {
    const navButtons = page.locator('nav[aria-label="Primary"] button')
    const count = await navButtons.count()
    expect(count).toBeGreaterThan(0)
    // Every nav button should contain a span that is display:none (hidden)
    for (let i = 0; i < count; i++) {
      const span = navButtons.nth(i).locator('span')
      const display = await span.evaluate((el) => getComputedStyle(el).display)
      expect(display).toBe('none')
    }
  })

  test('route planner FAB is positioned in top-right, away from left-side zoom controls', async ({ page }) => {
    const fab = page.locator('button[aria-label="Open route planner"]')
    await expect(fab).toBeVisible()
    const fabBox = await fab.boundingBox()
    expect(fabBox).not.toBeNull()
    if (fabBox) {
      // FAB should be on the right half of the 375px viewport
      expect(fabBox.x).toBeGreaterThan(375 / 2)
    }
  })

  test('nav toolbar wraps to its own row below the header content', async ({ page }) => {
    // The action buttons (A11y) and the nav toolbar should be on different rows
    const a11yButton = page.getByRole('button', { name: 'A11y' })
    const nav = page.locator('nav[aria-label="Primary"]')
    const a11yBox = await a11yButton.boundingBox()
    const navBox = await nav.boundingBox()
    expect(a11yBox).not.toBeNull()
    expect(navBox).not.toBeNull()
    if (a11yBox && navBox) {
      // nav should start below the A11y button (different row)
      expect(navBox.y).toBeGreaterThan(a11yBox.y + a11yBox.height - 10)
    }
  })
})
