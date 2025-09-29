# DockMon Comprehensive Test Suite

Complete functional, API, security, and data integrity tests for the DockMon application.

## Quick Start

```bash
# Run all tests
./run-tests.sh

# Run specific test category
./run-tests.sh --grep "Security"
./run-tests.sh --grep "API"

# Run tests in headed mode (visible browser)
./run-tests.sh --headed

# Open HTML report after tests
./run-tests.sh --html

# View available test categories
./run-tests.sh --help
```

## Test Coverage

The comprehensive test suite (`comprehensive-functional-tests.js`) includes:

### Core Functionality (89+ tests across 16 categories)
1. **Authentication** - Login/logout, session management
2. **Dashboard** - Stats, widgets, real-time updates
3. **Host Management** - Add, edit, delete, TLS configuration
4. **Container Management** - Start/stop/restart, auto-restart
5. **Alert Rules** - Create, edit, delete, multi-host alerts
6. **Notification Channels** - Discord, Pushover, email configuration
7. **Settings** - User preferences, theme, notifications
8. **WebSocket** - Real-time communication, reconnection
9. **Mobile UI** - Responsive design, touch interactions
10. **Keyboard Shortcuts** - Navigation, quick actions
11. **Data Integrity** - Alert rule updates on host deletion (critical test)
12. **Security** - SQL injection, XSS, authentication, CSRF
13. **Edge Cases** - Concurrent operations, network failures, timeouts
14. **API Endpoints** - Full REST API coverage with authentication
15. **Performance** - Load times, rendering, API response times
16. **Cross-Browser** - Chrome, Firefox, Safari, Edge support

## Running Test Subsets

The test suite is structured with `test.describe()` blocks, allowing you to run specific categories:

```bash
# Run only security tests
npx playwright test comprehensive-functional-tests.js --grep "Security"

# Run only API tests
npx playwright test comprehensive-functional-tests.js --grep "API Endpoints"

# Run data integrity tests (includes critical alert rule test)
npx playwright test comprehensive-functional-tests.js --grep "Data Integrity"

# Run multiple categories
npx playwright test comprehensive-functional-tests.js --grep "Security|API"
```

## Test Configuration

The test suite includes real test data in `comprehensive-functional-tests.js`:

```javascript
const CONFIG = {
    baseUrl: 'https://localhost:8001',
    credentials: {
        username: 'admin',
        password: 'test1234'
    },
    testHosts: {
        primary: {
            name: 'Test Host 1',
            address: 'tcp://192.168.1.43:2376',
            tls: false
        },
        secondary: {
            name: 'Test Host 2',
            address: 'tcp://192.168.1.41:2376',
            tls: false
        }
    },
    notifications: {
        discord: {
            webhook: 'https://discord.com/api/webhooks/...'
        },
        pushover: {
            appKey: 'aqopa9hax37rx4evz4a3a4suc2s2kj',
            userKey: 'uaJALmMcnjAXt5SgLxvb4gxwaXJSkv'
        }
    }
};
```

## Usage for Development

### Before refactoring:
```bash
# Establish baseline
./run-tests.sh > baseline-results.log 2>&1
```

### During development:
```bash
# Run specific tests while developing
./run-tests.sh --grep "Container Management" --headed
```

### After refactoring:
```bash
# Run full test suite
./run-tests.sh > refactored-results.log 2>&1

# Compare results
diff baseline-results.log refactored-results.log
```

## Prerequisites

- DockMon running on https://localhost:8001
- Node.js and npm installed
- Playwright browsers installed (automatic via run-tests.sh)

## Test Reports

- **Console output**: Real-time test progress
- **HTML report**: `playwright-report/index.html`
- **Screenshots**: `tests/screenshots/` (on failures)
- **Videos**: Can be enabled in `playwright.config.js`

## Files

- `comprehensive-functional-tests.js` - Main test suite with all tests
- `playwright.config.js` - Playwright configuration
- `run-tests.sh` - Test runner script with options
- `package.json` - Dependencies

## Regular Development Process

As requested, this test suite is designed for regular use during development:

1. **Before making changes**: Run baseline tests
2. **During development**: Run specific test categories
3. **After changes**: Run full suite to ensure no regressions
4. **Before commits**: Run security and API tests minimum
5. **Before deployment**: Run complete suite