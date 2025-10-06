# DockMon v2 Test Suite

Comprehensive security and functionality tests for v2.0 backend.

---

## Test Coverage

### 🔒 Security Tests

**test_cookie_sessions.py** - Cookie Session Manager
- ✅ Session creation and validation
- ✅ Signature tampering detection
- ✅ Session expiry enforcement
- ✅ IP validation (anti-hijacking)
- ✅ Concurrent access safety
- ✅ Memory leak prevention
- ✅ Session fixation prevention
- ✅ Cryptographic randomness

**test_auth_v2.py** - Authentication API
- ✅ Cookie-based login flow
- ✅ HttpOnly cookie validation
- ✅ SameSite=strict enforcement
- ✅ Argon2id password hashing
- ✅ SQL injection prevention
- ✅ Password timing safety
- ✅ Logout session cleanup

**test_user_preferences.py** - User Preferences API
- ✅ Authentication requirement
- ✅ User data isolation
- ✅ Input validation (Pydantic)
- ✅ SQL injection prevention
- ✅ XSS payload handling
- ✅ Partial update logic
- ✅ CASCADE delete behavior

---

## Running Tests

### Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Run All Tests

```bash
pytest tests/v2/
```

### Run with Coverage

```bash
pytest tests/v2/ --cov=auth --cov=api/v2 --cov-report=html
```

Coverage report will be in `coverage_html/index.html`

### Run Specific Test Files

```bash
# Session manager tests
pytest tests/v2/test_cookie_sessions.py -v

# Auth API tests
pytest tests/v2/test_auth_v2.py -v

# Preferences API tests
pytest tests/v2/test_user_preferences.py -v
```

### Run Security Tests Only

```bash
pytest tests/v2/ -m security
```

### Run with Verbose Output

```bash
pytest tests/v2/ -vv
```

---

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
- Individual function/class testing
- No external dependencies
- Fast execution

### Integration Tests (`@pytest.mark.integration`)
- Multiple components interaction
- May use test database
- Slower execution

### Security Tests (`@pytest.mark.security`)
- Security vulnerability validation
- Attack scenario testing
- Critical for production

---

## Key Test Scenarios

### 1. Session Security

**Session Hijacking Prevention:**
```python
def test_session_ip_validation_prevents_hijacking():
    # Create session from IP A
    token = manager.create_session(..., client_ip="192.168.1.100")

    # Attempt validation from IP B (hijack attempt)
    result = manager.validate_session(token, client_ip="10.0.0.50")

    # Should fail and delete session
    assert result is None
```

**Signature Tampering Detection:**
```python
def test_signature_tampering_detection():
    token = manager.create_session(...)

    # Tamper with token
    tampered = token[:-5] + "XXXXX"

    # Should reject
    assert manager.validate_session(tampered, ...) is None
```

### 2. Authentication Security

**HttpOnly Cookie Verification:**
```python
def test_cookie_not_accessible_via_javascript():
    response = client.post("/api/v2/auth/login", ...)

    # Verify HttpOnly flag in Set-Cookie header
    assert "HttpOnly" in response.headers.get("set-cookie")
```

**SQL Injection Prevention:**
```python
def test_login_sql_injection_prevention():
    payloads = [
        {"username": "admin' OR '1'='1", "password": "anything"},
        {"username": "admin'; DROP TABLE users; --", "password": "x"}
    ]

    for payload in payloads:
        response = client.post("/api/v2/auth/login", json=payload)
        # Should fail safely (401, not crash)
        assert response.status_code == 401
```

### 3. Password Security

**Argon2id Configuration:**
```python
def test_argon2_memory_cost():
    from auth.v2_routes import ph

    # Verify 64MB memory requirement (GPU-resistant)
    assert ph.memory_cost == 65536  # 64MB in KB
```

### 4. Preferences Security

**User Isolation:**
```python
def test_user_isolation():
    # User A's preferences
    # User B should not access User A's data
    # Enforced by WHERE user_id = current_user.id
```

**Input Validation:**
```python
def test_theme_validation():
    # Valid: "dark", "light"
    # Invalid: anything else raises ValidationError
```

---

## Coverage Requirements

### Minimum Coverage: 80%

**Critical Files (100% coverage required):**
- `auth/cookie_sessions.py` - Session manager
- `auth/v2_routes.py` - Auth endpoints
- `api/v2/user.py` - Preferences API

**Current Coverage:**
```bash
pytest tests/v2/ --cov --cov-report=term-missing
```

---

## Memory Safety Tests

### Thread Safety
```python
def test_concurrent_session_access():
    # Multiple threads creating sessions simultaneously
    # No race conditions, no data corruption
```

### Memory Leak Prevention
```python
def test_cleanup_expired_sessions():
    # Create sessions, expire them
    # Verify cleanup removes all expired
    # Prevents unbounded growth
```

### Graceful Shutdown
```python
def test_graceful_shutdown():
    # Cleanup thread terminates properly
    # No hanging threads after shutdown
```

---

## Known Limitations

### Mocking Required
Some tests require mocking because they depend on:
- Database connection (use in-memory SQLite)
- Authenticated session (mock `get_current_user`)

### Time-Based Tests
Session expiry tests may require:
- Time mocking with `freezegun`
- Or very short timeout periods

### Future Improvements
- [ ] Add Playwright E2E tests (cookie flow)
- [ ] Add fuzzing tests (security)
- [ ] Add load tests (concurrent sessions)
- [ ] Add mutation testing (test quality)

---

## Continuous Integration

### GitHub Actions Workflow

```yaml
name: v2 Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests/v2/ --cov --cov-fail-under=80
```

---

## Security Test Checklist

Before deploying v2.0:

- [ ] All session security tests pass
- [ ] All auth API tests pass
- [ ] All preferences API tests pass
- [ ] Coverage > 80%
- [ ] No SQL injection vulnerabilities
- [ ] No XSS vulnerabilities
- [ ] No session fixation vulnerabilities
- [ ] No session hijacking vulnerabilities
- [ ] Password hashing uses Argon2id
- [ ] Cookies are HttpOnly + Secure + SameSite
- [ ] Memory leaks tested and fixed
- [ ] Concurrent access is thread-safe

---

## Test Output Example

```
$ pytest tests/v2/ -v

tests/v2/test_cookie_sessions.py::TestCookieSessionManager::test_create_session PASSED
tests/v2/test_cookie_sessions.py::TestCookieSessionManager::test_validate_session_success PASSED
tests/v2/test_cookie_sessions.py::TestCookieSessionManager::test_session_ip_validation_prevents_hijacking PASSED
tests/v2/test_cookie_sessions.py::TestCookieSessionManager::test_signature_tampering_detection PASSED
tests/v2/test_cookie_sessions.py::TestCookieSessionManager::test_session_expiry PASSED
tests/v2/test_auth_v2.py::TestAuthV2Login::test_login_success_sets_cookie PASSED
tests/v2/test_auth_v2.py::TestAuthV2Login::test_login_sql_injection_prevention PASSED
tests/v2/test_user_preferences.py::TestUserPreferencesAPI::test_get_preferences_requires_auth PASSED

======================================== 25 passed in 2.34s ========================================

Coverage:
auth/cookie_sessions.py     98%
auth/v2_routes.py           95%
api/v2/user.py              92%
```

---

## Troubleshooting

### ImportError: No module named 'auth'
```bash
# Ensure backend is in PYTHONPATH
cd backend
pytest tests/v2/
```

### Tests fail with "No such table: user_prefs"
```bash
# Run Alembic migration first
alembic upgrade head
```

### Coverage not working
```bash
pip install pytest-cov
pytest --cov=auth --cov=api/v2
```

---

**Test Coverage Goal: ✅ 80%+**
**Security Tests: ✅ 100% coverage**
**Ready for Production: After all tests pass**
