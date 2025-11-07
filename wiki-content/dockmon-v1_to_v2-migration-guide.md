# DockMon v2 Migration Guide

This guide covers the necessary steps to migrate from DockMon v1.x to v2.0.0.

## What's Preserved

Your upgrade to v2 automatically preserves:
- ✅ All configured Docker hosts (local and remote)
- ✅ Container discovery and monitoring
- ✅ Event history
- ✅ User accounts and authentication settings

## What Requires Manual Migration

Due to architectural improvements in v2, the following require manual action:

---

## 1. Alert Rules Migration

### Why Migration is Required

DockMon v2 introduces a completely redesigned alert system with:
- More flexible rule conditions
- Better alert deduplication
- Improved notification management
- Enhanced alert history tracking

Due to these significant changes, **alert rules from v1 cannot be automatically migrated** and must be recreated.

### Migration Steps

1. **Document Your Existing Alert Rules** (if you haven't already)
   - Before upgrading, note down your v1 alert configurations
   - Include: alert types, conditions, notification channels, and recipients

2. **Access the New Alerts Interface**
   - Navigate to **Settings → Alerts** in DockMon v2
   - You'll see the new alert rule creation interface

3. **Recreate Each Alert Rule**
   - Click **"Create Alert Rule"**
   - Configure the alert conditions using the new rule builder:
     - **Event Type:** Container stopped, update available, health check failed, etc.
     - **Scope:** Apply to all containers, specific containers, or tagged containers
     - **Conditions:** Set thresholds and filters as needed
   - Configure notifications:
     - Enable Pushover integration if needed
     - Set notification preferences (immediate, digest, etc.)

4. **Test Your New Alert Rules**
   - Use the alert preview feature to verify rules will trigger correctly
   - Consider testing with a non-critical container first

### Example Alert Rule Recreation

**v1 Alert:** "Notify when any container stops"

**v2 Equivalent:**
- Event Type: `Container State Changed`
- Condition: `New State = Stopped`
- Scope: `All Containers`
- Notification: `Pushover (Immediate)`

---

## 2. mTLS Certificate Regeneration (Remote Docker Hosts)

### Why Regeneration is Required

DockMon v2 is built on **Alpine Linux 3.20** with **OpenSSL 3.x**, which has stricter certificate validation requirements than v1's OpenSSL 1.x:

- Stronger security standards for certificate chains
- More rigorous validation of certificate extensions
- Enhanced encryption requirements

Certificates generated with the old script may not meet these stricter requirements, causing connection failures.

### Who Needs This

**You need to regenerate certificates if:**
- ✅ You have remote Docker hosts configured with mTLS/TLS authentication
- ✅ DockMon shows connection errors to remote hosts after upgrading

**You can skip this if:**
- ❌ You only monitor local Docker (no remote hosts)
- ❌ Your remote hosts use IP whitelisting instead of mTLS

### Migration Steps

#### Prerequisites
- SSH or console access to each remote Docker host
- Root or sudo privileges on the remote host
- DockMon v2 already upgraded and running

#### Step 1: Download the Updated Certificate Generation Script

On **each remote Docker host**, run:

```bash
curl -O https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/setup-docker-mtls.sh
```

#### Step 2: Make the Script Executable

```bash
chmod +x setup-docker-mtls.sh
```

#### Step 3: Run the Certificate Generation Script

```bash
sudo ./setup-docker-mtls.sh
```

The script will:
- Generate new CA, server, and client certificates
- Configure Docker daemon to use the new certificates
- Display the certificate contents for copying

**Important:** Take note of the three certificate outputs:
- `ca.pem` (Certificate Authority)
- `cert.pem` (Client Certificate)
- `key.pem` (Client Key)

#### Step 4: Restart Docker on the Remote Host

```bash
sudo systemctl restart docker
```

**Verify Docker is running:**
```bash
sudo systemctl status docker
```

#### Step 5: Update Certificates in DockMon

1. Open DockMon v2 and navigate to **Settings → Docker Hosts**
2. Find your remote host in the list
3. Click **"Edit"** on the host
4. You'll see three certificate fields:
   - **CA Certificate** → Paste the contents of `ca.pem`
   - **Client Certificate** → Paste the contents of `cert.pem`
   - **Client Key** → Paste the contents of `key.pem`
5. Click **"Test Connection"** to verify
6. Click **"Save"** when the test succeeds

#### Step 6: Verify Connectivity

- Check that the host shows as "Connected" in the Hosts list
- Verify containers from that host appear in the dashboard
- Confirm metrics and stats are updating

### Troubleshooting mTLS Issues

**Connection still fails after regenerating certificates:**

1. **Verify Docker is listening on the correct port:**
   ```bash
   sudo netstat -tlnp | grep 2376
   ```
   Should show Docker listening on `0.0.0.0:2376`

2. **Check Docker daemon configuration:**
   ```bash
   cat /etc/docker/daemon.json
   ```
   Should contain:
   ```json
   {
     "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
     "tls": true,
     "tlsverify": true,
     "tlscacert": "/etc/docker/certs/ca.pem",
     "tlscert": "/etc/docker/certs/server-cert.pem",
     "tlskey": "/etc/docker/certs/server-key.pem"
   }
   ```

3. **Verify firewall allows port 2376:**
   ```bash
   sudo ufw status | grep 2376
   # or
   sudo iptables -L -n | grep 2376
   ```

4. **Check Docker logs for certificate errors:**
   ```bash
   sudo journalctl -u docker --since "5 minutes ago"
   ```

5. **Ensure certificate files have correct permissions:**
   ```bash
   ls -la /etc/docker/certs/
   ```
   Certificates should be owned by root with permissions `600` or `644`

**Certificate validation errors in DockMon logs:**
- Double-check you copied the complete certificate contents (including `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----` lines)
- Ensure no extra whitespace or line breaks were added
- Verify the certificates match (client cert must be signed by the same CA)

---

## Post-Migration Checklist

After completing the migration steps:

- [ ] All alert rules have been recreated and tested
- [ ] All remote Docker hosts show as "Connected"
- [ ] Containers from all hosts are visible in the dashboard
- [ ] Metrics and stats are updating for all containers
- [ ] Test an alert trigger to confirm notifications work
- [ ] Review the new v2 features (tags, bulk operations, health checks)

---

## Getting Help

If you encounter issues during migration:

1. **Check the logs:**
   ```bash
   docker logs dockmon --tail 100
   ```

2. **Review DockMon documentation:**
   - Wiki: Available in the DockMon UI under Help
   - GitHub Issues: https://github.com/darthnorse/dockmon/issues

3. **Common Issues:**
   - Connection timeouts → Check firewall rules and Docker daemon configuration
   - Certificate errors → Ensure certificates were copied completely without modifications
   - Alert rules not triggering → Verify event type and scope match your containers

---

## What's New in v2

Now that you've completed the migration, explore these new features:

- **Customizable Dashboard** - Drag-and-drop widgets, custom layouts
- **Container Tags** - Organize containers with custom tags
- **Bulk Operations** - Start/stop/restart multiple containers at once
- **Automatic Updates** - Schedule container updates with validation policies
- **HTTP/HTTPS Health Checks** - Monitor endpoints with auto-restart on failure
- **Enhanced Metrics** - Better performance visualization with sparklines
- **Modern UI** - Completely rebuilt React-based interface
- **Improved Security** - Alpine Linux base, OpenSSL 3.x, enhanced authentication

---

**Thank you for upgrading to DockMon v2!** We appreciate your patience with the migration process. These breaking changes enable a more secure, scalable, and feature-rich platform.
