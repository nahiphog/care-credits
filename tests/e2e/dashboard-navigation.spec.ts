import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page, email = 'doctor@carecredits.local') {
  await expect(page).toHaveURL(/\/log_in(?:\?|$)/);
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill('CareCredits-demo-2026');
  await page.getByRole('button', { name: 'Sign in and search', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toBeVisible();
}

test('all seven sidebar links have reloadable URLs and matching active pages', async ({ page }) => {
  await page.goto('/');
  await signIn(page);
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  await expect(page.getByRole('link', { name: 'Overview', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.reload();
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  expect(new URL(page.url()).pathname).toBe('/');
  const destinations = [
    ['Overview', '/overview'], ['My Credits', '/my-credits'],
    ['Discover', '/discover'], ['Events', '/events'],
    ['Certificates', '/certificates'], ['About credits', '/about-credits'],
    ['Settings', '/settings'],
  ];
  for (const [label, path] of destinations) {
    const link = page.getByRole('link', { name: label, exact: true });
    await expect(link).toHaveAttribute('href', path);
    await link.click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.locator('#page-heading')).toHaveText(label);
    await expect(link).toHaveAttribute('aria-current', 'page');
    await page.reload();
    await expect(page.locator('#page-heading')).toHaveText(label);
    await expect(link).toHaveAttribute('aria-current', 'page');
  }
});

test('direct sign-in retains Settings and history preserves search and profile drafts', async ({ page }) => {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/log_in\?next=%2Fsettings$/);
  await page.getByRole('button', { name: 'New here? Create an account', exact: true }).click();
  await expect(page).toHaveURL(/\/sign_up\?next=%2Fsettings$/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Create your workspace', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Already have an account? Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/log_in\?next=%2Fsettings$/);
  await signIn(page);
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.locator('#page-heading')).toHaveText('Settings');
  await page.getByRole('link', { name: 'Discover', exact: true }).click();
  await page.getByLabel('Search training', { exact: true }).fill('Diabetes care in general practice');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.locator('button.event')).toHaveCount(1);
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Profile city', { exact: true }).fill('Unsaved city draft');
  await page.goBack();
  await expect(page).toHaveURL(/\/discover$/);
  await expect(page.locator('#page-heading')).toHaveText('Discover');
  await expect(page.getByLabel('Search training', { exact: true })).toHaveValue('Diabetes care in general practice');
  await expect(page.locator('button.event')).toHaveCount(1);
  await page.goForward();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByLabel('Profile city', { exact: true })).toHaveValue('Unsaved city draft');
  // A top-bar search also navigates to its own page rather than leaving a stale URL.
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/\/discover$/);
  await expect(page.locator('#page-heading')).toHaveText('Discover');
});

test('sign-in and signup have distinct URLs and logout starts a fresh Overview session', async ({ page }) => {
  // Share login coverage across demo actors without weakening the per-account rate limit.
  await page.goto('/log_in');
  await page.getByRole('button', { name: 'New here? Create an account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create your workspace', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/sign_up$/);
  await page.reload();
  await expect(page.getByLabel('Your name', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/sign_up$/);
  await page.getByRole('button', { name: 'Already have an account? Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/log_in$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/sign_up$/);
  await expect(page.getByRole('heading', { name: 'Create your workspace', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('heading', { name: 'Sign in to search', exact: true })).toBeVisible();
  await signIn(page, 'demo@carecredits.local');
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  expect(new URL(page.url()).pathname).toBe('/');
  await page.getByRole('link', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/log_in$/);
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/log_in$/);
  await signIn(page, 'demo@carecredits.local');
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  // An already authenticated visitor should not get another login form.
  await page.goto('/log_in');
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  expect(new URL(page.url()).pathname).toBe('/');
  await page.goto('/sign_up');
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  expect(new URL(page.url()).pathname).toBe('/');
});

test('disabled signup returns to sign-in while preserving the intended dashboard page', async ({ page }) => {
  await page.route('**/api/v1/config', route => route.fulfill({ json: { signup_enabled: false, demo: true } }));
  await page.goto('/sign_up?next=%2Fsettings');
  await expect(page).toHaveURL(/\/log_in\?next=%2Fsettings$/);
  await expect(page.getByRole('heading', { name: 'Sign in to search', exact: true })).toBeVisible();
  await expect(page.getByLabel('Your name', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'New here? Create an account', exact: true })).toHaveCount(0);
});

test('login rejects an external return destination', async ({ page }) => {
  await page.goto('/log_in?next=https%3A%2F%2Fexample.com');
  await signIn(page, 'demo@carecredits.local');
  await expect(page.locator('#page-heading')).toHaveText('Overview');
  expect(new URL(page.url()).pathname).toBe('/');
});

test('an unavailable session check keeps the error and retry on the requested page', async ({ page }) => {
  await page.route('**/api/v1/me', route => route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } }));
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'CareCredits is unavailable' })).toBeVisible();
  await expect(page).toHaveURL(/\/settings$/);
  await page.unroute('**/api/v1/me');
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page).toHaveURL(/\/log_in\?next=%2Fsettings$/);
  await signIn(page, 'demo@carecredits.local');
  await expect(page.locator('#page-heading')).toHaveText('Settings');
});
