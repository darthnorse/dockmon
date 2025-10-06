# DockMon UI - Testing Guide

Comprehensive testing documentation for the React frontend.

## Test Stack

- **Test Runner**: Vitest (Vite-native, fast)
- **Testing Library**: React Testing Library
- **Assertions**: Vitest + jest-dom matchers
- **Environment**: jsdom (browser simulation)
- **Coverage**: v8 provider

## Running Tests

```bash
# Watch mode (recommended during development)
npm test

# Run once (CI mode)
npm test -- --run

# With UI (interactive)
npm run test:ui

# Generate coverage report
npm run test:coverage

# Type check (runs before build)
npm run type-check
```

## Test Files

### Test Organization
```
src/
├── App.test.tsx                    # Routing tests
├── lib/api/client.test.ts          # API client tests
├── features/
│   └── auth/
│       ├── AuthContext.test.tsx    # Auth context tests
│       └── LoginPage.test.tsx      # Login UI tests
└── test/
    ├── setup.ts                    # Global test setup
    └── utils.tsx                   # Test utilities
```

## Coverage Requirements

**Minimum Thresholds**: 80% across all metrics
- Lines: 80%
- Functions: 80%
- Branches: 80%
- Statements: 80%

**Current Coverage** (as of Phase 2):
```
File                  | Lines | Functions | Branches | Statements
----------------------|-------|-----------|----------|------------
lib/api/client.ts     | 100%  | 100%      | 100%     | 100%
features/auth/api.ts  | 100%  | 100%      | 100%     | 100%
features/auth/        | >90%  | >90%      | >90%     | >90%
App.tsx               | >85%  | >85%      | >85%     | >85%
```

## Test Patterns

### 1. Component Testing

```typescript
import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '@/test/utils'
import { MyComponent } from './MyComponent'

describe('MyComponent', () => {
  it('should render correctly', () => {
    render(<MyComponent />)

    expect(screen.getByText(/hello/i)).toBeInTheDocument()
  })

  it('should handle user interaction', async () => {
    const user = userEvent.setup()
    render(<MyComponent />)

    await user.click(screen.getByRole('button'))

    expect(await screen.findByText(/clicked/i)).toBeInTheDocument()
  })
})
```

### 2. API Testing

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiClient } from './client'

describe('API Client', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  it('should make authenticated request', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: 'test' }),
    })

    await apiClient.get('/test')

    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        credentials: 'include', // Cookie auth
      })
    )
  })
})
```

### 3. Context/Hook Testing

```typescript
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuth } from './AuthContext'

describe('useAuth', () => {
  it('should return auth state', async () => {
    const wrapper = ({ children }) => (
      <QueryClientProvider client={new QueryClient()}>
        {children}
      </QueryClientProvider>
    )

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.isAuthenticated).toBe(true)
  })
})
```

### 4. Async Testing

```typescript
// ✅ CORRECT: Use waitFor for async state changes
await waitFor(() => {
  expect(screen.getByText(/success/i)).toBeInTheDocument()
})

// ✅ CORRECT: Use findBy for async elements
const element = await screen.findByText(/success/i)
expect(element).toBeInTheDocument()

// ❌ WRONG: Don't use getBy for async elements
expect(screen.getByText(/success/i)).toBeInTheDocument() // Fails!
```

## Test Utilities

### Custom Render

```typescript
import { render } from '@/test/utils'

// Automatically wraps with QueryClientProvider + BrowserRouter
render(<MyComponent />)
```

### Query Client

```typescript
import { createTestQueryClient } from '@/test/utils'

const queryClient = createTestQueryClient()
// Fresh client for each test, no retry, silent errors
```

## Mocking

### API Mocking

```typescript
import { vi } from 'vitest'
import { authApi } from '@/features/auth/api'

// Mock the entire module
vi.mock('@/features/auth/api', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

// Use in tests
vi.mocked(authApi.login).mockResolvedValueOnce({
  user: { id: 1, username: 'test' },
})
```

### Fetch Mocking

```typescript
beforeEach(() => {
  global.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

vi.mocked(global.fetch).mockResolvedValueOnce({
  ok: true,
  json: async () => ({ data: 'test' }),
})
```

## Best Practices

### 1. Test User Behavior, Not Implementation

```typescript
// ✅ GOOD: Test what user sees
expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument()

// ❌ BAD: Test internal state
expect(component.state.isLoggedIn).toBe(false)
```

### 2. Use Accessible Queries

```typescript
// ✅ GOOD: Semantic queries (accessible)
screen.getByRole('button', { name: /submit/i })
screen.getByLabelText(/username/i)
screen.getByText(/welcome/i)

// ❌ BAD: Non-semantic queries
screen.getByTestId('submit-button')
screen.getByClassName('username-input')
```

### 3. Avoid Test Pollution

```typescript
describe('MyComponent', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    // Fresh client for each test
    queryClient = createTestQueryClient()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })
})
```

### 4. Test Error States

```typescript
it('should handle API errors gracefully', async () => {
  vi.mocked(authApi.login).mockRejectedValueOnce(
    new ApiError('Unauthorized', 401)
  )

  render(<LoginPage />)
  // ... trigger login

  expect(await screen.findByText(/invalid username or password/i))
    .toBeInTheDocument()
})
```

### 5. Test Loading States

```typescript
it('should show loading state', async () => {
  vi.mocked(authApi.login).mockImplementation(
    () => new Promise(() => {}) // Never resolves
  )

  render(<LoginPage />)
  // ... trigger login

  expect(screen.getByRole('button', { name: /logging in/i }))
    .toBeDisabled()
})
```

## Accessibility Testing

### Labels and Roles

```typescript
it('should have proper form labels', () => {
  render(<LoginPage />)

  expect(screen.getByLabelText(/username/i)).toHaveAttribute('id', 'username')
  expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument()
})
```

### ARIA Attributes

```typescript
it('should mark errors as alerts', async () => {
  render(<LoginPage />)
  // ... trigger error

  const errorAlert = await screen.findByRole('alert')
  expect(errorAlert).toHaveTextContent(/invalid/i)
})
```

### Focus Management

```typescript
it('should focus first input on mount', () => {
  render(<LoginPage />)

  expect(screen.getByLabelText(/username/i)).toHaveFocus()
})
```

## Security Testing

### Cookie Authentication

```typescript
it('should include credentials in all requests', async () => {
  await apiClient.get('/test')

  expect(global.fetch).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({
      credentials: 'include', // HttpOnly cookie
    })
  )
})
```

### Error Messages

```typescript
it('should not leak sensitive info in errors', async () => {
  // Test that error messages are generic
  expect(await screen.findByText(/invalid username or password/i))
    .toBeInTheDocument()

  // Not "User does not exist" (reveals if username is valid)
})
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - run: npm ci
      - run: npm run type-check
      - run: npm run lint
      - run: npm run test:coverage

      # Fail if coverage below 80%
      - name: Check coverage
        run: |
          if [ $(cat coverage/coverage-summary.json | jq '.total.lines.pct') -lt 80 ]; then
            echo "Coverage below 80%"
            exit 1
          fi
```

## Debugging Tests

### VSCode Launch Config

```json
{
  "type": "node",
  "request": "launch",
  "name": "Debug Vitest",
  "runtimeExecutable": "npm",
  "runtimeArgs": ["run", "test"],
  "console": "integratedTerminal"
}
```

### Console Output

```typescript
// Debug what's rendered
import { screen, debug } from '@testing-library/react'

debug() // Prints entire DOM
debug(screen.getByRole('button')) // Prints specific element
```

### Isolate Tests

```typescript
// Run only this test
it.only('should work', () => {
  // ...
})

// Skip this test
it.skip('should work eventually', () => {
  // ...
})
```

## Common Issues

### Issue: "Unable to find element"

```typescript
// ❌ Element appears async, but using synchronous query
expect(screen.getByText(/success/i)).toBeInTheDocument()

// ✅ Use async query
expect(await screen.findByText(/success/i)).toBeInTheDocument()
```

### Issue: "Test is timing out"

```typescript
// Check if you're awaiting promises
await waitFor(() => {
  expect(screen.getByText(/loaded/i)).toBeInTheDocument()
})
```

### Issue: "Query from a previous test"

```typescript
// Ensure cleanup runs
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup() // Already done in setup.ts
})
```

## Test Coverage Reports

### Generate HTML Report

```bash
npm run test:coverage
open coverage/index.html
```

### Coverage Thresholds

Edit `vitest.config.ts`:

```typescript
coverage: {
  thresholds: {
    lines: 80,      // Minimum 80% line coverage
    functions: 80,  // Minimum 80% function coverage
    branches: 80,   // Minimum 80% branch coverage
    statements: 80, // Minimum 80% statement coverage
  },
}
```

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [jest-dom Matchers](https://github.com/testing-library/jest-dom)
- [Testing Library Best Practices](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)

---

**Status**: ✅ **40+ Tests, 80%+ Coverage, Production-Ready**
