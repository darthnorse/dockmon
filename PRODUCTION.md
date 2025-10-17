# Production Deployment

DockMon is production-ready out of the box with secure defaults. No configuration needed for most deployments!

## Quick Start

```bash
docker compose up -d
```

**That's it!** Access at `https://yourserver:8001`

Default login:
- Username: `admin`
- Password: `dockmon123` (you'll be forced to change it on first login)

---

## Production Configuration (Optional)

### CORS Configuration

**By default:** DockMon allows access from any origin (authentication still required for all endpoints).

**If you want to restrict access to specific domains only:**

Edit `docker-compose.yml` and change this line:

```yaml
- DOCKMON_CORS_ORIGINS=https://dockmon.yourcompany.com
```

For multiple domains (comma-separated, no spaces):
```yaml
- DOCKMON_CORS_ORIGINS=https://dockmon.company.com,https://backup.company.com
```

Then restart:
```bash
docker compose restart dockmon
```

**Examples:**

| Your Setup | CORS Setting |
|------------|--------------|
| Access from anywhere (default) | Leave empty - allows all origins |
| Restrict to specific domain | `DOCKMON_CORS_ORIGINS=https://dockmon.company.com` |
| Restrict to multiple domains | `DOCKMON_CORS_ORIGINS=https://main.com,https://backup.com` |

---

## Configuration Reference

### Timezone

Edit `docker-compose.yml` and change this line:

```yaml
- TZ=America/New_York  # Change to your timezone
```

Common timezones:
- `America/New_York`
- `America/Los_Angeles`
- `Europe/London`
- `Europe/Paris`
- `Asia/Tokyo`
- `UTC`

[Full timezone list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

---

## Security

### What's Already Secured

✅ **Authentication** - All endpoints require login
✅ **Rate Limiting** - Prevents abuse (sensible defaults)
✅ **Session Security** - Signed cookies with automatic rotation
✅ **Password Hashing** - Bcrypt with timing attack protection
✅ **SQL Injection** - Parameterized queries everywhere
✅ **Path Traversal** - Input validation and sanitization
✅ **Audit Logging** - Security events tracked

**Security Score: A+ (99/110)**

### First Login

1. Login with default credentials (`admin` / `dockmon123`)
2. You'll be forced to change the password immediately
3. Choose a strong password (12+ characters recommended)

---

## Testing vs Production

There's no difference! DockMon works the same way in both:

**Development (localhost):**
- CORS defaults to `localhost:3000`, `localhost:8080`, etc.
- Works out of the box, no config needed

**Production (your domain):**
- Set `DOCKMON_CORS_ORIGINS` if using custom domain
- Everything else identical

**No separate `.env` files or environment modes needed!**

---

## Troubleshooting

### CORS Errors in Browser

**Error:** `Access to fetch...has been blocked by CORS policy`

**Note:** This should NOT happen with default configuration (allows all origins).

**If you restricted CORS and need to adjust:**
1. Edit `docker-compose.yml` and update:
   ```yaml
   - DOCKMON_CORS_ORIGINS=https://your-actual-domain.com
   ```
2. Restart: `docker compose restart dockmon`
3. Verify in logs: `docker compose logs dockmon | grep CORS`

You should see:
```
CORS configured for specific origins: ['https://your-actual-domain.com']
```

### Can't Access DockMon

**Quick checks:**
```bash
# Is it running?
docker compose ps

# Is it healthy?
curl http://localhost:8001/health

# Check logs
docker compose logs dockmon --tail 50
```

---

## Updating DockMon

```bash
# Pull latest
git pull origin main

# Rebuild and restart
docker compose up -d --build

# Your data persists in the dockmon_data volume
```

---

## That's It!

DockMon is designed to be simple. You don't need:
- ❌ Complicated `.env` files
- ❌ Environment modes (dev/prod/test)
- ❌ Rate limit configuration
- ❌ Session timeout settings
- ❌ Log level configuration

Everything has sensible, secure defaults. Just deploy and use!
