#!/bin/bash

# DockMon Comprehensive Test Runner
# Runs comprehensive tests to verify system functionality
#
# Usage:
#   ./run-tests.sh                    # Run all tests
#   ./run-tests.sh --grep "Security"  # Run only security tests
#   ./run-tests.sh --grep "API"       # Run only API tests
#   ./run-tests.sh --headed           # Run tests in headed mode (visible browser)
#   ./run-tests.sh --html             # Open HTML report after tests

set -e

echo "🧪 DockMon Comprehensive Test Suite"
echo "===================================="
echo ""

# Check if DockMon is running
echo "📡 Checking if DockMon is running..."
if curl -k -s https://localhost:8001/health > /dev/null 2>&1; then
    echo "✅ DockMon is running"
else
    echo "❌ DockMon is not running. Please start it first:"
    echo "   docker compose up -d"
    exit 1
fi

# Setup test environment
echo "📦 Installing test dependencies..."
cd /Users/patrikrunald/Documents/CodeProjects/dockmon/tests
npm install

echo "🌐 Checking Playwright browsers..."
npx playwright install

# Create screenshots directory
mkdir -p screenshots

# Parse command line arguments
PLAYWRIGHT_ARGS=""
SHOW_REPORT=false

for arg in "$@"; do
    if [ "$arg" == "--html" ]; then
        SHOW_REPORT=true
    else
        PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS $arg"
    fi
done

# Show available test categories if --help is requested
if [[ "$*" == *"--help"* ]]; then
    echo ""
    echo "Available test categories (use with --grep):"
    echo "  - Authentication"
    echo "  - Dashboard"
    echo "  - Host Management"
    echo "  - Container Management"
    echo "  - Alert Rules"
    echo "  - Notification Channels"
    echo "  - Settings"
    echo "  - WebSocket"
    echo "  - Mobile UI"
    echo "  - Keyboard Shortcuts"
    echo "  - Data Integrity"
    echo "  - Security"
    echo "  - Edge Cases"
    echo "  - API Endpoints"
    echo "  - Performance"
    echo "  - Cross-Browser"
    echo ""
    echo "Example: ./run-tests.sh --grep \"Security\""
    exit 0
fi

# Run comprehensive tests
echo "🖥️  Running comprehensive tests..."
echo "Test arguments: $PLAYWRIGHT_ARGS"
echo ""

npx playwright test comprehensive-functional-tests.js $PLAYWRIGHT_ARGS

# Check test results
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Tests completed successfully!"
    echo "📁 Screenshots saved to: tests/screenshots/"
    echo "📝 Full report available at: playwright-report/index.html"

    # Open HTML report if requested
    if [ "$SHOW_REPORT" = true ]; then
        echo "📊 Opening HTML report..."
        npx playwright show-report
    fi
else
    echo ""
    echo "❌ Some tests failed"
    echo "📝 Check the report at: playwright-report/index.html"

    # Always show report on failure
    echo "📊 Opening HTML report..."
    npx playwright show-report

    exit 1
fi

echo ""
echo "🎉 Test run completed!"