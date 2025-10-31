# DockMon Test Suite

Test infrastructure for DockMon v2.0 baseline.

## Structure

```
tests/
├── conftest.py           # Shared pytest fixtures
├── unit/                 # Fast unit tests (mocked dependencies)
├── integration/          # Integration tests (real DB + mocked Docker)
├── contract/             # Contract tests against real Docker SDK
└── fixtures/             # Test data and helpers
```

## Running Tests

### Option 1: Inside Docker Container (Recommended)

```bash
# Install dev dependencies in container
DOCKER_HOST= docker exec dockmon pip3 install -r /app/backend/requirements-dev.txt

# Run all tests
DOCKER_HOST= docker exec dockmon python3 -m pytest /app/backend/tests/

# Run specific test types
DOCKER_HOST= docker exec dockmon python3 -m pytest /app/backend/tests/ -m unit
DOCKER_HOST= docker exec dockmon python3 -m pytest /app/backend/tests/ -m integration
DOCKER_HOST= docker exec dockmon python3 -m pytest /app/backend/tests/ -m contract

# Run with coverage
DOCKER_HOST= docker exec dockmon python3 -m pytest /app/backend/tests/ --cov=backend --cov-report=term
```

### Option 2: Local Virtual Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest tests/
```

## Test Markers

- `@pytest.mark.unit` - Fast unit tests (no external dependencies)
- `@pytest.mark.integration` - Integration tests (require Docker)
- `@pytest.mark.contract` - Contract tests against real Docker SDK
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.database` - Tests that use database

## Writing Tests

See `conftest.py` for available fixtures:
- `test_db` - Temporary SQLite database
- `mock_docker_client` - Mocked Docker SDK client
- `test_host` - Test Docker host record
- `test_container` - Test container record
- `event_bus` - Test event bus instance
- `managed_container` - Container with deployment metadata (for v2.1 tests)

Example:
```python
import pytest

@pytest.mark.unit
def test_something(test_db, test_host):
    # Your test here
    assert True
```
