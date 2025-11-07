# Security Guide

DockMon security architecture, best practices, and threat model.

## Security Overview

DockMon v2 is designed as a **single-user system** with strong authentication and security features:

- Session-based authentication with secure cookies
- Bcrypt password hashing (12 rounds)
- HTTPS-only access (self-signed cert included)
- Rate limiting on all endpoints
- Security audit logging
- Backend bound to localhost (127.0.0.1)

### v2 Security Improvements

DockMon v2 introduces significant security enhancements:

**Base Image:**
- Alpine Linux 3.x (minimal attack surface)
- Python 3.13 (latest security patches)
- OpenSSL 3.x (stricter certificate validation)

**Architecture:**
- Multi-stage Docker build (reduced image size)
- Go-based stats service (memory-safe, high performance)
- Supervisor process management (proper signal handling)
- SQLAlchemy 2.0 with Alembic migrations (schema versioning)

## Authentication & Access Control

### Session-Based Authentication

**How it works:**
- Username/password login
- Server generates session ID
- Session ID stored in HTTPOnly, Secure, SameSite cookie
- Backend validates session on every request

**Security features:**
- No passwords in URLs or localStorage
- Session timeout after inactivity
- Secure cookie flags prevent XSS/CSRF
- Bcrypt password hashing with salt (12 rounds)

### Password Requirements

**Strong passwords required:**
- Minimum 8 characters (12+ recommended)
- Mix of uppercase and lowercase
- Include numbers
- Include special characters

**Password management:**
- Change password: Settings → Account
- Reset password: Command-line tool (see [First Time Setup](First-Time-Setup))
- Force password change on first login

### Rate Limiting

DockMon implements rate limiting to prevent abuse:

| Endpoint Type | Limit | Window |
|--------------|-------|--------|
| Authentication | 5 attempts | 15 minutes |
| Hosts API | 30 requests | 1 minute |
| Containers API | 60 requests | 1 minute |
| Notifications | 20 requests | 1 minute |
| WebSocket | 30 messages | 1 minute |

**What happens when limited:**
- HTTP 429 "Too Many Requests" response
- Automatic unlock after window expires
- All attempts logged in security audit

**View rate limit stats:**
Settings → Security Audit → Rate Limiting

---

## Docker Socket Access

### ⚠️ The Elephant in the Room

DockMon requires access to the Docker socket:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

**This provides root-equivalent access** to the host system. A compromised DockMon instance could:
- Start/stop any containers
- Mount host filesystem
- Escalate to host root access

### Why It's Required

**DockMon cannot function without Docker socket access.** This is not a design flaw - it's inherent to Docker container management:

- Monitor container status
- Start/stop/restart containers
- Read container logs
- Subscribe to Docker events

### Security Implications

**Risks:**
- ⚠️ Compromised DockMon = compromised host
- ⚠️ DockMon exposed to internet = extreme risk
- ⚠️ Weak password = easy compromise

**Mitigations:**
- Strong authentication (implemented)
- Backend localhost-only binding (implemented)
- Rate limiting (implemented)
- Security audit logging (implemented)
- **Do NOT expose to internet** (your responsibility)

---

## Network Security

### Deployment Model

```
Internet → [VPN/SSH Tunnel] → HTTPS (port 8001) → Nginx → Backend (127.0.0.1:8080)
```

**What's exposed:**
- Port 8001 (HTTPS) - Nginx frontend, authentication required
- Backend: NOT exposed (localhost-only)

### Backend Isolation

The FastAPI backend listens ONLY on `127.0.0.1:8080`:

```python
uvicorn.run(
    "main:app",
    host="127.0.0.1",  # Localhost only
    port=8080
)
```

**This means:**
- Backend not accessible from network
- Only Nginx (same container) can access backend
- Additional security layer

### TLS Certificate

DockMon includes a self-signed certificate that's auto-generated on first run using OpenSSL 3.x.

**For private use:** The self-signed cert is adequate and secure.

**For production:** Replace with proper TLS certificate:

```bash
# Option 1: Replace certificate files
docker cp your-cert.crt dockmon:/etc/nginx/certs/dockmon.crt
docker cp your-cert.key dockmon:/etc/nginx/certs/dockmon.key
docker exec dockmon supervisorctl restart nginx

# Option 2: Mount your certificates
# Edit docker-compose.yml:
volumes:
  - ./certs/your-cert.crt:/etc/nginx/certs/dockmon.crt:ro
  - ./certs/your-cert.key:/etc/nginx/certs/dockmon.key:ro
```

**For Let's Encrypt:** Use a reverse proxy (Caddy, Traefik) in front of DockMon.

**v2 Note:** Certificates are generated with OpenSSL 3.x, which produces certificates compatible with modern security standards.

---

## Remote Access

### ❌ Do NOT Expose Directly to Internet

**Never expose port 8001 to the internet directly!**

Even with authentication, exposing DockMon increases attack surface:
- Brute force attempts
- Credential stuffing
- Zero-day exploits
- DDoS attacks

### ✅ Use VPN for Remote Access

**Recommended approach:**

1. **WireGuard** (simplest, fastest)
   - Install WireGuard on server and client
   - Connect to VPN, then access DockMon at `https://[server-ip]:8001`

2. **OpenVPN** (mature, widely supported)
   - Install OpenVPN server
   - Connect to VPN, then access DockMon

3. **Tailscale** (zero-config mesh VPN)
   - Install Tailscale on server and client
   - Automatically creates private network
   - Access DockMon at `https://[tailscale-ip]:8001`

### Alternative: SSH Tunnel

**For quick remote access:**

```bash
# From your local machine
ssh -L 8001:localhost:8001 user@server

# Access at https://localhost:8001
```

This tunnels traffic through SSH, avoiding exposing the port.

---

## Security Audit Logging

DockMon logs security-critical events.

### What Gets Logged

- Login attempts (success and failure)
- Password changes
- Host additions/removals
- Privileged actions
- Rate limit violations
- Configuration changes

### View Audit Logs

1. Go to Settings → Security Audit
2. Review recent events
3. Export logs if needed

### Log Format

```json
{
  "timestamp": "2025-09-29T14:23:45Z",
  "client_ip": "192.168.1.100",
  "action": "LOGIN_SUCCESS",
  "user": "admin",
  "user_agent": "Mozilla/5.0...",
  "success": true
}
```

---

## File Permissions

DockMon v2 sets secure file permissions automatically:

| File/Directory | Permissions | Owner |
|----------------|-------------|-------|
| Database (`dockmon.db`) | 600 | app user |
| TLS certificates (private keys) | 600 | app user |
| TLS certificates (public certs) | 644 | app user |
| Data directory | 700 | app user |
| Nginx config | 644 | root |

**v2 Note:** The Alpine-based container runs with minimal privileges, and all sensitive files are protected with strict permissions set during startup.

---

## Database Security

### SQLite Database

**Location:** `/app/data/dockmon.db`

**Security features:**
- File permissions: 600 (owner read/write only)
- SQLAlchemy ORM (prevents SQL injection)
- Parameterized queries
- No raw SQL from user input

**Sensitive data stored:**
- User passwords (bcrypt hashed)
- TLS certificates for remote hosts
- Session tokens
- Notification webhooks

### Backup Security

**When backing up:**
```bash
docker cp dockmon:/app/data/dockmon.db ./backup/dockmon.db
chmod 600 ./backup/dockmon.db
```

**Important:**
- Backup contains TLS certificates
- Backup contains notification webhooks
- Store backups securely (encrypted if possible)

---

## Input Validation & Sanitization

### Path Traversal Protection

Host IDs are sanitized to prevent path traversal:

```python
def sanitize_host_id(host_id: str) -> str:
    """Prevent path traversal attacks"""
    if ".." in host_id or "/" in host_id or "\\" in host_id:
        raise ValueError(f"Invalid host ID: {host_id}")
    # Must be valid UUID or alphanumeric
    return host_id
```

This prevents attacks like:
- `../../etc/passwd`
- `../../../root/.ssh/id_rsa`

### SQL Injection Protection

DockMon uses SQLAlchemy ORM with parameterized queries:

```python
# Safe - parameterized
session.query(Host).filter(Host.id == host_id).first()

# Never done - raw SQL
# session.execute(f"SELECT * FROM hosts WHERE id = '{host_id}'")  # NEVER!
```

### XSS Protection

- Frontend sanitizes all user input
- HTTPOnly cookies prevent XSS cookie theft
- Content-Type headers properly set

---

## Security Best Practices

### Required (Do These!)

- **Change default password** immediately after first login
- **Use strong passwords** (12+ characters, mixed case, numbers, symbols)
- **Do NOT expose to internet** - use VPN for remote access
- **Keep DockMon updated** - pull latest version regularly

### Recommended

- **Run on dedicated management network** - separate from production
- **Use firewall rules** - restrict port 8001 to specific IPs
- **Review audit logs regularly** - check for suspicious activity
- **Backup database securely** - encrypt backups
- **Use TLS for remote Docker** - never insecure TCP
- **Monitor rate limiting stats** - detect brute force attempts

### Nice to Have

- **Reverse proxy with additional auth** - Caddy/Traefik with basic auth
- **Network segmentation** - isolate DockMon on dedicated VLAN
- **Docker socket proxy** - use tecnativa/docker-socket-proxy for defense-in-depth

---

## Docker Socket Proxy (Optional)

For defense-in-depth, use a Docker socket proxy:

**Benefits:**
- Only proxy has direct socket access
- Restricts Docker API operations
- Additional security layer if DockMon compromised

**Example configuration:**

```yaml
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy
    environment:
      - CONTAINERS=1
      - INFO=1
      - NETWORKS=1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    restart: unless-stopped

  dockmon:
    image: dockmon:latest
    environment:
      - DOCKER_HOST=tcp://docker-proxy:2375
    depends_on:
      - docker-proxy
    # Remove socket mount
    ports:
      - "8001:443"
```

**Trade-offs:**
- Better security
- Additional complexity
- Slightly higher latency

---

## Threat Model

### DockMon Is Designed For

- Single-user, self-hosted deployments
- Private networks (home lab, office)
- Trusted environments with physical security

### DockMon Is NOT Designed For

- Multi-tenant SaaS deployments
- Public internet exposure
- Untrusted network environments
- High-security/compliance-required environments

### Risk Assessment

**Low Risk (Typical Home Lab):**
- Single user
- Private network
- Strong authentication
- Localhost-only backend
- VPN for remote access

**Medium Risk (Small Office):**
- Multiple users (single shared account)
- Internal network exposure
- Strong authentication required
- Audit logging enabled

**High Risk (Internet Exposure):**
- ⚠️ **DO NOT DO THIS**
- If you must: Reverse proxy + additional auth + VPN

---

## What DockMon Does to Protect You

- **Backend isolation** - API only accessible via Nginx
- **Authentication required** - All endpoints except health check
- **Rate limiting** - Prevents brute force and abuse
- **Security auditing** - Logs all privileged actions
- **Path traversal protection** - Sanitizes all file paths
- **SQL injection protection** - Parameterized queries
- **Secure file permissions** - Database (600), certs (600)
- **Session security** - HTTPOnly, Secure, SameSite cookies
- **Password security** - Bcrypt hashing with salt

---

## Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)

---

## Next Steps

- [Remote Docker Setup](Remote-Docker-Setup) - Secure remote host configuration
- [First Time Setup](First-Time-Setup) - Initial security configuration
- [Troubleshooting](Troubleshooting) - Security-related issues