# DockMon Test Suite

Comprehensive functional tests for DockMon using Playwright.

## Test Configurations

### Desktop Tests (Recommended for Development)
Run tests on desktop Chrome viewport (1280x720):

```bash
cd tests
npx playwright test --config=playwright.desktop.config.js
```

**Report:** `playwright-report-desktop/index.html`
**Time:** ~10 minutes (66 tests)

### Mobile Tests
Run tests on mobile viewport (Pixel 5):

```bash
cd tests
npx playwright test --config=playwright.mobile.config.js
```

**Report:** `playwright-report-mobile/index.html`
**Time:** ~10 minutes (66 tests)

### Running Both Desktop + Mobile
To run both test suites, run them separately:

```bash
cd tests
npx playwright test --config=playwright.desktop.config.js
npx playwright test --config=playwright.mobile.config.js
```

**Time:** ~20 minutes total (132 tests)

💡 **Tip:** Run desktop tests first to establish baseline, then run mobile tests separately if needed.

## Quick Commands

```bash
# Desktop only (faster - recommended for baseline)
cd tests && npx playwright test --config=playwright.desktop.config.js

# Run specific test
cd tests && npx playwright test --config=playwright.desktop.config.js --grep "Should login"

# Debug mode
cd tests && npx playwright test --config=playwright.desktop.config.js --debug

# Show last desktop report
cd tests && npx playwright show-report playwright-report-desktop
```

## Test Coverage

- **Authentication** - Login, logout, password management
- **Dashboard** - Statistics, widgets, drag-and-drop
- **Host Management** - Add, edit, delete Docker hosts
- **Container Operations** - Start, stop, restart, logs, auto-restart
- **Alert Rules** - Create, edit, delete alert rules
- **Notifications** - Configure channels (Discord, Slack, Telegram, Pushover)
- **Settings** - Global settings, blackout windows
- **WebSocket** - Real-time updates
- **Performance** - Load times, responsiveness

## Test Credentials

- **Username:** `admin`
- **Password:** `test1234`
- **URL:** `https://localhost:8001`

## Troubleshooting

### Tests timing out
- Check that DockMon is running: `curl -k https://localhost:8001`
- Verify credentials match your setup
- Some tests may have incorrect selectors - check HTML report for screenshots

### Self-signed certificate errors
- Tests automatically ignore HTTPS errors (`ignoreHTTPSErrors: true`)

### Report not opening
```bash
cd tests
npx playwright show-report playwright-report-desktop
```