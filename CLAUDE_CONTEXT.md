# DockMon Refactoring Context - Resume Guide

**Last Updated:** September 29, 2025
**Status:** Test framework complete, all selectors fixed, ready for refactoring
**Next Task:** Refactor index.html into modular components

---

## 🎯 Current Mission

**GOAL:** Refactor the 248KB, 5,937-line index.html into modular components to make it manageable and prepare for Event Viewer feature addition.

**APPROACH:** "Screw it, let's go for the desired end-state" - full refactoring with comprehensive test coverage to ensure no breakage.

---

## 📊 Current System State

### Files & Sizes
- **Main file:** `/src/index.html` - 248KB, 5,937 lines
- **Status:** ❌ TOO LARGE - needs immediate modularization
- **Authentication:** admin/test1234
- **URL:** https://localhost:8001

### What Works (Verified by Tests)
- ✅ Authentication and login flow (4/4 tests passing)
- ✅ Dashboard loads with sidebar and main content
- ✅ Container operations (start/stop/restart)
- ✅ Auto-restart functionality
- ✅ WebSocket real-time updates
- ✅ API endpoints responding correctly
- ✅ Mobile responsive design
- ✅ Host management (CRUD operations)
- ✅ Alert rules and notifications
- ✅ Security (API auth required)

---

## 🧪 Test Infrastructure (READY TO USE)

### ⚠️ CRITICAL UPDATE - Tests Are Now Fixed!

**Major Test Suite Update (Sept 29):**
- Created comprehensive test suite with 132 tests
- Fixed ALL selector mismatches
- Tests now properly match actual HTML structure
- Mobile navigation issues resolved
- Most tests passing (core functionality verified)

### Test Files (Now in Git)
```bash
tests/
├── comprehensive-functional-tests.js  # 132 tests across 16 categories
├── run-tests.sh                      # Test runner with subset support
├── package.json                      # Dependencies
├── playwright.config.js              # Configuration
└── README.md                          # Documentation
```

### Running Tests
```bash
# Run all tests
cd tests
./run-tests.sh

# Run specific category
./run-tests.sh --grep "Authentication"
./run-tests.sh --grep "Host Management"
./run-tests.sh --grep "Security"

# Run with visible browser
./run-tests.sh --headed

# View HTML report
./run-tests.sh --html
```

### Test Categories (All Fixed)
1. **Authentication** - ✅ All passing
2. **Dashboard** - ✅ Most passing
3. **Host Management** - ✅ CRUD operations work
4. **Container Management** - ✅ Core operations work
5. **Alert Rules** - Fixed selectors (#alertRuleName, #alertHost)
6. **Notification Channels** - Discord/Pushover tests
7. **Settings** - Global configuration
8. **WebSocket** - Real-time updates
9. **Mobile UI** - Navigation fixes applied
10. **Keyboard Shortcuts** - Hotkeys
11. **Data Integrity** - Critical alert update test
12. **Security** - SQL injection, XSS, auth
13. **Edge Cases** - Network failures, timeouts
14. **API Endpoints** - ✅ All passing with auth
15. **Performance** - Load time benchmarks
16. **Integration Scenarios** - Complete workflows

### Key Selector Fixes Applied
```javascript
// OLD (incorrect) → NEW (correct)
#accountModal .modal-title → #accountModal h2
#hostName → input[name="hostname"]
#hostAddress → input[name="hosturl"]
#ruleName → #alertRuleName
#ruleHost → #alertHost
#hostTLS → input[type="checkbox"][name="use_tls"]
button:has-text("Save") → button[type="submit"]
```

---

## 🏗️ Planned Refactoring Structure

### Target Architecture
```
src/
├── index.html (main layout + initialization only)
├── css/
│   ├── variables.css (CSS custom properties)
│   ├── layout.css (layout, sidebar, topbar)
│   ├── components.css (cards, buttons, modals)
│   ├── dashboard.css (dashboard-specific styles)
│   └── responsive.css (media queries)
├── js/
│   ├── core/
│   │   ├── auth.js (authentication)
│   │   ├── websocket.js (WebSocket management)
│   │   ├── api.js (API calls)
│   │   └── utils.js (utilities, icons)
│   ├── components/
│   │   ├── dashboard.js (dashboard functionality)
│   │   ├── hosts.js (host management)
│   │   ├── containers.js (container operations)
│   │   ├── alerts.js (alert rules)
│   │   ├── notifications.js (notification channels)
│   │   ├── settings.js (settings management)
│   │   └── events.js (📌 NEW - event viewer)
│   └── app.js (main application controller)
```

---

## 🆕 Recent Changes (Sept 29)

### 1. Comprehensive Test Suite
- Created 132-test suite covering all features
- Fixed all selector mismatches
- Added mobile navigation handling
- Integrated real test data (hosts, webhooks)
- Tests now in Git (removed from .gitignore)

### 2. unRAID & NAS Support
- **Unified mTLS script** with auto-detection
- Supports: unRAID, Synology, QNAP, TrueNAS
- Platform-specific certificate paths
- Custom Docker restart methods
- Updated README with instructions

### 3. Test Data Configuration
```javascript
const CONFIG = {
    credentials: {
        username: 'admin',
        password: 'test1234'
    },
    testHosts: {
        primary: { address: 'tcp://192.168.1.43:2376' },
        secondary: { address: 'tcp://192.168.1.41:2376' }
    },
    notifications: {
        discord: { webhook: 'https://discord.com/api/webhooks/...' },
        pushover: { appKey: '...', userKey: '...' }
    }
};
```

---

## 🚀 Refactoring Instructions

### Step 1: Pre-Refactoring Baseline
```bash
# Start DockMon
docker compose up -d

# Run comprehensive tests
cd tests
./run-tests.sh > baseline-results.log 2>&1

# Note passing/failing tests
# Most should pass after our fixes
```

### Step 2: Execute Refactoring
```bash
# Extract CSS first (safest)
# Then JavaScript modules
# Update Dockerfile for new structure
# Test after each step
```

### Step 3: Post-Refactoring Verification
```bash
# Rebuild container
docker compose down && docker compose build --no-cache && docker compose up -d

# Run same tests
cd tests
./run-tests.sh > post-refactor-results.log 2>&1

# Compare results
diff baseline-results.log post-refactor-results.log
```

---

## 📁 Important File Locations

### Source Files
- **Main:** `src/index.html` (248KB to be refactored)
- **Docker:** `docker/Dockerfile`
- **Tests:** `tests/comprehensive-functional-tests.js`
- **mTLS Script:** `scripts/setup-docker-mtls.sh` (unified with unRAID support)

### Configuration
- **Git:** Tests now tracked (removed from .gitignore)
- **README:** Updated with unRAID/NAS instructions

---

## 🎯 Next Feature: Event Viewer

### Requirements (Post-Refactoring)
- **Name:** "Event Viewer" (not "log viewer")
- **Location:** New `js/components/events.js`
- **Features:**
  - Real-time event list with color coding
  - Search/filter functionality
  - Host + container combinations
  - Event types: state changes, auto-restarts, alerts
  - Colors: 🟢 starts, 🔴 stops, 🟡 warnings, 🔵 info

### Backend Status
- ✅ Event APIs exist (`/api/events`)
- ✅ Database schema ready (`EventLog` table)
- ✅ Event categories defined
- ✅ Host+container logging implemented

---

## ⚠️ Critical Success Factors

1. **Tests are now fixed** - Use them!
2. **Run tests before and after** each change
3. **DockMon must be running** for tests
4. **Credentials:** admin/test1234
5. **Update Dockerfile** for new file structure
6. **Mobile navigation** helper added to tests

---

## 📞 Resuming Instructions

**To continue from another system:**

1. **Pull latest changes:**
   ```bash
   git pull
   cd tests && npm install
   npx playwright install
   ```

2. **Start DockMon:**
   ```bash
   docker compose up -d
   ```

3. **Run baseline tests:**
   ```bash
   cd tests
   ./run-tests.sh --grep "Authentication|Dashboard|Host"
   ```

4. **Begin refactoring:**
   - Start with CSS extraction
   - Move JavaScript to modules
   - Update Dockerfile
   - Test continuously

5. **Verify no regression:**
   - All tests should maintain same pass/fail status
   - Core functionality must remain intact

---

## 💡 Key Insights

1. **Test suite is comprehensive** - 132 tests covering all features
2. **Selectors are fixed** - Tests now match actual HTML
3. **Mobile handling added** - Tests work on all viewports
4. **unRAID support added** - mTLS script auto-detects platforms
5. **Ready for refactoring** - Tests provide safety net

**Expected Timeline:** 2-3 hours for full refactoring + Event Viewer

---

**Last Session Summary:**
- Fixed all test selector mismatches
- Added unRAID/NAS platform support
- Updated README with platform instructions
- Tests now in Git for portability
- System ready for location switch