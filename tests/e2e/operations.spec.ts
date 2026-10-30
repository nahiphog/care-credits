import { test, expect } from '@playwright/test';

test('disabled email recovery is honest and cannot submit a request', async ({ page }) => {
  await page.goto('/reset-password');
  await expect(page.getByText('Email recovery is not available.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Request reset email' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Back to sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to search' })).toBeVisible();
  await expect(page).toHaveURL(/\/log_in$/);
  await expect(page.getByRole('link', { name: 'Forgot your password?' })).toHaveCount(0);
});

test('reset link leaves the URL, validates confirmation, and clears passwords on success', async ({ page }) => {
  await page.route('**/api/v1/config', route => route.fulfill({ json: { password_recovery_available: true } }));
  let calls = 0;
  await page.route('**/api/v1/auth/password-reset', async route => {
    calls++;
    expect(route.request().postDataJSON()).toEqual({ token: 'test-only-reset-token', new_password: 'Testing-password-1234' });
    await route.fulfill({ json: { message: 'Password reset. Please sign in again on each device.' } });
  });
  await page.goto('/reset-password#token=test-only-reset-token');
  await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible();
  expect(page.url()).not.toContain('#');
  await page.getByLabel('New password', { exact: true }).fill('Testing-password-1234');
  await page.getByLabel('Confirm password').fill('Different-password-1234');
  await page.getByRole('button', { name: 'Reset password' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toHaveText('Passwords do not match.');
  expect(calls).toBe(0);
  await page.getByLabel('Confirm password').fill('Testing-password-1234');
  await page.getByRole('button', { name: 'Reset password' }).click();
  await expect(page.getByRole('status')).toContainText('Password reset.');
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  expect(calls).toBe(1);
});

test('operator can read maintenance receipts and the catalogue quality queue', async ({ page }) => {
  await page.goto('/workspace');
  await page.getByLabel('Email address').fill('demo@carecredits.local');
  await page.getByLabel('Password', { exact: true }).fill('CareCredits-demo-2026');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Training sources', exact: true }).click();
  await page.getByText('Advanced tools & connection details', { exact: true }).click();
  await page.getByText('Maintenance and catalogue quality', { exact: true }).click();
  await page.getByRole('button', { name: 'Refresh checks', exact: true }).click();
  await expect(page.getByRole('heading', { name: /listings need review/ })).toBeVisible();
  await expect(page.getByText(/Last successful run:/)).toBeVisible();
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:900});
    await page.getByText('Maintenance and catalogue quality', { exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await page.screenshot({path:`outputs/e2e/operations-${width}.png`});
  }
});
