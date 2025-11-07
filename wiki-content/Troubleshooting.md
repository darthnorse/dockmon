# Troubleshooting

Common issues and their solutions.

## Table of Contents

- [Installation Issues](#installation-issues)
- [v2-Specific Issues](#v2-specific-issues)
- [Connection Problems](#connection-problems)
- [Authentication Issues](#authentication-issues)
- [Container Management](#container-management)
- [Notification Problems](#notification-problems)
- [Performance Issues](#performance-issues)
- [Docker Socket Issues](#docker-socket-issues)

---

## Installation Issues

### Container Shows as "Unhealthy"

**Symptoms:**
```bash
docker ps
# STATUS: Up 2 minutes (unhealthy)
```

**Solutions:**

1. **Wait 30-60 seconds** - health check takes time to pass

2. **Check health endpoint:**
   ```bash
   docker exec dockmon curl -f http://localhost:8080/health
   # Should return: {"status":"healthy","service":"dockmon-backend"}
   ```

3. **Check logs for errors:**
   ```bash
   docker logs dockmon --tail 50
   ```

4. **Restart container:**
   ```bash
   docker compose restart
   ```

### Can't Access https://localhost:8001

**Symptoms:**
- Browser shows "Connection refused"
- "This site can't be reached"

**Solutions:**

1. **Verify container is running:**
   ```bash
   docker ps | grep dockmon
   ```

2. **Check port binding:**
   ```bash
   docker ps | grep 8001
   # Should show: 0.0.0.0:8001->443/tcp
   ```

3. **Check if port 8001 is in use:**
   ```bash
   lsof -i :8001
   # or
   netstat -tuln | grep 8001
   ```

4. **Try accessing via IP:**
   ```
   https://127.0.0.1:8001
   ```

5. **Check firewall:**
   ```bash
   sudo ufw status
   ```

### Port Already in Use

**Symptoms:**
```
Error starting container: port 8001: bind: address already in use
```

**Solutions:**

1. **Find what's using the port:**
   ```bash
   sudo lsof -i :8001
   ```

2. **Stop the conflicting service** or **change DockMon port** in `docker-compose.yml`:
   ```yaml
   ports:
     - "8002:443"  # Use different port
   ```

---

## v2-Specific Issues

### Database Migration Failed After Upgrading from v1

**Symptoms:**
```
Error: Could not upgrade database schema
Migration from v1.1.3 to v2.0.0 failed
```

**Solutions:**

1. **Check migration logs:**
   ```bash
   docker logs dockmon | grep -i migration
   docker logs dockmon | grep -i alembic
   ```

2. **Verify database backup exists:**
   ```bash
   docker exec dockmon ls -la /app/data/backups/
   # Look for pre-v2-upgrade backup
   ```

3. **Restore from backup and retry:**
   ```bash
   docker compose down
   docker exec dockmon cp /app/data/backups/dockmon-pre-v2.db /app/data/dockmon.db
   docker compose up -d
   ```

4. **Manual migration (last resort):**
   ```bash
   docker exec dockmon python -m alembic upgrade head
   ```

### OpenSSL 3.x Certificate Validation Errors

**Symptoms:**
```
SSL: CERTIFICATE_VERIFY_FAILED (after upgrading to v2)
SSL certificate problem: unable to get local issuer certificate
```

**Cause:** DockMon v2 uses Alpine with OpenSSL 3.x, which has stricter certificate validation than v1.

**Solutions:**

1. **Regenerate certificates with proper SANs:**
   ```bash
   # On remote host
   ./setup-docker-mtls.sh --host myserver.local --ip 192.168.1.100
   ```

2. **Verify certificate has SANs:**
   ```bash
   openssl x509 -in server-cert.pem -noout -text | grep -A1 "Subject Alternative Name"
   # Should show: DNS:myserver.local, IP:192.168.1.100
   ```

3. **Update host certificates in DockMon:**
   - Go to Host Management
   - Edit affected host
   - Paste new CA, cert, and key
   - Test Connection

### Supervisor Process Issues

**Symptoms:**
```
supervisor: couldn't exec nginx
supervisor: process 'backend' failed to start
```

**Solutions:**

1. **Check supervisor status:**
   ```bash
   docker exec dockmon supervisorctl status
   ```

2. **Restart individual services:**
   ```bash
   docker exec dockmon supervisorctl restart backend
   docker exec dockmon supervisorctl restart nginx
   docker exec dockmon supervisorctl restart stats-service
   ```

3. **Check supervisor logs:**
   ```bash
   docker exec dockmon cat /var/log/supervisor/supervisord.log
   docker exec dockmon cat /var/log/supervisor/backend-stderr.log
   docker exec dockmon cat /var/log/supervisor/nginx-stderr.log
   ```

4. **Full restart:**
   ```bash
   docker compose restart
   ```

### Go Stats Service Not Running

**Symptoms:**
```
Container stats not updating
Health check failing on port 8081
```

**Solutions:**

1. **Check stats service status:**
   ```bash
   docker exec dockmon supervisorctl status stats-service
   ```

2. **Check stats service health:**
   ```bash
   docker exec dockmon curl -f http://localhost:8081/health
   ```

3. **View stats service logs:**
   ```bash
   docker logs dockmon | grep -i "stats-service"
   docker exec dockmon cat /var/log/supervisor/stats-service-stderr.log
   ```

4. **Restart stats service:**
   ```bash
   docker exec dockmon supervisorctl restart stats-service
   ```

### Alert Rules Not Working After v1→v2 Upgrade

**Symptoms:**
- Old alert rules don't fire
- Alert rules page shows empty

**Cause:** Alert system was completely rewritten in v2 with breaking changes.

**Solutions:**

1. **Recreate alert rules manually:**
   - Go to Alert Rules page
   - Click "Add Alert Rule"
   - Configure new rules with v2 system

2. **Export v1 alert data (if downgrading):**
   ```bash
   # Not directly supported - v2 schema is incompatible
   # Contact support if you need assistance migrating complex rules
   ```

**Note:** This is documented in the v2 migration guide. Old alert rules cannot be automatically migrated due to architectural changes.

---

## Connection Problems

### "Connection Refused" to Remote Host

**Symptoms:**
- Host shows "offline" status
- Error: `Connection refused on port 2376`

**Solutions:**

1. **Verify Docker is listening on remote host:**
   ```bash
   # On remote host
   ss -tlnp | grep docker
   # Should show: 0.0.0.0:2376
   ```

2. **Check firewall on remote host:**
   ```bash
   sudo ufw status
   sudo iptables -L | grep 2376
   ```

3. **Test connectivity from DockMon:**
   ```bash
   docker exec dockmon telnet [remote-ip] 2376
   ```

4. **Verify Docker daemon configuration:**
   ```bash
   # On remote host
   sudo journalctl -u docker | grep "API listen"
   ```

### "Certificate Verification Failed"

**Symptoms:**
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Solutions:**

1. **Verify you're using matching certificates**
   - CA, cert, and key must all match
   - Regenerating certs on remote host requires updating DockMon

2. **Check certificate hasn't expired:**
   ```bash
   openssl x509 -in cert.pem -noout -dates
   ```

3. **Verify hostname/IP matches certificate:**
   ```bash
   openssl x509 -in server-cert.pem -noout -text | grep -A1 "Subject Alternative Name"
   ```

4. **Regenerate certificates if needed:**
   - Follow [Remote Docker Setup](Remote-Docker-Setup) again

---

## Authentication Issues

### Forgot Password

**Solutions:**

Reset password via command line:

```bash
# Auto-generate new password
docker exec dockmon python /app/backend/reset_password.py admin

# Set specific password
docker exec dockmon python /app/backend/reset_password.py admin --password NewPass123

# Interactive mode
docker exec -it dockmon python /app/backend/reset_password.py admin --interactive
```

### "Invalid Credentials" But Password is Correct

**Symptoms:**
- Password definitely correct
- Still shows "Invalid credentials"

**Solutions:**

1. **Clear browser cache and cookies:**
   - Chrome: Ctrl+Shift+Delete
   - Firefox: Ctrl+Shift+Delete
   - Try incognito/private mode

2. **Check for rate limiting:**
   - Wait 15 minutes
   - Check logs: `docker logs dockmon | grep "rate limit"`

3. **Verify database isn't corrupted:**
   ```bash
   docker exec dockmon sqlite3 /app/data/dockmon.db "SELECT username FROM users;"
   ```

4. **Last resort - reset database:**
   ⚠️ **This deletes all configuration!**
   ```bash
   docker compose down
   docker volume rm dockmon_data
   docker compose up -d
   ```

### Session Expired / Keep Getting Logged Out

**Symptoms:**
- Logged out after a few minutes
- "Session expired" message

**Solutions:**

1. **Check system time synchronization:**
   ```bash
   timedatectl status
   # Ensure time is synced
   ```

2. **Check browser cookie settings:**
   - Allow cookies from localhost
   - Don't block third-party cookies (affects some browsers)

3. **Check if using multiple DockMon instances:**
   - Sessions don't sync between containers
   - Use only one instance or configure session sharing

---

## Container Management

### Container Won't Start

**Symptoms:**
- Click "Start" but container remains stopped
- No error message shown

**Solutions:**

1. **Check Docker logs on remote host:**
   ```bash
   docker logs [container-name]
   ```

2. **Try starting manually:**
   ```bash
   docker start [container-name]
   ```

3. **Check Docker daemon status:**
   ```bash
   systemctl status docker
   ```

4. **Verify container isn't in restart loop:**
   ```bash
   docker ps -a | grep [container-name]
   # Check "Status" column
   ```

### Auto-Restart Not Working

**Symptoms:**
- Container crashes but doesn't restart
- Auto-restart toggle is ON

**Solutions:**

1. **Check max retries not exceeded:**
   - Settings → Auto-Restart Settings
   - Default: 3 retries
   - After max retries, auto-restart disables automatically

2. **Check retry delay:**
   - Settings → Auto-Restart Settings
   - Default: 10 seconds between attempts

3. **Verify container state:**
   ```bash
   docker inspect [container-name] | grep State
   ```

4. **Check DockMon logs:**
   ```bash
   docker logs dockmon | grep "auto-restart"
   ```

### Container Logs Not Showing

**Symptoms:**
- Click "View Logs" but no logs appear
- Shows "No logs available"

**Solutions:**

1. **Verify container has logs:**
   ```bash
   docker logs [container-name]
   ```

2. **Check container logging driver:**
   ```bash
   docker inspect [container-name] | grep LogConfig -A5
   # Should show: "Type": "json-file"
   ```

3. **Try increasing log lines:**
   - Change `tail` parameter in URL
   - Default: 100 lines

4. **Check DockMon backend logs:**
   ```bash
   docker logs dockmon | grep "get.*logs"
   ```

---

## Notification Problems

### Test Notification Not Received

**Symptoms:**
- Click "Test" button
- No notification appears
- No error shown

**Solutions:**

### Discord:
1. **Verify webhook URL is correct**
2. **Check channel permissions** - bot needs "Send Messages"
3. **Test webhook manually:**
   ```bash
   curl -X POST [webhook-url] \
     -H "Content-Type: application/json" \
     -d '{"content":"Test from curl"}'
   ```

### Telegram:
1. **Verify bot token is correct**
2. **Verify chat ID is correct**
3. **Check bot is not blocked**
4. **For groups: verify bot is in the group**

### Pushover:
1. **Verify app token and user key**
2. **Check Pushover app is installed and logged in**
3. **Verify account is not expired**

### Slack:
1. **Verify webhook URL is correct**
2. **Check app is installed in workspace**
3. **Verify channel exists**

### Notifications Work But Alerts Don't Fire

**Symptoms:**
- Test notifications work
- Real alerts don't trigger

**Solutions:**

1. **Verify alert rule is enabled:**
   - Alert Rules page
   - Check "Enabled" toggle

2. **Check container matches alert rule:**
   - Verify host + container name pattern

3. **Check trigger conditions:**
   - Events: container_die, container_stop, etc.
   - States: exited, dead, paused, etc.

4. **Check cooldown period:**
   - Default: 15 minutes
   - Alert won't fire again until cooldown expires

5. **Check blackout window:**
   - Notifications → Quiet Hours
   - Alerts suppressed during blackout

---

## Performance Issues

### Dashboard Slow to Load

**Symptoms:**
- Dashboard takes 10+ seconds to load
- Browser feels sluggish

**Solutions:**

1. **Check number of containers:**
   - 100+ containers can slow down UI
   - Consider filtering or pagination

2. **Reduce polling interval:**
   - Settings → Polling Interval
   - Increase from 10s to 30s or 60s

3. **Check DockMon resource usage:**
   ```bash
   docker stats dockmon
   ```

4. **Check remote host latency:**
   ```bash
   ping [remote-host-ip]
   ```

### High CPU Usage

**Symptoms:**
```bash
docker stats dockmon
# CPU: 100%+
```

**Solutions:**

1. **Check number of monitored containers:**
   - Each container adds overhead
   - Consider removing unused hosts

2. **Increase polling interval:**
   - Settings → Polling Interval
   - Default: 10s → Try 30s or 60s

3. **Check for event loops:**
   ```bash
   docker logs dockmon | grep ERROR
   ```

4. **Restart DockMon:**
   ```bash
   docker compose restart
   ```

### WebSocket Connection Drops

**Symptoms:**
- Dashboard stops updating
- Manual refresh needed

**Solutions:**

1. **Check nginx timeout settings:**
   ```bash
   docker exec dockmon cat /etc/nginx/conf.d/default.conf | grep timeout
   ```

2. **Check reverse proxy (if using one):**
   - Increase WebSocket timeout
   - Example (nginx): `proxy_read_timeout 3600s;`

3. **Check network stability:**
   ```bash
   ping -c 100 [dockmon-ip]
   # Look for packet loss
   ```

---

## Docker Socket Issues

### Permission Denied on Docker Socket

**Symptoms:**
```
Permission denied while trying to connect to Docker daemon socket
```

**Solutions:**

1. **Verify socket is mounted:**
   ```bash
   docker inspect dockmon | grep docker.sock
   ```

2. **Check socket permissions on host:**
   ```bash
   ls -l /var/run/docker.sock
   # Should be writable by docker group
   ```

3. **Verify DockMon user has access:**
   ```bash
   docker exec dockmon ls -l /var/run/docker.sock
   ```

4. **Try adding user to docker group (host):**
   ```bash
   sudo usermod -aG docker $USER
   ```

### Docker Socket Not Found

**Symptoms:**
```
Local Docker host not showing containers
Error: docker.sock: no such file
```

**Solutions:**

1. **Verify Docker is installed on host:**
   ```bash
   docker --version
   ```

2. **Check socket location:**
   ```bash
   ls -l /var/run/docker.sock
   ```

3. **For rootless Docker:**
   - Socket is at `$XDG_RUNTIME_DIR/docker.sock`
   - Update docker-compose.yml volume mount

4. **For Docker Desktop (Mac):**
   - Socket is at `/var/run/docker.sock` (should work)
   - Try restarting Docker Desktop

---

## Getting More Help

### Enable Debug Logging

```bash
# Edit docker-compose.yml or docker-compose.override.yml
environment:
  - LOG_LEVEL=DEBUG

# Restart
docker compose restart

# View logs (all services)
docker logs -f dockmon

# View specific service logs (v2)
docker exec dockmon cat /var/log/supervisor/backend-stderr.log
docker exec dockmon cat /var/log/supervisor/nginx-stderr.log
docker exec dockmon cat /var/log/supervisor/stats-service-stderr.log
```

### Collect Diagnostic Information

```bash
# System info
docker --version
docker compose version
uname -a

# DockMon version
docker exec dockmon python -c "import sys; print(f'Python {sys.version}')"
docker exec dockmon cat /etc/alpine-release

# DockMon info
docker ps | grep dockmon
docker logs dockmon --tail 100

# Supervisor status (v2)
docker exec dockmon supervisorctl status

# Network info
ss -tlnp | grep -E '8001|8080|8081'

# Resource usage
docker stats dockmon --no-stream

# Service-specific logs (v2)
docker exec dockmon cat /var/log/supervisor/supervisord.log
docker exec dockmon cat /var/log/supervisor/backend-stderr.log
```

### Report an Issue

If none of these solutions work:

1. **Search existing issues:** https://github.com/darthnorse/dockmon/issues
2. **Create new issue** with:
   - DockMon version
   - Docker version
   - Operating system
   - Complete error message
   - Relevant logs
   - Steps to reproduce

---

## See Also

- [FAQ](FAQ) - Frequently asked questions
- [Installation](Installation) - Installation guides
- [Security Guide](Security-Guide) - Security troubleshooting