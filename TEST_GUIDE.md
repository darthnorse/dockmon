# DockMon Test Guide

## Overview

This test suite helps prevent the common logic bugs we've been encountering, such as:
- Database constraint violations on restart
- WebSocket parameter extraction issues
- Missing authentication on endpoints
- Resource leaks and connection issues

## Running Tests

### Install Test Dependencies

```bash
cd backend
pip install -r requirements-test.txt
```

### Run All Tests

```bash
cd backend
pytest
```

### Run Specific Test Categories

```bash
# Only unit tests
pytest -m unit

# Only integration tests
pytest -m integration

# Specific test file
pytest tests/test_database.py

# With coverage report
pytest --cov=. --cov-report=html
```

### Run Tests in Docker

```bash
docker compose exec dockmon pytest /app/backend/tests
```

## Test Structure

```
backend/tests/
├── conftest.py           # Shared fixtures and configuration
├── test_database.py      # Database operation tests
├── test_monitor.py       # Docker monitor logic tests
├── test_auth.py          # Authentication tests
└── test_websocket.py     # WebSocket endpoint tests
```

## Key Test Coverage

### Database Tests (`test_database.py`)
- ✅ Duplicate host insertion prevention
- ✅ CRUD operations for hosts, alerts, sessions
- ✅ Session expiration handling
- ✅ Auto-restart configuration

### Monitor Tests (`test_monitor.py`)
- ✅ Host reconnection without DB duplication
- ✅ Connection failure handling
- ✅ Security validation
- ✅ Container restart functionality

### Authentication Tests (`test_auth.py`)
- ✅ Password hashing and validation
- ✅ Session creation and validation
- ✅ Rate limiting on auth endpoints
- ✅ Secure cookie settings

### WebSocket Tests (`test_websocket.py`)
- ✅ Tail parameter extraction from query string
- ✅ Parameter validation and limits
- ✅ Connection cleanup on disconnect
- ✅ Concurrent connection handling

## Adding New Tests

When adding new features or fixing bugs:

1. **Write the test first** (TDD approach)
2. **Run the test** - it should fail
3. **Implement the fix**
4. **Run the test again** - it should pass

### Example Test Template

```python
def test_new_feature(self, temp_db):
    """Test description of what should happen"""
    # Arrange - set up test data

    # Act - perform the action

    # Assert - verify the result
    assert expected == actual
```

## CI/CD Integration

Add to your GitHub Actions workflow:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install dependencies
      run: |
        cd backend
        pip install -r requirements.txt
        pip install -r requirements-test.txt

    - name: Run tests
      run: |
        cd backend
        pytest --cov=. --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## Common Test Patterns

### Mocking Docker Client

```python
@patch('docker_monitor.monitor.docker')
def test_something(self, mock_docker):
    mock_client = MagicMock()
    mock_docker.DockerClient.return_value = mock_client
    # Your test here
```

### Testing Async Functions

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == expected
```

### Using Temp Database

```python
def test_with_db(self, temp_db):
    # temp_db fixture provides clean database
    user = temp_db.create_user({"username": "test"})
    assert user.username == "test"
```

## Debugging Failed Tests

1. **Run with verbose output**: `pytest -vv`
2. **Show print statements**: `pytest -s`
3. **Drop into debugger**: `pytest --pdb`
4. **Run single test**: `pytest tests/test_file.py::test_function`

## Coverage Goals

Aim for:
- **80%+ overall coverage**
- **100% coverage on critical paths** (auth, database ops)
- **Focus on edge cases** that have caused bugs

Check coverage:
```bash
pytest --cov=. --cov-report=term-missing
```

## Next Steps

1. **Run tests before every commit**
2. **Add tests for new features**
3. **Fix any failing tests immediately**
4. **Set up CI to run tests automatically**

This test suite will help catch the "silly logic bugs" before they reach production!