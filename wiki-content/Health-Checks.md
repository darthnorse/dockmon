# Health Checks

Monitor container health with HTTP/HTTPS endpoint checking and automatic recovery in DockMon v2.

---

## Overview

DockMon v2's health check system monitors container HTTP/HTTPS endpoints to verify service availability. Unlike Docker's built-in health checks, DockMon's health checks run externally and can trigger automatic container restarts, making them ideal for production monitoring.

**Key features:**
- **HTTP/HTTPS endpoint monitoring** - Check any HTTP/HTTPS URL
- **Configurable check interval** - From 10 seconds to 1 hour
- **Flexible status code matching** - Single codes, ranges, or multiple values
- **Failure threshold** - Consecutive failures before unhealthy
- **Success threshold** - Consecutive successes before healthy (debouncing)
- **Auto-restart on failure** - Automatically restart unhealthy containers
- **Response time tracking** - Monitor endpoint performance
- **SSL certificate validation** - Verify HTTPS certificates
- **Custom headers** - Send authentication or custom headers
- **Basic/Bearer authentication** - Support for authenticated endpoints
- **Health history** - Track health status over time
- **Alert integration** - Trigger alerts on health status changes

---

## How Health Checks Work

### Health Check Workflow

1. **Configuration** - Define endpoint URL, check interval, and criteria
2. **Background polling** - DockMon periodically checks the endpoint
3. **Status evaluation** - Compare response to expected status codes
4. **State tracking** - Count consecutive successes/failures
5. **State transition** - Change status when threshold exceeded
6. **Event emission** - Emit health status change event
7. **Auto-restart** (optional) - Restart container if unhealthy
8. **Alert triggering** (optional) - Send notification on status change

**Example timeline:**
```
0s:   Check http://localhost:8080/health → 200 OK (success)
60s:  Check http://localhost:8080/health → 200 OK (success)
120s: Check http://localhost:8080/health → 500 Error (failure, count=1)
180s: Check http://localhost:8080/health → 500 Error (failure, count=2)
240s: Check http://localhost:8080/health → 500 Error (failure, count=3)
      → Threshold reached (3) → Status: UNHEALTHY
      → Auto-restart triggered (if enabled)
      → Alert sent (if configured)
```

### Health States

**Healthy**
- Endpoint responding with expected status codes
- Consecutive successes ≥ success threshold
- Container is functioning normally

**Unhealthy**
- Endpoint not responding or returning error status
- Consecutive failures ≥ failure threshold
- Container may need restart

**Unknown** (initial state)
- Health check just configured
- Not enough data to determine status
- First check in progress

---

## Configuring Health Checks

### Per-Container Configuration

1. Navigate to **Container Dashboard**
2. Click container to open **Details** view
3. Go to **Health Check** tab
4. Click **Configure Health Check**
5. Fill in configuration (see below)
6. Click **Save**

### Configuration Options

#### Enabled

**Toggle:** Enable or disable health check

**Default:** Disabled

**Note:** Disable temporarily during maintenance or testing.

#### URL

**Field:** Endpoint URL to check

**Format:** `http://` or `https://` followed by host and path

**Examples:**
```
http://localhost:8080/health
https://api.example.com/status
http://192.168.1.10:3000/api/ping
https://container-name:443/healthz
```

**Important:**
- Use `localhost` if health endpoint is on the same container
- Use container name if checking another container in same network
- Use host IP if checking from DockMon host
- Ensure endpoint is reachable from DockMon container

**Best practice:** Create a dedicated health endpoint in your application that checks:
- Database connectivity
- Cache connectivity
- Critical service dependencies
- Disk space
- Memory usage

**Example health endpoint (Node.js):**
```javascript
app.get('/health', async (req, res) => {
  try {
    // Check database
    await db.ping();

    // Check Redis
    await redis.ping();

    // All checks passed
    res.status(200).json({ status: 'healthy' });
  } catch (error) {
    res.status(500).json({ status: 'unhealthy', error: error.message });
  }
});
```

#### HTTP Method

**Options:** GET, POST, HEAD

**Default:** GET

**When to use:**
- **GET** - Most common, retrieve health status
- **POST** - Trigger health check logic (less common)
- **HEAD** - Check availability without response body (efficient)

**Recommendation:** Use GET unless your health endpoint requires POST.

#### Expected Status Codes

**Field:** HTTP status codes that indicate healthy

**Format:** Single code, comma-separated, or ranges

**Examples:**
```
200                    # Only 200 OK
200,201,204            # Multiple specific codes
200-299                # Any 2xx success code
200-299,301            # 2xx or 301
```

**Default:** `200`

**Common patterns:**
- `200` - Standard success
- `200-299` - Any successful response
- `200,204` - Success with or without content
- `200-299,404` - Success or not found (for optional resources)

**Recommendation:** Use `200` for simple health checks, `200-299` for more flexible checks.

#### Timeout

**Field:** Maximum seconds to wait for response

**Range:** 5-60 seconds

**Default:** 10 seconds

**Considerations:**
- **Too short** - Slow endpoints marked unhealthy unnecessarily
- **Too long** - Delays detection of real failures

**Recommendation:**
- 5s for fast endpoints (local cache)
- 10s for typical web services (default)
- 30s for slow services (complex database queries)

#### Check Interval

**Field:** Seconds between health checks

**Range:** 10-3600 seconds (10s to 1 hour)

**Default:** 60 seconds

**Considerations:**
- **Short interval** - Faster failure detection, higher load on endpoint
- **Long interval** - Slower failure detection, lower load on endpoint

**Recommendation:**
- 10-30s for critical services (fast detection)
- 60s for standard services (default, balanced)
- 300s (5 min) for non-critical or slow endpoints

**Formula:** Check interval should be at least 2x timeout to avoid overlap.

#### Failure Threshold

**Field:** Consecutive failures before status becomes unhealthy

**Range:** 1-10

**Default:** 3

**Purpose:** Prevent false positives from temporary glitches

**Examples:**
```
Threshold = 1: Unhealthy after first failure (very sensitive)
Threshold = 3: Unhealthy after 3 consecutive failures (balanced)
Threshold = 5: Unhealthy after 5 consecutive failures (tolerant)
```

**Recommendation:**
- 1-2 for critical services that must be highly available
- 3 for standard services (default)
- 5+ for services with expected intermittent failures

#### Success Threshold

**Field:** Consecutive successes before status becomes healthy

**Range:** 1-10

**Default:** 1

**Purpose:** Prevent flapping (rapid healthy/unhealthy transitions)

**Examples:**
```
Threshold = 1: Healthy after first success (fast recovery)
Threshold = 3: Healthy after 3 consecutive successes (cautious)
```

**Recommendation:**
- 1 for most services (default, fast recovery)
- 2-3 if container has startup issues or slow initialization

**Use case:** If container passes health check but crashes 10s later, increase success threshold to ensure stability.

#### Follow Redirects

**Toggle:** Follow HTTP 3xx redirects

**Default:** Enabled

**When to disable:**
- Health endpoint should NOT redirect
- Want to detect unexpected redirects as failures

**Example:**
```
URL: http://app.com/health
Redirects to: http://app.com/login
→ If Follow Redirects = true: Checks /login (probably wrong)
→ If Follow Redirects = false: 301 redirect treated as failure (correct)
```

#### Verify SSL

**Toggle:** Validate HTTPS SSL certificates

**Default:** Enabled

**When to disable:**
- Using self-signed certificates
- Development/testing environments
- Internal services with custom CAs

**Warning:** Disabling SSL verification in production reduces security. Use proper certificates instead.

#### Custom Headers

**Field:** JSON object of HTTP headers

**Format:**
```json
{
  "X-API-Key": "secret-key-here",
  "User-Agent": "DockMon-HealthChecker/2.0",
  "Accept": "application/json"
}
```

**Use cases:**
- API key authentication
- Custom user agent
- Accept headers for specific response formats
- Correlation IDs for tracing

**Note:** Headers must be valid JSON. Invalid JSON is ignored with warning in logs.

#### Authentication

**Field:** JSON object for Basic or Bearer auth

**Formats:**

**Basic authentication:**
```json
{
  "type": "basic",
  "username": "health-checker",
  "password": "secret-password"
}
```

**Bearer token:**
```json
{
  "type": "bearer",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Use cases:**
- Protected health endpoints
- Microservices requiring auth
- API gateways

**Security note:** Credentials are stored in database. Ensure database is properly secured.

#### Auto-Restart on Failure

**Toggle:** Automatically restart container when unhealthy

**Default:** Disabled

**Behavior:**
- When status becomes unhealthy → restart container
- Restart is rate-limited (max 3 restarts per 10 minutes)
- Prevents infinite restart loops

**Use cases:**
- Production services that can recover via restart
- Containers with transient issues (memory leaks, connection pool exhaustion)
- Critical services requiring high availability

**Warning:**
- Ensure restart actually fixes the issue (not a configuration problem)
- Monitor restart frequency to detect systemic issues
- Consider fixing root cause instead of relying on restarts

**Restart loop protection:**
```
Restart 1: Immediately
Restart 2: After next unhealthy detection
Restart 3: After next unhealthy detection
Restart 4+: Blocked for 10 minutes (prevents infinite loop)
```

---

## Health Check Examples

### Example 1: Simple Web Application

**Application:** Node.js Express app on port 3000

**Health endpoint:**
```javascript
app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok' });
});
```

**DockMon configuration:**
```
Enabled: Yes
URL: http://localhost:3000/health
Method: GET
Expected Status Codes: 200
Timeout: 10 seconds
Check Interval: 60 seconds
Failure Threshold: 3
Success Threshold: 1
Follow Redirects: Yes
Verify SSL: N/A (HTTP)
Custom Headers: None
Authentication: None
Auto-Restart on Failure: Yes
```

**Result:** DockMon checks every 60s. If 3 consecutive failures, container restarts.

### Example 2: Database-Backed Service

**Application:** Python Flask app with PostgreSQL

**Health endpoint:**
```python
@app.route('/health')
def health():
    try:
        # Check database connectivity
        db.session.execute('SELECT 1')
        return {'status': 'healthy', 'database': 'connected'}, 200
    except Exception as e:
        return {'status': 'unhealthy', 'error': str(e)}, 500
```

**DockMon configuration:**
```
Enabled: Yes
URL: http://localhost:5000/health
Method: GET
Expected Status Codes: 200
Timeout: 15 seconds  # Database query may be slow
Check Interval: 30 seconds
Failure Threshold: 2  # More sensitive for critical service
Success Threshold: 2  # Require stability before marking healthy
Auto-Restart on Failure: Yes
```

**Rationale:** Lower thresholds for faster detection. Higher timeout for DB queries.

### Example 3: HTTPS API with Authentication

**Application:** REST API with JWT authentication

**Health endpoint:**
```javascript
app.get('/api/health', authMiddleware, (req, res) => {
  res.status(200).json({ status: 'healthy' });
});
```

**DockMon configuration:**
```
Enabled: Yes
URL: https://api.example.com/api/health
Method: GET
Expected Status Codes: 200
Timeout: 10 seconds
Check Interval: 60 seconds
Failure Threshold: 3
Success Threshold: 1
Verify SSL: Yes
Custom Headers:
{
  "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
Auto-Restart on Failure: No  # Alert only, manual investigation
```

**Alternative using auth config:**
```
Authentication:
{
  "type": "bearer",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### Example 4: Microservice Health Check

**Application:** Java Spring Boot microservice

**Health endpoint (Spring Actuator):**
```
http://localhost:8080/actuator/health
```

**Response:**
```json
{
  "status": "UP",
  "components": {
    "db": {"status": "UP"},
    "diskSpace": {"status": "UP"},
    "ping": {"status": "UP"}
  }
}
```

**DockMon configuration:**
```
Enabled: Yes
URL: http://localhost:8080/actuator/health
Method: GET
Expected Status Codes: 200
Timeout: 10 seconds
Check Interval: 30 seconds
Failure Threshold: 3
Success Threshold: 1
Auto-Restart on Failure: Yes
```

**Note:** Spring Boot's `/actuator/health` returns 200 when UP, 503 when DOWN.

### Example 5: Self-Signed Certificate

**Application:** HTTPS service with self-signed cert

**DockMon configuration:**
```
Enabled: Yes
URL: https://localhost:8443/health
Method: GET
Expected Status Codes: 200
Verify SSL: No  # Disable for self-signed cert
Auto-Restart on Failure: Yes
```

**Better approach:** Use proper certificates (Let's Encrypt) instead of disabling SSL verification.

---

## Health Check vs Docker Health Check

### Docker's Built-In Health Check

**How it works:**
- Runs inside the container
- Configured in Dockerfile or docker-compose.yml
- Checks container health from inside

**Example Dockerfile:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

**Limitations:**
- ❌ Requires healthcheck command in container
- ❌ Cannot check external dependencies
- ❌ Limited auto-restart options
- ❌ No centralized monitoring

### DockMon's Health Check

**How it works:**
- Runs outside the container (from DockMon container)
- Configured via DockMon UI
- Checks container health from external perspective

**Advantages:**
- ✅ No changes to container required
- ✅ Centralized monitoring across all containers
- ✅ Flexible auto-restart logic
- ✅ Integration with DockMon alerts
- ✅ Historical health tracking
- ✅ Can check external endpoints
- ✅ Detailed response time metrics

**Disadvantages:**
- ❌ Requires health endpoint exposed
- ❌ Additional configuration in DockMon

### When to Use Which?

**Use Docker health check when:**
- Container doesn't expose HTTP endpoints
- Checking container-internal state (file existence, process running)
- Want basic health status in `docker ps`

**Use DockMon health check when:**
- Container has HTTP/HTTPS endpoint
- Need auto-restart on failure
- Want centralized monitoring
- Need historical health data
- Want alert integration

**Best practice:** Use both for comprehensive monitoring:
- Docker health check for internal state
- DockMon health check for external availability

---

## Health Check Alerts

### Creating Health Check Alerts

1. Navigate to **Alert Rules**
2. Click **Create Rule**
3. Select containers to monitor
4. In **Trigger Conditions**, check:
   - Event: **Health: Unhealthy**
   - (Optional) Event: **Health: Healthy** (recovery notification)
5. Select notification channels
6. Set cooldown period (e.g., 15 minutes)
7. Click **Create**

**Example alert rule:**
```
Name: Production Service Health Alert
Containers: All with tag "production"
Events: Health: Unhealthy
Channels: Discord #alerts, Pushover Mobile
Cooldown: 15 minutes
```

**Result:** Get notified when any production container becomes unhealthy.

See [Alert Rules](Alert-Rules) for details.

### Alert Message Content

**Health: Unhealthy alert includes:**
- Container name
- Host name
- Health check URL
- Error message
- Consecutive failure count
- Response time (if available)
- Timestamp

**Example alert:**
```
[ALERT] Container Unhealthy

Container: api-backend
Host: Production-Server
Health Check: http://localhost:8080/health
Status: Unhealthy
Error: Status 500 (expected 200)
Consecutive Failures: 3 / 3
Response Time: 2150ms
Time: 2025-10-18 14:32:15 UTC

Auto-restart: Triggered
```

---

## Response Time Tracking

### Metrics Collected

For each health check, DockMon records:
- **Response time** - Milliseconds from request to response
- **Last checked** - Timestamp of most recent check
- **Last success** - Timestamp of most recent successful check
- **Last failure** - Timestamp of most recent failure
- **Consecutive successes** - Current success streak
- **Consecutive failures** - Current failure streak

### Viewing Response Times

**Location:** Container Details → Health Check tab

**Display:**
```
Last Response Time: 145ms
Average Response Time: 203ms (last 24 hours)
Max Response Time: 1250ms (last 24 hours)
```

**Use cases:**
- Detect performance degradation
- Identify slow endpoints
- Capacity planning

**Future enhancement:** Response time graphing and trend analysis.

---

## Best Practices

### Health Endpoint Design

**Do:**
- ✅ Keep health checks fast (<100ms)
- ✅ Check critical dependencies (database, cache)
- ✅ Return appropriate status codes (200 = healthy, 500 = unhealthy)
- ✅ Include diagnostic info in response body
- ✅ Use lightweight queries (SELECT 1, not full table scan)
- ✅ Cache expensive checks (don't hit DB every request)

**Don't:**
- ❌ Run heavy computations in health check
- ❌ Return 200 when dependencies are down
- ❌ Require authentication for health endpoint (use dedicated endpoint)
- ❌ Check external APIs (slow and unreliable)

**Example good health endpoint:**
```python
@app.route('/health')
def health():
    checks = {
        'database': check_database(),      # Fast: SELECT 1
        'cache': check_redis(),            # Fast: PING
        'disk_space': check_disk_space()   # Fast: df command
    }

    healthy = all(checks.values())
    status_code = 200 if healthy else 500

    return {
        'status': 'healthy' if healthy else 'unhealthy',
        'checks': checks
    }, status_code
```

### Configuration Strategy

**Start conservative:**
```
Check Interval: 60s
Failure Threshold: 3
Success Threshold: 1
Auto-Restart: Disabled
```

**Monitor for 1 week:**
- Are there false positives? (Increase failure threshold)
- Are failures detected too slowly? (Decrease check interval)
- Is auto-restart needed? (Enable if manual intervention frequent)

**Adjust based on data:**
```
Check Interval: 30s (faster detection)
Failure Threshold: 2 (quicker response)
Auto-Restart: Enabled (reduce manual intervention)
```

### Multi-Container Health Checks

**Scenario:** Microservices architecture with 20 containers

**Strategy:**
1. **Tag containers by tier:**
   - `critical` - Must be healthy 24/7
   - `important` - Should be healthy during business hours
   - `standard` - Basic monitoring

2. **Configure by tier:**
   - **Critical:** 30s interval, threshold=2, auto-restart=yes
   - **Important:** 60s interval, threshold=3, auto-restart=yes
   - **Standard:** 300s interval, threshold=5, auto-restart=no

3. **Set up alerts:**
   - Critical tier → Pushover + Discord #oncall
   - Important tier → Discord #alerts
   - Standard tier → Email daily digest

### Testing Health Checks

**Before enabling in production:**

1. **Test manually:**
```bash
curl -v http://localhost:8080/health
```

2. **Verify status codes:**
```bash
# Should return 200 when healthy
curl -I http://localhost:8080/health | grep HTTP

# Should return 500 when unhealthy
# (Simulate by stopping database)
curl -I http://localhost:8080/health | grep HTTP
```

3. **Test with DockMon:**
- Configure health check
- Disable auto-restart
- Monitor for false positives
- Adjust thresholds if needed

4. **Enable auto-restart:**
- After confirming stability
- Monitor restart frequency
- Investigate if restarts >1 per day

---

## Troubleshooting

### Health Check Always Failing

**Symptom:** Health check immediately goes to unhealthy

**Common causes:**

#### Endpoint not reachable

**Check:**
```bash
# From DockMon container
docker exec dockmon curl http://container-name:8080/health
```

**Solutions:**
- Verify URL is correct
- Check container is running
- Verify port is exposed
- Check Docker network connectivity

#### SSL certificate issues

**Check logs:**
```bash
docker logs dockmon | grep "SSL verification"
```

**Solutions:**
- Disable SSL verification (temporary)
- Use proper certificate
- Import custom CA certificate

#### Authentication failing

**Check response:**
```bash
curl -v -H "Authorization: Bearer TOKEN" https://api.com/health
```

**Solutions:**
- Verify credentials are correct
- Check token expiration
- Verify authentication format (Basic vs Bearer)

### False Positives

**Symptom:** Health check marks container unhealthy but it's working fine

**Causes:**
- Endpoint is slow (exceeds timeout)
- Endpoint has transient errors
- Network latency spikes

**Solutions:**
- Increase timeout
- Increase failure threshold
- Improve endpoint performance
- Check network stability

### Health Check Not Running

**Symptom:** No health check events in Event Log

**Check:**
1. Is health check enabled for container?
2. Is DockMon backend running? `docker ps | grep dockmon`
3. Check DockMon logs: `docker logs dockmon | grep "health check"`

**Solutions:**
- Re-save health check configuration
- Restart DockMon container
- Check for errors in logs

### Auto-Restart Not Working

**Symptom:** Container marked unhealthy but doesn't restart

**Check:**
1. Is auto-restart enabled in health check config?
2. Is restart loop protection active? (Check logs)
3. Does container have permission issues?

**Logs:**
```bash
docker logs dockmon | grep "auto-restart"
```

**Solutions:**
- Verify auto-restart is enabled
- Check if restart loop protection triggered (wait 10 minutes)
- Verify DockMon has Docker socket access

---

## Related Documentation

- [Container Operations](Container-Operations) - Manual container restart
- [Alert Rules](Alert-Rules) - Configure health check alerts
- [Automatic Updates](Automatic-Updates) - Auto-update integration
- [Event Viewer](Event-Viewer) - View health check events

---

## Need Help?

- [Troubleshooting Guide](Troubleshooting)
- [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Report an Issue](https://github.com/darthnorse/dockmon/issues)
