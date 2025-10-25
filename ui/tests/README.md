# DockMon UI E2E Tests

End-to-end tests for DockMon user interface using Playwright.

## Structure

```
tests/
├── e2e/
│   ├── auth.spec.ts          # Authentication workflows
│   ├── containers.spec.ts    # Container management
│   └── updates.spec.ts       # Update workflows
└── fixtures/
    ├── auth.ts               # Authentication helpers
    └── testData.ts           # Sample test data
```

## Running Tests

### Prerequisites

```bash
# Install dependencies
npm install

# Install Playwright browsers
npx playwright install
```

### Run Tests

```bash
# Run all E2E tests
npx playwright test

# Run specific test file
npx playwright test tests/e2e/auth.spec.ts

# Run in UI mode (interactive)
npx playwright test --ui

# Run in headed mode (see browser)
npx playwright test --headed

# Generate HTML report
npx playwright show-report
```

### Run Against Running DockMon

```bash
# Start DockMon dev server first
npm run dev

# In another terminal, run tests
npx playwright test
```

## Configuration

See `playwright.config.ts` for:
- Base URL (default: http://localhost:3000)
- Test timeout
- Screenshot on failure
- Trace on retry

## Test Patterns

### Authentication

```typescript
import { login, logout } from '../fixtures/auth';

test('my test', async ({ page }) => {
  await login(page);
  // Test authenticated workflow
});
```

### Container IDs

Tests verify SHORT ID (12 chars) format:
```typescript
const containerId = 'abc123def456';  // 12 characters
expect(containerId).toHaveLength(12);
```

Tests verify composite key format for multi-host:
```typescript
const compositeKey = '7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456';
const [hostId, containerId] = compositeKey.split(':');
expect(hostId).toHaveLength(36);  // UUID
expect(containerId).toHaveLength(12);  // SHORT ID
```

## CI/CD Integration

Tests run in GitHub Actions (see `.github/workflows/test.yml`):
```yaml
- name: Run Playwright tests
  run: |
    cd ui
    npx playwright install --with-deps
    npx playwright test
```

## Troubleshooting

**Tests failing to connect:**
- Ensure DockMon is running on localhost:3000
- Check `playwright.config.ts` baseURL

**Screenshots/traces:**
- Failures save screenshots to `test-results/`
- View with: `npx playwright show-report`

**Slow tests:**
- Tests run serially (workers: 1) to avoid race conditions
- This is intentional for Docker state management
