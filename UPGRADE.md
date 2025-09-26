# DockMon Upgrade Guide

## Data Persistence & Upgrades

DockMon stores all configuration data (hosts, alert rules, notification settings, user accounts) in a SQLite database. This guide ensures your data survives upgrades.

## Method 1: Recommended Production Setup

### Initial Installation
```bash
# Create data directory on host
mkdir -p ./dockmon-data

# Use production compose file
docker compose -f docker-compose.prod.yml up -d
```

### Upgrading to New Version
```bash
# Stop container
docker compose -f docker-compose.prod.yml stop

# Pull new image
docker pull dockmon:latest  # Or build new version

# Start with new image
docker compose -f docker-compose.prod.yml up -d
```

Your data in `./dockmon-data/` directory is preserved across upgrades.

## Method 2: Named Volume Backup

### Before Upgrading
```bash
# Backup database
docker exec dockmon cp /app/data/dockmon.db /tmp/backup.db
docker cp dockmon:/tmp/backup.db ./dockmon-backup-$(date +%Y%m%d).db

# Stop and remove container
docker compose down
```

### After Upgrade
```bash
# Start new version
docker compose up -d

# Restore if needed
docker cp ./dockmon-backup-YYYYMMDD.db dockmon:/app/data/dockmon.db
docker compose restart
```

## Method 3: Volume Migration

### Export Data
```bash
# Create backup directory
mkdir -p ./dockmon-data-backup

# Copy data from named volume
docker run --rm -v dockmon_dockmon_data:/source -v $(pwd)/dockmon-data-backup:/backup alpine cp -r /source/. /backup/
```

### Switch to Bind Mount
```bash
# Update docker-compose.yml to use bind mount
# volumes:
#   - ./dockmon-data:/app/data

# Start with preserved data
mv dockmon-data-backup dockmon-data
docker compose up -d
```

## Troubleshooting

### Lost Data After Upgrade
1. Check if old volume exists: `docker volume ls | grep dockmon`
2. If volume exists, mount it manually: `docker run -v dockmon_dockmon_data:/data alpine ls /data`
3. Copy data out: `docker run -v dockmon_dockmon_data:/source -v $(pwd):/dest alpine cp -r /source/. /dest/recovered-data/`

### Version Compatibility
- Database schema changes are handled automatically by migration scripts
- Configuration format changes are documented in release notes
- Always backup before major version upgrades

## Best Practices

1. **Always use bind mounts** (`./dockmon-data:/app/data`) for production
2. **Regular backups** of the database file
3. **Test upgrades** in staging environment first
4. **Read release notes** before upgrading

## Automated Backup Script

```bash
#!/bin/bash
# backup-dockmon.sh
DATE=$(date +%Y%m%d-%H%M%S)
mkdir -p ./backups
docker exec dockmon cp /app/data/dockmon.db /tmp/backup-$DATE.db
docker cp dockmon:/tmp/backup-$DATE.db ./backups/dockmon-backup-$DATE.db
echo "Backup created: ./backups/dockmon-backup-$DATE.db"
```

Run before each upgrade: `./backup-dockmon.sh`