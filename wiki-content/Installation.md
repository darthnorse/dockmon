# Installation Guide

DockMon v2 can be installed on any system that supports Docker. Choose your installation method below.

> **Note:** DockMon v2 features a complete rewrite with React, TypeScript, and Alpine Linux. If you're upgrading from v1, see the [Migration Guide](Migration-Guide) for important information about breaking changes.

## Table of Contents

- [Docker Compose (Recommended)](#docker-compose-recommended) - Tested
- [Docker Run](#docker-run) - Tested
- [unRAID](#unraid) - Tested
- [Synology NAS](#synology-nas) - ⚠️ Untested
- [QNAP NAS](#qnap-nas) - ⚠️ Untested
- [Proxmox LXC](#proxmox-lxc-coming-soon) - Coming Soon
- [Building from Source](#building-from-source) - Tested

---

## Docker Compose (Recommended)

The easiest way to install DockMon.

### Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- 2GB RAM minimum
- Port 8001 available

### Installation Steps

1. **Create a docker-compose.yml file:**

```yaml
services:
  dockmon:
    image: darthnorse/dockmon:latest
    container_name: dockmon
    restart: unless-stopped
    ports:
      - "8001:443"
    environment:
      - TZ=America/New_York
    volumes:
      - dockmon_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock
    healthcheck:
      test: ["CMD", "curl", "-k", "-f", "https://localhost:443/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  dockmon_data:
```

2. **Start DockMon:**

```bash
docker compose up -d
```

3. **Access DockMon:**

Open `https://localhost:8001` and login with `admin` / `dockmon123`

### Configuration

Customize the compose file before starting:
- Change `TZ` to your timezone (e.g., `America/New_York`)
- Change port `8001` to your preferred port
- Add additional environment variables as needed

---

## Docker Run

Install DockMon with a single `docker run` command.

### Prerequisites

- Docker Engine 20.10+
- 2GB RAM minimum
- Port 8001 available

### Installation

```bash
docker run -d \
  --name=dockmon \
  --restart unless-stopped \
  -p 8001:443 \
  -v dockmon_data:/app/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e TZ=America/New_York \
  darthnorse/dockmon:latest
```

### Access

Open `https://localhost:8001` and login with `admin` / `dockmon123`

---

## unRAID

Install DockMon on unRAID servers.

### Method 1: Community Applications (Coming Soon)

DockMon will be available in Community Applications soon!

### Method 2: Manual Docker Run

1. **SSH into unRAID**

2. **Run DockMon:**
   ```bash
   docker run -d \
     --name=dockmon \
     --restart unless-stopped \
     -p 8001:443 \
     -v /mnt/user/appdata/dockmon:/app/data \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -e TZ=America/New_York \
     darthnorse/dockmon:latest
   ```

### Access

Open `https://[unraid-ip]:8001`

### Monitoring Remote Docker Hosts from unRAID

See [Remote Docker Setup](Remote-Docker-Setup) for configuring mTLS to monitor Docker on remote servers.

---

## Synology NAS

⚠️ **UNTESTED - Proceed with caution!** These instructions are provided based on general Synology knowledge but have not been tested. Please report success or issues in [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions).

Install DockMon on Synology DSM 7.0+.

### Prerequisites

- DSM 7.0 or newer
- Docker package installed (from Package Center)
- 2GB RAM minimum

### Installation via Docker UI

1. **Download DockMon Image**
   - Open Docker app in DSM
   - Go to Registry → Search for "darthnorse/dockmon"
   - Download the `latest` tag

2. **Create Container**
   - Image: `darthnorse/dockmon:latest`
   - Container Name: `dockmon`
   - Enable auto-restart

3. **Port Settings**
   - Local Port: `8001`
   - Container Port: `443`
   - Type: TCP

4. **Volume Settings**
   - Add folder: `/docker/dockmon` → `/app/data`
   - Add file: `/var/run/docker.sock` → `/var/run/docker.sock`

5. **Environment Variables**
   - `TZ` = Your timezone (e.g., `America/New_York`)

6. **Start Container**

### Installation via SSH

```bash
# SSH into Synology as admin
ssh admin@synology-ip

# Switch to root (if needed)
sudo -i

# Create data directory
mkdir -p /volume1/docker/dockmon

# Run container
docker run -d \
  --name=dockmon \
  --restart unless-stopped \
  -p 8001:443 \
  -v /volume1/docker/dockmon:/app/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e TZ=America/New_York \
  darthnorse/dockmon:latest
```

### Access

Open `https://[synology-ip]:8001`

---

## QNAP NAS

⚠️ **UNTESTED - Proceed with caution!** These instructions are provided based on general QNAP knowledge but have not been tested. Please report success or issues in [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions).

Install DockMon on QNAP Container Station.

### Prerequisites

- QTS 4.5+ or QuTS hero
- Container Station installed
- 2GB RAM minimum

### Installation via Container Station

1. **Open Container Station**

2. **Create Container**
   - Click "Create" → "Create Application"

3. **Pull Image**
   - Search for `darthnorse/dockmon`
   - Select `latest` tag

4. **Configure Container**
   - Name: `dockmon`
   - CPU/RAM: Allocate at least 2GB RAM
   - Auto-start: Enabled
   - Port: Host `8001` → Container `443`
   - Volumes:
     - `/share/Container/dockmon` → `/app/data`
     - `/var/run/docker.sock` → `/var/run/docker.sock`
   - Environment:
     - `TZ=America/New_York`

5. **Start Container**

### Installation via SSH

```bash
# SSH into QNAP
ssh admin@qnap-ip

# Create directory
mkdir -p /share/Container/dockmon

# Run container
docker run -d \
  --name=dockmon \
  --restart unless-stopped \
  -p 8001:443 \
  -v /share/Container/dockmon:/app/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e TZ=America/New_York \
  darthnorse/dockmon:latest
```

### Access

Open `https://[qnap-ip]:8001`

---

## Proxmox LXC (Coming Soon)

Automated LXC container installation script is coming in a future release!

For now, you can install DockMon in a Proxmox LXC container by:
1. Creating an Ubuntu 22.04 or Alpine Linux LXC container
2. Installing Docker inside the LXC
3. Following the [Docker Compose](#docker-compose-recommended) instructions

---

## Building from Source

Build DockMon from source code.

### Prerequisites

- Docker Engine 20.10+
- Git
- 2GB RAM minimum

### Build Steps

1. **Clone repository:**
   ```bash
   git clone https://github.com/darthnorse/dockmon.git
   cd dockmon
   ```

2. **Build image:**
   ```bash
   docker build -f docker/Dockerfile -t dockmon:latest .
   ```

3. **Run container:**
   ```bash
   docker compose up -d
   ```

   Or manually:
   ```bash
   docker run -d \
     --name=dockmon \
     --restart unless-stopped \
     -p 8001:443 \
     -v dockmon_data:/app/data \
     -v /var/run/docker.sock:/var/run/docker.sock \
     dockmon:latest
   ```

---

## Post-Installation

After installation on any platform:

1. **Access DockMon:** `https://[your-ip]:8001`
2. **Accept SSL Warning:** Self-signed certificate is expected
3. **Login:** `admin` / `dockmon123`
4. **Change Password:** Required on first login
5. **Verify Local Docker:** Should be automatically configured

### Next Steps

- [First Time Setup](First-Time-Setup) - Complete initial configuration
- [Managing Hosts](Managing-Hosts) - Add remote Docker hosts
- [Notifications](Notifications) - Configure alerts

---

## Upgrading DockMon

To upgrade to the latest version:

```bash
docker compose pull
docker compose down
docker compose up -d
```

Or if using `docker run`:

```bash
docker stop dockmon
docker rm dockmon
docker pull darthnorse/dockmon:latest
# Then run the docker run command again
```

Your data will be preserved in the `dockmon_data` volume.

---

## Uninstalling DockMon

To completely remove DockMon:

```bash
# Stop and remove container
docker compose down

# Remove volume (⚠️ deletes all data)
docker volume rm dockmon_data

# Remove image
docker rmi dockmon-dockmon

# Remove source code
cd .. && rm -rf dockmon
```

---

## Troubleshooting Installation

See [Troubleshooting](Troubleshooting) page for common installation issues and solutions.