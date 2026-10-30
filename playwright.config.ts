import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests/e2e', timeout: 90000, expect: { timeout: 20000 }, workers: 1, use: { baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:3111', trace: 'retain-on-failure' }, outputDir: 'outputs/e2e' });
