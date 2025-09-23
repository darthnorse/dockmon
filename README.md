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
Access DockMon at: http://localhost:8080
Or run directly with Docker:
bashdocker build -t dockmon -f docker/Dockerfile .
docker run -d -p 8080:80 --name dockmon dockmon
Option 2: Proxmox LXC Container Deployment
Step 1: Create LXC Container in Proxmox

In Proxmox VE, click on your node
Click "Create CT" button
General:

Node: Select your node
CT ID: (auto-assigned or choose one)
Hostname: dockmon
Password: Set a root password


Template:

Template: debian-12-standard or debian-13-standard


Disks:

Disk size: 4GB is plenty


CPU:

Cores: 1 (minimum)


Memory:

Memory: 512MB
Swap: 512MB


Network:

Bridge: vmbr0 (or your preferred bridge)
IPv4: DHCP or Static


DNS:

Use host settings or configure custom


Click "Finish" and wait for container creation

Step 2: Start and Access the Container

Select your new container → Click "Start"
Click "Console" or SSH into it:

bash   ssh root@<container-ip>
Step 3: Install DockMon
Inside the LXC container, run:
bash# Update system
apt update && apt upgrade -y

# Install git and nginx
apt install -y git nginx curl

# Clone DockMon
cd /opt
git clone https://github.com/darthnorse/dockmon.git
cd dockmon

# Copy application file
cp src/index.html /var/www/html/

# Configure nginx (optional - it works with defaults)
systemctl restart nginx
systemctl enable nginx
Step 4: Access DockMon
Open your browser and navigate to:
http://<lxc-container-ip>
Optional: Configure nginx for port 8080
If you want to use port 8080 instead of 80:
bash# Edit nginx config
nano /etc/nginx/sites-available/default

# Find the line "listen 80 default_server;" and change to:
# listen 8080 default_server;

# Restart nginx
systemctl restart nginx
Option 3: Direct Deployment (Any Linux Server)
For any Debian/Ubuntu based system:
bash# Install nginx
sudo apt update && sudo apt install -y nginx git

# Clone the repository
cd /opt
sudo git clone https://github.com/darthnorse/dockmon.git

# Copy the application
sudo cp dockmon/src/index.html /var/www/html/

# Restart nginx
sudo systemctl restart nginx
🔧 Configuration
Auto-Restart Settings

Max Retry Attempts: 0-10 attempts
Retry Delay: 5-300 seconds between attempts
Default Auto-Restart: Enable/disable for new containers

Alert Channels Setup

Telegram: Requires Bot Token and Chat ID
Discord: Requires Webhook URL
Pushover: Requires App Token and User Key

📊 Usage

Add Docker Hosts: Click "Add Host" and enter Docker host details
Configure Alerts: Set up notification channels in Settings
Create Alert Rules: Define which container state changes trigger notifications
Enable Auto-Restart: Toggle auto-restart per container
Monitor: View real-time container status across all hosts

🐳 Docker Hub
Coming soon:
bashdocker pull darthnorse/dockmon:latest
docker run -d -p 8080:80 darthnorse/dockmon:latest
📁 Project Structure
dockmon/
├── src/
│   └── index.html       # Complete application (single file)
├── docker/
│   ├── Dockerfile       # Docker container definition
│   └── nginx.conf       # Nginx configuration
├── docker-compose.yml   # Docker Compose configuration
├── LICENSE             # MIT License
└── README.md          # This file
🛠️ Development
The entire application is contained in a single HTML file (src/index.html) with embedded CSS and JavaScript. No build process required!
To modify:

Edit src/index.html
Test locally by opening in a browser
Commit and push changes

🤝 Contributing
Contributions are welcome! Feel free to:

Fork the repository
Create a feature branch (git checkout -b feature/AmazingFeature)
Commit changes (git commit -m 'Add some AmazingFeature')
Push to branch (git push origin feature/AmazingFeature)
Open a Pull Request

📝 License
MIT License - see LICENSE file for details
🙏 Acknowledgments

UI design inspired by Portainer
Built with vanilla HTML, CSS, and JavaScript
No external dependencies

👤 Author
Created by darthnorse

DockMon - Keep your containers in check! 🐳
