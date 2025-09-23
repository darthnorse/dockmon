# 🐳 DockMon

A modern Docker container monitoring solution with auto-restart capabilities and multi-channel alerting.

![DockMon](https://img.shields.io/badge/DockMon-v1.0.0-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## ✨ Features

- 📊 **Multi-host Docker monitoring** - Monitor containers across multiple Docker hosts
- 🔄 **Auto-restart capability** - Automatically restart failed containers with configurable retry logic  
- 🔔 **Multi-channel alerting** - Send alerts via Telegram, Discord, and Pushover
- 🎨 **Modern UI** - Clean, dark theme inspired by Portainer
- 🚀 **Lightweight** - Zero dependencies, pure HTML/CSS/JavaScript
- 📦 **Flexible deployment** - Run as Docker container or in LXC/VM

## 🚀 Quick Start

### Option 1: Docker Deployment

Clone and run with Docker Compose:

```bash
git clone https://github.com/darthnorse/dockmon.git
cd dockmon
docker-compose up -d
```

Access DockMon at: `http://localhost:8080`

Or run directly with Docker:

```bash
docker build -t dockmon -f docker/Dockerfile .
docker run -d -p 8080:80 --name dockmon dockmon
```

### Option 2: Proxmox LXC Container Deployment

#### Step 1: Create LXC Container in Proxmox

1. In Proxmox VE, click on your node
2. Click "Create CT" button
3. **General:**
   - Node: Select your node
   - CT ID: (auto-assigned or choose one)
   - Hostname: `dockmon`
   - Password: Set a root password
4. **Template:**
   - Template: `debian-12-standard` or `debian-13-standard`
5. **Disks:**
   - Disk size: 4GB is plenty
6. **CPU:**
   - Cores: 1 (minimum)
7. **Memory:**
   - Memory: 512MB
   - Swap: 512MB
8. **Network:**
   - Bridge: `vmbr0` (or your preferred bridge)
   - IPv4: DHCP or Static
9. **DNS:**
   - Use host settings or configure custom
10. Click "Finish" and wait for container creation

#### Step 2: Start and Access the Container

1. Select your new container → Click "Start"
2. Click "Console" or SSH into it:

```bash
ssh root@<container-ip>
```

#### Step 3: Install DockMon

Inside the LXC container, run:

```bash
# Update system
apt update && apt upgrade -y

# Install git and nginx
apt install -y git nginx curl

# Clone DockMon
cd /opt
git clone https://github.com/darthnorse/dockmon.git
cd dockmon

# Copy application file
cp src/index.html /var/www/html/index.html

# Configure nginx (optional - it works with defaults)
systemctl restart nginx
systemctl enable nginx
```

#### Step 4: Access DockMon

Open your browser and navigate to:

```
http://<lxc-container-ip>
```

#### Optional: Configure nginx for port 8080

If you want to use port 8080 instead of 80:

```bash
# Edit nginx config
nano /etc/nginx/sites-available/default

# Find the line "listen 80 default_server;" and change to:
# listen 8080 default_server;

# Restart nginx
systemctl restart nginx
```

### Option 3: Direct Deployment (Any Linux Server)

For any Debian/Ubuntu based system:

```bash
# Install nginx
sudo apt update && sudo apt install -y nginx git

# Clone the repository
cd /opt
sudo git clone https://github.com/darthnorse/dockmon.git

# Copy the application
sudo cp dockmon/src/index.html /var/www/html/index.html

# Restart nginx
sudo systemctl restart nginx
```

## 🔧 Configuration

### Auto-Restart Settings
- **Max Retry Attempts:** 0-10 attempts
- **Retry Delay:** 5-300 seconds between attempts
- **Default Auto-Restart:** Enable/disable for new containers

### Alert Channels Setup
1. **Telegram:** Requires Bot Token and Chat ID
2. **Discord:** Requires Webhook URL
3. **Pushover:** Requires App Token and User Key

## 📊 Usage

1. **Add Docker Hosts:** Click "Add Host" and enter Docker host details
2. **Configure Alerts:** Set up notification channels in Settings
3. **Create Alert Rules:** Define which container state changes trigger notifications
4. **Enable Auto-Restart:** Toggle auto-restart per container
5. **Monitor:** View real-time container status across all hosts

## 🐳 Docker Hub

Coming soon:

```bash
docker pull darthnorse/dockmon:latest
docker run -d -p 8080:80 darthnorse/dockmon:latest
```

## 📁 Project Structure

```
dockmon/
├── src/
│   └── index.html       # Complete application (single file)
├── docker/
│   ├── Dockerfile       # Docker container definition
│   └── nginx.conf       # Nginx configuration
├── docker-compose.yml   # Docker Compose configuration
├── LICENSE             # MIT License
└── README.md          # This file
```

## 🛠️ Development

The entire application is contained in a single HTML file (`src/index.html`) with embedded CSS and JavaScript. No build process required!

To modify:
1. Edit `src/index.html`
2. Test locally by opening in a browser
3. Commit and push changes

## 🤝 Contributing

Contributions are welcome! Feel free to:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details

## 🙏 Acknowledgments

- UI design inspired by [Portainer](https://www.portainer.io/)
- Built with vanilla HTML, CSS, and JavaScript
- No external dependencies

## 👤 Author

Created by [darthnorse](https://github.com/darthnorse)

---

**DockMon** - Keep your containers in check! 🐳