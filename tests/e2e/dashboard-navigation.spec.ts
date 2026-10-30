import { test, expect, type Page } from '@playwright/test';

async function signIn(page: Page) {
  await page.getByLabel('Email address').fill('doctor@carecredits.local');
  await page.getByLabel('Password', { exact: true }).fill('CareCredits-demo-2026');
  await page.getByRole('button', { name: 'Sign in and search', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toBeVisible();
}

test('all seven sidebar links have reloadable URLs and matching active pages', async ({ page }) => {
  await page.goto('/');
  await signIn(page);
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
