# Deployments

DockMon's deployment system provides a powerful, automated way to deploy single containers or multi-container stacks with real-time progress tracking, security validation, and rollback support.

## Table of Contents

1. [Overview](#overview)
2. [Deployment Types](#deployment-types)
3. [Deployment Lifecycle](#deployment-lifecycle)
4. [Creating Deployments](#creating-deployments)
5. [Deployment Templates](#deployment-templates)
6. [Security Validation](#security-validation)
7. [Progress Tracking](#progress-tracking)
8. [Rollback and Recovery](#rollback-and-recovery)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

## Overview

The deployment system automates container lifecycle operations with:

- **Automated Deployment**: Pull images, create containers, start services
- **Real-time Progress**: Live updates via WebSocket during deployment
- **Security Validation**: Pre-deployment security checks with multiple severity levels
- **Rollback Support**: Automatic cleanup on failure
- **Template System**: Save and reuse configurations with variable substitution
- **Stack Support**: Deploy multi-container applications using Docker Compose

### Key Features

- 7-state deployment state machine with granular progress tracking
- Security validation for privileged access, dangerous mounts, and more
- Commitment point tracking for safe rollback operations
- Template variables for parameterized deployments
- Real-time WebSocket updates for progress and errors
- Support for both single containers and Docker Compose stacks

## Deployment Types

### Container Deployments

Deploy a single container with specified configuration.

**Use Cases:**
- Single-service applications (web servers, databases, etc.)
- Simple containerized tools
- Testing and development environments

**Example Configuration:**
```json
{
  "image": "nginx:1.25-alpine",
  "name": "my-nginx",
  "ports": ["8080:80"],
  "environment": {
    "NGINX_HOST": "example.com"
  },
  "volumes": [
    "nginx-data:/usr/share/nginx/html:ro"
  ],
  "restart_policy": {"Name": "unless-stopped"},
  "mem_limit": "512m",
  "cpus": 0.5
}
```

### Stack Deployments

Deploy multi-container applications using Docker Compose syntax.

**Use Cases:**
- Multi-service applications (web + database + cache)
- Complex microservice architectures
- Applications with service dependencies

**Example Docker Compose YAML:**
```yaml
version: '3.8'
services:
  web:
    image: nginx:alpine
    ports:
      - '8080:80'
  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: secret
```

**Note:** In the deployment form, paste this YAML into the Compose YAML field.

## Deployment Lifecycle

### State Machine (7 States)

Deployments progress through a well-defined state machine:

```
planning → validating → pulling_image → creating → starting → running
              ↓              ↓            ↓           ↓
              +--------------+------------+-----------+
                             ↓
                          failed
                             ↓
                       rolled_back (optional)
```

### State Descriptions

| State | Description | Progress | Duration |
|-------|-------------|----------|----------|
| **planning** | Deployment created, not started | 0% | Instant |
| **validating** | Security validation in progress | 0-10% | <1 second |
| **pulling_image** | Downloading container image(s) | 10-50% | Varies by image size |
| **creating** | Creating container in Docker | 50-70% | <5 seconds |
| **starting** | Starting container | 70-90% | <5 seconds |
| **running** | Container healthy and running | 100% | Terminal state |
| **failed** | Error occurred during deployment | 100% | Terminal state |
| **rolled_back** | Failed deployment cleaned up | 100% | Terminal state |

### Commitment Point

Once a container is successfully **created** in Docker, the deployment is marked as "committed". This prevents rollback operations from destroying successfully created containers, even if post-creation steps fail (like health checks).

**Why This Matters:**
- Prevents data loss from destroying containers that were successfully created
- Allows manual recovery when automated health checks fail
- Maintains consistency between Docker state and DockMon database

## Creating Deployments

### Creating a Deployment

1. Navigate to **Deployments** page
2. Click **New Deployment**
3. Select **host** from dropdown
4. Choose **deployment type**: Container or Stack
5. Configure deployment:
   - **Container**: Fill in image, ports, environment, volumes, etc.
   - **Stack**: Provide Docker Compose YAML
6. Click **Create Deployment**
7. Click **Execute** to start deployment

The deployment will begin executing and you'll see real-time progress updates in the UI.

### Configuration Options

#### Container Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | string | Yes | Docker image (e.g., `nginx:alpine`) |
| `name` | string | No | Container name (auto-generated if not provided) |
| `ports` | array | No | Port mappings (e.g., `["8080:80"]`) |
| `environment` | object | No | Environment variables (key-value pairs) |
| `volumes` | array | No | Volume mounts (e.g., `["data:/app/data"]`) |
| `networks` | array | No | Docker networks to connect to |
| `restart_policy` | object | No | Restart policy (e.g., `{"Name": "unless-stopped"}`) |
| `mem_limit` | string | No | Memory limit (e.g., `"512m"`) |
| `cpus` | number | No | CPU limit (e.g., `0.5` for half CPU) |
| `privileged` | boolean | No | Run in privileged mode (triggers security warning) |
| `cap_add` | array | No | Add Linux capabilities |
| `cap_drop` | array | No | Drop Linux capabilities |
| `network_mode` | string | No | Network mode (e.g., `"host"`, `"bridge"`) |
| `hostname` | string | No | Container hostname |
| `user` | string | No | User to run as (e.g., `"1000:1000"`) |
| `working_dir` | string | No | Working directory inside container |
| `command` | string/array | No | Command to run (overrides image CMD) |
| `entrypoint` | string/array | No | Entrypoint (overrides image ENTRYPOINT) |
| `labels` | object | No | Container labels (key-value pairs) |

#### Stack Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `compose_yaml` | string | Yes | Docker Compose YAML definition |
| `variables` | object | No | Template variable values (if using template) |

## Deployment Templates

Templates allow you to save reusable deployment configurations with variable substitution.

### Template Benefits

- **Reusability**: Deploy the same configuration multiple times
- **Parameterization**: Customize deployments with variables
- **Organization**: Categorize templates (web-servers, databases, monitoring)
- **Consistency**: Ensure deployments follow standards

### Creating Templates

**Via UI:**
1. Go to **Templates** page (from Deployments page)
2. Click **New Template**
3. Fill in template details:
   - Name (e.g., "Nginx Web Server")
   - Category (e.g., "web-servers")
   - Description
   - Deployment type (container or stack)
4. Define template with variables using `${VARIABLE}` syntax
5. Define variable schemas (default values, types, descriptions)
6. Save template

**Example Template:**
```json
{
  "name": "PostgreSQL Database",
  "category": "databases",
  "deployment_type": "container",
  "template_definition": {
    "image": "postgres:${VERSION}",
    "environment": {
      "POSTGRES_PASSWORD": "${DB_PASSWORD}",
      "POSTGRES_DB": "${DB_NAME}",
      "POSTGRES_USER": "${DB_USER}"
    },
    "ports": ["${PORT}:5432"],
    "volumes": ["${VOLUME_NAME}:/var/lib/postgresql/data"],
    "mem_limit": "${MEMORY_LIMIT}",
    "restart_policy": {"Name": "unless-stopped"}
  },
  "variables": {
    "VERSION": {
      "default": "16-alpine",
      "type": "string",
      "description": "PostgreSQL version"
    },
    "DB_PASSWORD": {
      "default": "",
      "type": "password",
      "required": true,
      "description": "Database root password"
    },
    "DB_NAME": {
      "default": "mydb",
      "type": "string",
      "description": "Initial database name"
    },
    "DB_USER": {
      "default": "postgres",
      "type": "string",
      "description": "Database user"
    },
    "PORT": {
      "default": 5432,
      "type": "integer",
      "description": "Host port to expose"
    },
    "VOLUME_NAME": {
      "default": "postgres-data",
      "type": "string",
      "description": "Volume name for data persistence"
    },
    "MEMORY_LIMIT": {
      "default": "2g",
      "type": "string",
      "description": "Memory limit"
    }
  }
}
```

### Using Templates

1. From Deployments page, click **New Deployment**
2. Click **From Template** button
3. Select a template
4. Fill in variable values (or use defaults)
5. Review generated configuration
6. Create and execute deployment

### Variable Substitution

Template variables use `${VARIABLE_NAME}` syntax and are replaced at deployment time.

**Variable Types:**
- `string`: Text value
- `integer`: Numeric value
- `boolean`: True/false
- `password`: Sensitive string (hidden in UI)

**Variable Rules:**
- Variable names must be UPPERCASE with underscores (e.g., `DB_PASSWORD`)
- Variables can have default values
- Variables can be marked as `required` (must be provided)
- Undefined variables in templates will keep the `${VAR}` placeholder

### Saving Deployments as Templates

After creating a successful deployment, you can save it as a template for reuse:

1. From Deployments list, click **Save as Template** icon
2. Enter template name and category
3. Optionally mark fields as variables (e.g., replace `8080` with `${PORT}`)
4. Save template

## Security Validation

All deployments undergo security validation before execution. The system checks for common security issues and categorizes them by severity.

### Security Levels

| Level | Numeric | Behavior | Description |
|-------|---------|----------|-------------|
| **CRITICAL** | 4 | Blocks deployment | Must be explicitly overridden |
| **HIGH** | 3 | Strong warning | Deployment allowed but discouraged |
| **MEDIUM** | 2 | Warning | User should review |
| **LOW** | 1 | Informational | Best practice recommendation |
| **INFO** | 0 | Note | No action required |

### Security Checks

#### CRITICAL Issues (Block Deployment)

**Privileged Containers:**
```
privileged: true
```
- **Risk**: Disables all security isolation, grants full host access
- **Recommendation**: Use specific capabilities instead (`cap_add`)

**Dangerous Volume Mounts:**
```
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - /:/host
```
- **Risk**: Container escape, full Docker API access
- **Recommendation**: Mount only specific directories needed
- **Note**: Read-only mounts (`:/path:ro`) reduce severity to HIGH

#### HIGH Issues (Strong Warning)

**Host Network Mode:**
```
network_mode: "host"
```
- **Risk**: Bypasses network isolation, exposes all host ports
- **Recommendation**: Use port mappings instead

**Dangerous Linux Capabilities:**
```
cap_add:
  - SYS_ADMIN
  - SYS_MODULE
  - SYS_RAWIO
```
- **Risk**: Container escape, kernel module loading, hardware access
- **Recommendation**: Use minimal capabilities or none

**Dangerous Mount Paths:**
```
volumes:
  - /etc:/host-etc
  - /proc:/host-proc
  - /sys:/host-sys
  - /boot:/host-boot
  - /dev:/host-dev
```
- **Risk**: Access to sensitive host configuration
- **Recommendation**: Mount only application-specific directories

#### MEDIUM Issues (Warning)

**Plaintext Secrets in Environment:**
```
environment:
  DB_PASSWORD: "my-password-123"
  API_KEY: "secret-key"
```
- **Risk**: Secrets visible in Docker inspect, logs, and process lists
- **Recommendation**: Use Docker secrets or external secret management

**Dangerous Network Capabilities:**
```
cap_add:
  - NET_ADMIN
```
- **Risk**: Network administration privileges
- **Recommendation**: Use only if absolutely necessary

**Excessive Memory Limits:**
```
mem_limit: "32g"
```
- **Risk**: Resource exhaustion
- **Recommendation**: Set reasonable limits based on application needs

#### LOW Issues (Informational)

**Missing Resource Limits:**
```
# No mem_limit, cpus, or cpu_shares specified
```
- **Risk**: Container can consume all available resources
- **Recommendation**: Set memory and CPU limits

**Using :latest Tag:**
```
image: "nginx:latest"
```
- **Risk**: Unpredictable updates, lack of reproducibility
- **Recommendation**: Use specific version tags (e.g., `nginx:1.25-alpine`)

### Security Check Enforcement

CRITICAL security issues will block deployment. There is currently no way to override these checks in the UI for safety reasons.

**If you encounter a CRITICAL security violation:**
1. **Fix the security issue** (strongly recommended) - Remove privileged mode, dangerous mounts, etc.
2. **Understand the risk** - If you must proceed, manually deploy the container using `docker run` commands outside of DockMon

HIGH, MEDIUM, and LOW warnings will not block deployment but should be reviewed and addressed when possible.

## Progress Tracking

Deployments provide real-time progress updates via WebSocket.

### Progress Stages

**Validation (0-10%):**
- Security validation
- Configuration validation
- Pre-flight checks

**Image Pull (10-50%):**
- Downloading container image layers
- Layer-by-layer progress tracking
- Progress varies by image size and network speed

**Container Creation (50-70%):**
- Creating container in Docker
- Resource allocation
- Network configuration
- Volume mounting

**Container Start (70-90%):**
- Starting container process
- Initial startup checks

**Health Check (90-100%):**
- Waiting for container to be healthy
- Running health check commands
- Verifying container is responsive

### Real-time Updates

The Deployments page automatically receives real-time updates via WebSocket connection:

- **Progress bar** updates as deployment progresses
- **Status badge** changes as deployment transitions through states
- **Stage description** shows current operation (e.g., "Pulling image", "Starting container")
- **Error messages** appear immediately if deployment fails

You don't need to refresh the page - all updates happen automatically.

### Layer-by-Layer Progress

During image pull, DockMon tracks individual layer downloads:

```
Pulling image nginx:1.25-alpine
├─ Layer 1/5: 100% [===================] 2.8 MB
├─ Layer 2/5: 100% [===================] 1.2 MB
├─ Layer 3/5:  45% [=========>---------] 5.1 MB
├─ Layer 4/5:   0% [-------------------] 12.3 MB
└─ Layer 5/5:   0% [-------------------] 1.5 MB

Overall: 35% complete
```

## Rollback and Recovery

### Automatic Rollback

When a deployment fails, DockMon automatically attempts to clean up:

**Rollback Behavior:**
- Removes created containers
- Cleans up resources (networks, volumes if not in use)
- Transitions deployment to `rolled_back` state

**Rollback Conditions:**
1. Deployment has NOT reached commitment point
2. Deployment is in a rollback-eligible state (validating, pulling_image, creating, starting, or failed)

### Commitment Point Protection

The commitment point prevents rollback from destroying successfully created containers.

**Example Scenario:**
1. Container created successfully in Docker ✓
2. Deployment marked as "committed" ✓
3. Health check fails (timeout) ✗
4. Rollback is **NOT** performed (container preserved)

**Why?**
- Container was successfully created
- Failure might be temporary (slow startup)
- User can manually investigate and fix
- Prevents data loss from destroying working containers

### Manual Recovery

For failed deployments with `committed=true`:

1. **Check Container Logs:**
   ```bash
   docker logs <container-id>
   ```

2. **Inspect Container:**
   ```bash
   docker inspect <container-id>
   ```

3. **Restart Container:**
   ```bash
   docker restart <container-id>
   ```

4. **Fix and Redeploy:**
   - Update deployment configuration
   - Delete failed deployment
   - Create new deployment with fixes

### Failed Deployment States

| State | Committed | Rollback Performed | Container Status |
|-------|-----------|-------------------|------------------|
| **failed** | No | Yes (automatic) | Removed |
| **failed** | Yes | No (protected) | Exists, may be running |
| **rolled_back** | No | Yes | Removed successfully |

## Best Practices

### Deployment Configuration

1. **Use Specific Image Tags:**
   ```json
   {"image": "nginx:1.25-alpine"}  // Good
   {"image": "nginx:latest"}        // Avoid
   ```

2. **Set Resource Limits:**
   ```json
   {
     "mem_limit": "512m",
     "cpus": 0.5
   }
   ```

3. **Use Restart Policies:**
   ```json
   {"restart_policy": {"Name": "unless-stopped"}}
   ```

4. **Avoid Privileged Mode:**
   ```json
   {"privileged": false}  // Default, secure
   {"cap_add": ["NET_BIND_SERVICE"]}  // Use capabilities instead
   ```

5. **Mount Volumes with Minimal Permissions:**
   ```json
   {"volumes": [
     "app-data:/app/data",           // Read-write for data
     "/path/to/config:/config:ro"    // Read-only for config
   ]}
   ```

### Template Design

1. **Parameterize Configuration:**
   - Use variables for ports, versions, credentials
   - Provide sensible defaults
   - Mark sensitive variables as `password` type

2. **Document Variables:**
   ```json
   {
     "VERSION": {
       "default": "1.25",
       "type": "string",
       "description": "Application version to deploy"
     }
   }
   ```

3. **Organize with Categories:**
   - Use categories like `web-servers`, `databases`, `monitoring`
   - Makes templates easier to find

4. **Test Templates:**
   - Deploy from template before sharing
   - Verify all variables work correctly
   - Test with default values

### Security

1. **Review Security Warnings:**
   - Always review HIGH and MEDIUM warnings
   - Fix CRITICAL issues before deployment
   - Understand the risks before proceeding

2. **Use Docker Secrets:**
   ```yaml
   environment:
     DB_PASSWORD_FILE: /run/secrets/db_password  # Good
     # DB_PASSWORD: "plaintext"  # Avoid
   ```

3. **Limit Network Exposure:**
   - Only expose ports that need to be public
   - Use internal Docker networks for service communication

4. **Drop Unnecessary Capabilities:**
   ```json
   {
     "cap_drop": ["ALL"],
     "cap_add": ["NET_BIND_SERVICE"]
   }
   ```

### Monitoring

1. **Watch Deployment Progress:**
   - Monitor real-time progress in UI
   - Check for warnings or errors
   - Review logs if deployment fails

2. **Verify Deployment Success:**
   - Check container is running
   - Test application endpoints
   - Review container logs

3. **Use Health Checks:**
   ```json
   {
     "healthcheck": {
       "test": ["CMD", "curl", "-f", "http://localhost/health"],
       "interval": "30s",
       "timeout": "10s",
       "retries": 3
     }
   }
   ```

## Troubleshooting

### Deployment Stuck in "pulling_image"

**Cause:** Large image or slow network

**Solution:**
- Wait for image download to complete
- Check network connectivity
- Consider deploying a smaller image variant
- Pull image manually first: `docker pull <image>`

### Deployment Fails with "Image not found"

**Cause:** Invalid image name or tag

**Solution:**
- Verify image exists on Docker Hub or registry
- Check spelling and tag
- Use `docker pull <image>` to test manually
- Check registry credentials if using private registry

### Deployment Fails with "Port already in use"

**Cause:** Another container using the same host port

**Solution:**
- Change host port in deployment configuration
- Stop conflicting container
- Check with: `docker ps` and look for port mappings

### Deployment Fails with "Health check timeout"

**Cause:** Container takes too long to start or health check misconfigured

**Solution:**
- Increase health check timeout in Settings
- Check container logs: `/logs` page
- Verify health check command is correct
- Container might need more resources (increase memory limit)

### Deployment Fails with Security Violation

**Cause:** CRITICAL security issue detected

**Solution:**
- Review security error message
- Fix the security issue (recommended)
  - Remove `privileged: true`
  - Remove dangerous volume mounts
  - Use specific capabilities instead
- Or contact administrator for override

### Container Created But Marked as Failed

**Cause:** Post-creation step failed (health check, etc.)

**Note:** Container is preserved (commitment point protection)

**Solution:**
1. Check container status: `docker ps -a`
2. Check logs from Logs page or `docker logs <container-id>`
3. Investigate and fix issue
4. Option A: Fix and restart container
5. Option B: Delete deployment and recreate with fixes

### Rollback Not Performed After Failure

**Cause:** Deployment reached commitment point

**Explanation:**
- Container was successfully created
- Rollback would destroy working container
- This is intentional for data safety

**Solution:**
- Manually stop and remove container if needed
- Or investigate and fix the container

### Stack Deployment Fails with "Service dependency error"

**Cause:** Services started in wrong order

**Solution:**
- Add `depends_on` to Docker Compose YAML
- Ensure dependency services are healthy before starting dependent services

### Template Variables Not Substituted

**Cause:** Variable name mismatch or undefined variable

**Solution:**
- Check variable name matches exactly (case-sensitive)
- Verify variable is defined in template `variables` section
- Use format: `${VARIABLE_NAME}` (uppercase with underscores)
- Ensure variable value provided when deploying from template


---

**Related Pages:**
- [Container Operations](Container-Operations)
- [Managing Hosts](Managing-Hosts)
- [Settings](Settings)
- [Security Guide](Security-Guide)
