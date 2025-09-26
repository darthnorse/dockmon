# 🚀 DockMon v1.0 - Production Deployment Guide

## 📋 Production Configuration Overview

**Good news!** The security improvements are designed to work seamlessly in production. Here's what's been configured and how to customize for your environment.

## 🌐 CORS Configuration (Production Ready)

### **Default Behavior - Works Out of the Box**
DockMon automatically detects common deployment scenarios:

```python
# Automatically allowed origins:
- http://localhost:8001      # Local development
- http://127.0.0.1:8001      # Alternative localhost
- http://localhost:80        # Production on same host
- http://127.0.0.1:80        # Alternative production
- http://[HOSTNAME]          # Auto-detected hostname
- https://[HOSTNAME]         # Auto-detected hostname (HTTPS)
```

### **Custom Domain Configuration**

#### **Method 1: Environment Variable (Recommended)**
```bash
export DOCKMON_CORS_ORIGINS="https://your-domain.com,https://dockmon.your-company.com,http://192.168.1.100"
```

#### **Method 2: Docker Compose**
```yaml
# docker-compose.yml
services:
  dockmon-backend:
    environment:
      - DOCKMON_CORS_ORIGINS=https://your-domain.com,https://dockmon.your-company.com
```

#### **Method 3: Docker Run**
```bash
docker run -e DOCKMON_CORS_ORIGINS="https://your-domain.com" \
  -p 8080:8080 dockmon-backend
```

### **Production Examples**

```bash
# Single domain
DOCKMON_CORS_ORIGINS="https://dockmon.mycompany.com"

# Multiple domains
DOCKMON_CORS_ORIGINS="https://dockmon.mycompany.com,https://monitoring.mycompany.com,http://internal-server:8001"

# Mixed HTTP/HTTPS with IP addresses
DOCKMON_CORS_ORIGINS="https://dockmon.example.com,http://192.168.1.50:8001,https://10.0.0.100"
```

## 🛡️ Docker Host Security (Private Networks Allowed)

### **What's Allowed in Production**

✅ **Legitimate Docker Hosts (All Allowed):**
- `tcp://192.168.1.100:2376` - Private network hosts
- `tcp://10.0.1.50:2376` - Enterprise private networks
- `tcp://172.16.0.10:2376` - Docker Swarm networks
- `tcp://localhost:2376` - Local Docker daemon
- `unix:///var/run/docker.sock` - Local Unix socket
- `tcp://docker-host.company.com:2376` - Domain names

✅ **TLS/mTLS Endpoints:**
- `tcp://secure-docker:2376` with certificates
- `https://docker-api.internal:2376` - HTTPS endpoints

### **What's Blocked (Security)**

❌ **Dangerous Endpoints (Blocked):**
- `tcp://169.254.169.254:*` - AWS/GCP cloud metadata
- `tcp://metadata.google.internal:*` - Cloud metadata services
- `tcp://100.100.100.200:*` - Cloud provider internal services
- `tcp://0.0.0.0:*` - All interfaces binding
- Bare `localhost` without port (but `localhost:2376` is allowed)

### **Private Network Logging**

DockMon logs (but allows) private network usage for monitoring:

```
INFO: Docker host configured on private network: tcp://192.168.1.100:2376...
```

This helps administrators track what networks are being monitored.

## 🔧 Production Deployment Examples

### **1. Basic Production (Same Host)**
```yaml
# docker-compose.yml - Frontend and Backend on same server
version: '3.8'
services:
  dockmon-backend:
    build: ./backend
    ports:
      - "8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./backend/data:/app/data
    environment:
      # No CORS override needed - auto-detects localhost:80

  dockmon-frontend:
    build: ./docker
    ports:
      - "80:80"  # Production on port 80
    depends_on:
      - dockmon-backend
```

### **2. Custom Domain Deployment**
```yaml
services:
  dockmon-backend:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      - DOCKMON_CORS_ORIGINS=https://dockmon.mycompany.com,https://monitoring.internal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./backend/data:/app/data

  dockmon-frontend:
    build: ./docker
    ports:
      - "80:80"
```

### **3. Reverse Proxy (Nginx/Traefik)**
```yaml
# With reverse proxy, set CORS to match your proxy domain
services:
  dockmon-backend:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      - DOCKMON_CORS_ORIGINS=https://dockmon.example.com
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

  nginx:
    image: nginx
    ports:
      - "443:443"
    # ... SSL and reverse proxy config
```

### **4. Multi-Host Monitoring Setup**
```yaml
# On monitoring server
services:
  dockmon-backend:
    environment:
      - DOCKMON_CORS_ORIGINS=https://monitoring.company.com
    ports:
      - "8080:8080"
    # No local Docker socket - monitors remote hosts only
```

**Remote Docker Hosts Configuration:**
- `tcp://web-server-1:2376` (Private network ✅)
- `tcp://192.168.1.10:2376` (Private network ✅)
- `tcp://10.0.0.50:2376` (Enterprise network ✅)

## 🔒 Security Features Summary

### **What's Still Secure**

1. **API Key Authentication** - Required for all endpoints
2. **Rate Limiting** - Prevents abuse and DoS attacks
3. **Input Validation** - Blocks XSS, injection, malicious patterns
4. **SSRF Protection** - Blocks cloud metadata, dangerous internal services
5. **Comprehensive Logging** - All security events logged to `logs/security_audit.log`
6. **CORS Protection** - Only allowed origins can access the API

### **What's Production-Friendly**

1. **Private Networks Allowed** - Monitor Docker hosts on `192.168.*`, `10.*`, `172.16-31.*`
2. **Flexible CORS** - Environment-based configuration for any domain
3. **Auto-Detection** - Works out-of-the-box in most scenarios
4. **Logging** - Clear visibility into what's being accessed
5. **No Functionality Loss** - All monitoring features preserved

## 🚨 Common Production Issues & Solutions

### **Issue: "CORS policy: No 'Access-Control-Allow-Origin' header"**

**Solution:** Set CORS origins for your domain:
```bash
export DOCKMON_CORS_ORIGINS="https://your-actual-domain.com"
```

### **Issue: "URL targets potentially dangerous internal network"**

**Solution:** This should only appear for cloud metadata IPs. If you see this for legitimate Docker hosts, please check the IP is not in the blocked ranges:
- ✅ `192.168.1.100` - Should work
- ❌ `169.254.169.254` - Correctly blocked (AWS metadata)

### **Issue: Rate limiting in production**

**Solution:** Rate limits are now production-friendly (doubled from original):

| Endpoint Type | Requests/Min | Burst Limit | Usage Scenario |
|---------------|--------------|-------------|----------------|
| **Default** | 120/min | 20 burst | General API calls, settings |
| **Auth** | 60/min | 15 burst | Authentication requests |
| **Hosts** | 60/min | 15 burst | Docker host management |
| **Containers** | 200/min | 40 burst | Container operations |
| **Notifications** | 30/min | 10 burst | Alert testing, webhooks |

**Custom Rate Limits:** Set via environment variables:
```bash
export DOCKMON_RATE_LIMIT_DEFAULT=300        # 300/min instead of 120/min
export DOCKMON_RATE_LIMIT_CONTAINERS=500     # 500/min instead of 200/min
export DOCKMON_RATE_LIMIT_AUTH=100           # 100/min instead of 60/min
```

Monitor via: `GET /api/rate-limit/stats`

## 📊 Production Monitoring

### **Security Audit Logs**
```bash
# View security events
docker exec dockmon-backend cat logs/security_audit.log

# Monitor authentication
grep "AUTH_" logs/security_audit.log

# Check rate limit violations
grep "RATE_LIMIT" logs/security_audit.log
```

### **Health Checks**
- Backend health: `http://your-domain:8080/`
- Rate limit status: `http://your-domain:8080/api/rate-limit/stats`
- Security audit: `http://your-domain:8080/api/security/audit`

## ✅ Pre-Production Checklist

- [ ] Set `DOCKMON_CORS_ORIGINS` for your domain(s)
- [ ] Test Docker host connections from production server
- [ ] Verify TLS certificates for remote Docker hosts (if using mTLS)
- [ ] Configure log rotation for `logs/security_audit.log`
- [ ] Set up monitoring for security events
- [ ] Test authentication with production domains
- [ ] Backup API key (stored in database)

## 🎯 Summary

**DockMon v1.0 is production-ready!** The security improvements:

✅ **Work out-of-the-box** for most deployments
✅ **Allow legitimate private networks** for Docker monitoring
✅ **Block only dangerous cloud metadata** services
✅ **Provide flexible CORS configuration** via environment variables
✅ **Maintain all monitoring functionality** while adding security

The configuration automatically adapts to your deployment environment while maintaining strong security against actual threats.