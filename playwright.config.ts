import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'browser-tests',
  use: {
    baseURL: 'http://localhost:8080',
    screenshot: 'on',
    viewport: { width: 1280, height: 720 },
    locale: 'en-US',
  },
  projects: [
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
  ]
});
