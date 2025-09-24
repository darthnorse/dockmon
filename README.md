# 🐳 DockMon

A modern Docker container monitoring solution with auto-restart capabilities and multi-channel alerting.

![DockMon](https://img.shields.io/badge/DockMon-v1.0.0-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## 📸 Screenshots

### Dashboard Overview
![DockMon Dashboard](screenshots/dashboard.png)
*Real-time monitoring of multiple Docker hosts with container status and auto-restart controls*

### Container Management
![Container Management](screenshots/containers.png)
*Individual container controls with auto-restart toggles and state monitoring*

### Settings Panel
![Settings](screenshots/settings.png)
*Configure global auto-restart policies and monitoring intervals*

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

#### Automated Installation (Recommended)

Run this single command on your Proxmox host:

```bash
curl -sSL https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/dockmon-lxc.sh | bash
```

Or download and run the script:

```bash
wget https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/dockmon-lxc.sh
chmod +x dockmon-lxc.sh
./dockmon-lxc.sh
```

The script will:
- Let you choose between Debian 12 or 13
- Prompt for root password
- Select storage location
- Configure network settings
- Create and start the container
- Install DockMon automatically
- Set up the `update` command for easy updates

#### Keeping DockMon Updated

Once installed, simply SSH into your container and run:

```bash
update
```

This will update both Debian and DockMon to the latest versions.

#### Manual Installation (Alternative)

If you prefer to create the container manually:

1. Create an LXC container with Debian 12 or 13
2. Start the container and SSH into it
3. Run these commands:

```bash
# Update system
apt update && apt upgrade -y

# Install dependencies
apt install -y git nginx curl

# Clone and install DockMon
cd /opt
git clone https://github.com/darthnorse/dockmon.git
cp dockmon/src/index.html /var/www/html/index.html

# Start nginx
systemctl restart nginx
systemctl enable nginx
```

Access DockMon at: `http://<container-ip>`

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

## 🎯 Key Features in Detail

### Real-time Monitoring
- Live container status updates
- Multi-host support with connection status
- Container state visualization (running, stopped, paused)
- Quick stats overview with total hosts, containers, and active alerts

### Auto-Restart System
- Per-container auto-restart toggle
- Configurable retry attempts (0-10)
- Adjustable retry delays (5-300 seconds)
- Automatic disable after max attempts reached
- Visual feedback for restart attempts

### Alert Management
- Create custom alert rules per container
- Monitor specific state transitions
- Multiple notification channels per rule
- Support for Telegram, Discord, and Pushover

### Modern Interface
- Dark theme optimized for extended viewing
- Responsive design works on all devices
- Intuitive sidebar navigation
- Smooth animations and transitions
- Clean, organized layout inspired by Portainer

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
├── scripts/
│   ├── dockmon-lxc.sh   # Automated Proxmox LXC deployment
│   └── update.sh        # Update script for LXC containers
├── screenshots/         # Application screenshots
│   ├── dashboard.png
│   ├── containers.png
│   └── settings.png
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

### Running Locally

```bash
# Option 1: Open directly
open src/index.html

# Option 2: Use Python's simple HTTP server
python3 -m http.server 8080 --directory src

# Option 3: Use Node's http-server (if installed)
npx http-server src -p 8080
```

## 🤝 Contributing

Contributions are welcome! Feel free to:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 🚧 Roadmap

- [ ] Backend API integration for actual Docker monitoring
- [ ] WebSocket support for real-time updates
- [ ] Database persistence for settings and history
- [ ] Docker Swarm support
- [ ] Kubernetes support
- [ ] Metrics and performance graphs
- [ ] Container log viewer
- [ ] Multi-user support with authentication
- [ ] Export/import configuration
- [ ] Mobile app

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details

## 🙏 Acknowledgments

- UI design inspired by [Portainer](https://www.portainer.io/)
- Built with vanilla HTML, CSS, and JavaScript
- No external dependencies

## 👤 Author

Created by [darthnorse](https://github.com/darthnorse)

## ⭐ Show Your Support

Give a ⭐️ if this project helped you!

---

**DockMon** - Keep your containers in check! 🐳