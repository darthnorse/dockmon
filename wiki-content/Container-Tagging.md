# Container Tagging

Organize and filter your containers with powerful tagging capabilities in DockMon v2.

---

## Overview

Container tagging helps you organize, categorize, and quickly filter large numbers of containers across multiple hosts. DockMon v2 supports both **automatic tag derivation** from Docker labels and **custom user-defined tags** for maximum flexibility.

**Key features:**
- **Automatic tags** - Derived from Docker Compose, Swarm, and custom labels
- **Custom tags** - Add your own tags for organizational purposes
- **Tag-based filtering** - Instantly filter dashboard to show specific containers
- **Bulk tag operations** - Add/remove tags from multiple containers at once
- **Persistent storage** - Tags are preserved across container restarts

---

## Automatic Tag Derivation

DockMon automatically extracts tags from standard Docker labels without any configuration. These tags update automatically when containers are created or restarted.

### Supported Label Sources

#### Docker Compose Projects

**Label:** `com.docker.compose.project`

**Derived tag format:** `compose:{project_name}`

**Example:**
```yaml
# docker-compose.yml
version: '3'
services:
  web:
    image: nginx
  db:
    image: postgres
```

When deployed with `docker-compose up`, DockMon automatically tags both containers with `compose:myproject` (based on the directory name or `-p` flag).

**Use case:** Group all containers from the same Compose project for easy filtering and management.

#### Docker Swarm Services

**Label:** `com.docker.swarm.service.name`

**Derived tag format:** `swarm:{service_name}`

**Example:**
```bash
docker service create --name web-cluster nginx
```

DockMon automatically tags containers with `swarm:web-cluster`.

**Use case:** Identify containers managed by Docker Swarm.

#### Custom DockMon Labels

**Label:** `dockmon.tag`

**Format:** Comma-separated list of tags

**Derived tag format:** Tags are used as-is (not prefixed)

**Example:**
```bash
docker run -d \
  --label dockmon.tag="production,critical,web" \
  --name my-app \
  nginx
```

DockMon automatically tags the container with: `production`, `critical`, `web`

**Use case:** Define tags at container creation time for infrastructure-as-code setups.

### How Automatic Tags Work

1. **Container discovery** - DockMon scans all containers on all hosts
2. **Label extraction** - Reads Docker labels from each container
3. **Tag derivation** - Applies tag rules to extract tags
4. **Tag combination** - Merges automatic tags with user-defined custom tags
5. **Display** - Shows all tags in the dashboard

**Important:** Automatic tags are **read-only** in the UI. You cannot delete them through DockMon - they're derived from Docker labels. To remove an automatic tag, change the Docker label and recreate the container.

---

## Custom Tags

Custom tags are user-defined tags that you add directly through DockMon's interface. Unlike automatic tags, custom tags persist in DockMon's database and are independent of Docker labels.

### Adding Custom Tags

#### Method 1: Single Container

1. Navigate to the **Container Dashboard**
2. Find the container you want to tag
3. Click on the container to open the **Container Details** view
4. Go to the **Tags** tab
5. Click **Add Tag**
6. Enter the tag name (alphanumeric, hyphens, underscores)
7. Press **Enter** or click outside the input

**Examples of good tag names:**
- `production`
- `staging`
- `critical`
- `needs-update`
- `monitoring-disabled`
- `web-tier`
- `db-tier`

**Tag naming best practices:**
- Use lowercase for consistency
- Use hyphens for multi-word tags (`web-tier`, not `web_tier` or `webTier`)
- Keep tags short and descriptive
- Avoid spaces (they're not allowed)

#### Method 2: Bulk Tag Operations

1. Navigate to the **Container Dashboard**
2. Enable **Bulk Select** mode (checkbox icon in toolbar)
3. Check the containers you want to tag
4. Click **Bulk Actions** dropdown
5. Select **Add Tags**
6. Enter tag(s) to add (comma-separated for multiple)
7. Click **Apply**
8. Monitor progress in the bulk operation status panel

**Use case:** Tag all production containers or all containers from a specific host at once.

See [Bulk Operations](Bulk-Operations) for detailed bulk tagging workflows.

### Removing Custom Tags

#### Method 1: Single Container

1. Open **Container Details** view
2. Go to **Tags** tab
3. Click the **X** icon next to the tag you want to remove
4. Tag is removed immediately

#### Method 2: Bulk Remove Tags

1. Enable **Bulk Select** mode
2. Select containers
3. Click **Bulk Actions** → **Remove Tags**
4. Enter tag(s) to remove
5. Click **Apply**

**Note:** You can only remove **custom tags** through the UI. Automatic tags (like `compose:myproject`) cannot be removed - they're derived from Docker labels.

### Tag Display

Tags appear as colored badges in the container list:

- **Automatic tags** - Displayed with a subtle icon (e.g., compose icon for Compose tags)
- **Custom tags** - Displayed as plain text badges
- **Tag colors** - Assigned automatically based on tag name for visual consistency

---

## Filtering Containers by Tags

Tag-based filtering is one of the most powerful features for managing large container fleets.

### Using the Tag Filter

1. Navigate to the **Container Dashboard**
2. Find the **Filter by Tags** dropdown in the toolbar
3. Click to open the tag selector
4. Check one or more tags to filter
5. Dashboard updates instantly to show only matching containers

**Filter behavior:**
- **Multiple tags selected** - Shows containers that have **ANY** of the selected tags (OR logic)
- **No tags selected** - Shows all containers (no filter)
- **Tag count badge** - Shows how many containers have each tag

**Example workflow:**
```
1. Select tag "production" → Shows 45 containers
2. Also select tag "web-tier" → Shows 67 containers (production OR web-tier)
3. Clear filters → Shows all 150 containers
```

### Clearing Tag Filters

Click the **Clear Filters** button or uncheck all tags in the tag selector.

### Combining Filters

Tag filters can be combined with other filters:

- **Search** - Filter by tag AND search container name
- **Host filter** - Filter by tag AND specific host
- **State filter** - Filter by tag AND container state (running, stopped, etc.)

**Example:**
```
Tags: "production" + "critical"
Host: "Production-Server"
State: "exited"
→ Shows critical production containers that are stopped on Production-Server
```

This is extremely useful for incident response and troubleshooting.

---

## Tag Management Best Practices

### Organizational Strategies

#### By Environment

```
production
staging
development
qa
```

**Use case:** Quickly filter containers by deployment environment.

**Example:** Show only production containers during incident response.

#### By Tier/Function

```
web-tier
app-tier
db-tier
cache-tier
queue-tier
```

**Use case:** Organize containers by their role in the application stack.

**Example:** Restart all cache containers during maintenance.

#### By Criticality

```
critical
important
standard
```

**Use case:** Prioritize monitoring and alerts.

**Example:** Set up alert rules that only trigger for "critical" containers.

#### By Team/Owner

```
platform-team
frontend-team
backend-team
data-team
```

**Use case:** Filter containers by team ownership for delegation.

**Example:** Show only containers owned by the backend team.

#### By Maintenance Status

```
needs-update
needs-restart
monitoring-disabled
auto-restart-disabled
```

**Use case:** Track containers that need attention.

**Example:** Bulk update all containers tagged "needs-update".

### Tag Naming Conventions

**Do:**
- ✅ Use lowercase (`production`, not `Production`)
- ✅ Use hyphens for multi-word tags (`web-tier`, not `web_tier`)
- ✅ Keep tags short and memorable (`prod`, `staging`, `db`)
- ✅ Be consistent across your organization
- ✅ Use namespacing for complex setups (`team:backend`, `env:prod`)

**Don't:**
- ❌ Use spaces (not allowed)
- ❌ Use special characters except hyphens and underscores
- ❌ Create too many overlapping tags (causes filter fatigue)
- ❌ Use vague tags (`misc`, `other`, `temp`)

### Tag Lifecycle Management

**Review tags regularly:**
- Remove unused tags (containers no longer exist)
- Consolidate similar tags (`prod` + `production` → `production`)
- Update tag naming conventions as your organization grows

**Document your tagging strategy:**
- Maintain a wiki page or document listing standard tags
- Share tagging conventions with your team
- Include tag strategy in onboarding documentation

---

## Advanced: Tag-Based Automation

### Alert Rules with Tags

Create alert rules that target specific tags:

1. Navigate to **Alert Rules**
2. Click **Create Rule**
3. In **Container Selection**, use tag filtering to select containers
4. Configure alert conditions
5. Save rule

**Example:** Alert when ANY container tagged "critical" goes down.

See [Alert Rules](Alert-Rules) for details.

### Bulk Operations with Tags

Tag-based filtering makes bulk operations powerful:

**Scenario:** Update all staging containers

1. Filter by tag: `staging`
2. Enable bulk select
3. Select all visible containers
4. Click **Bulk Actions** → **Restart**
5. Containers restart in parallel with rate limiting

See [Bulk Operations](Bulk-Operations) for details.

### Auto-Update by Tag

Configure automatic updates for containers with specific tags:

**Example:** Enable auto-updates for all containers tagged "auto-update"

1. Filter by tag: `auto-update`
2. Select containers
3. Bulk Actions → **Set Auto-Update** → Enable

See [Automatic Updates](Automatic-Updates) for details.

---

## Tag Persistence and Container Lifecycle

### What Happens When...

#### Container is restarted

- **Automatic tags** - Re-derived from Docker labels (may change if labels changed)
- **Custom tags** - Preserved in DockMon database (no change)

#### Container is removed and recreated

- **Automatic tags** - Re-derived from new container's labels
- **Custom tags** - Lost (container ID changes, no way to link old and new)

**Recommendation:** Use `dockmon.tag` labels for tags that should survive container recreation.

#### Container is renamed

- **Automatic tags** - Updated if derived from name-based labels
- **Custom tags** - Preserved (tracked by container ID, not name)

#### Host is removed

- **All tags** - Deleted when host is removed from DockMon

### Tag Storage

- **Automatic tags** - Not stored in database (derived on-the-fly)
- **Custom tags** - Stored in `container_desired_states` table
- **Format** - Comma-separated string in `custom_tags` column
- **Lookup key** - Uses composite key `{host_id}:{container_id}` to prevent collisions

---

## Troubleshooting

### Tags Not Appearing

**Symptom:** Container has labels but no automatic tags show up.

**Check:**
1. Verify label format: `com.docker.compose.project=myproject` (not `com-docker-compose-project`)
2. Refresh the container list (automatic tags update every 10 seconds)
3. Check container details to see raw Docker labels
4. Ensure label value is not empty

**Solution:** Fix Docker labels and recreate container.

### Custom Tags Lost After Container Restart

**This is normal behavior.** Custom tags are tied to container ID, which changes when a container is removed and recreated.

**Workaround:** Use `dockmon.tag` labels in your Compose files or Dockerfiles:

```yaml
# docker-compose.yml
services:
  web:
    image: nginx
    labels:
      - dockmon.tag=production,web-tier,critical
```

### Too Many Tags

**Symptom:** Tag selector is cluttered with dozens of tags.

**Solutions:**
1. **Consolidate tags** - Merge similar tags (`prod` + `production` → `production`)
2. **Delete unused tags** - Remove tags from all containers, they'll disappear from the selector
3. **Use namespacing** - Group related tags (`team:frontend`, `team:backend`)
4. **Review tag strategy** - Revisit your tagging conventions

### Tag Filter Shows Wrong Containers

**Symptom:** Container appears in filter but doesn't have the selected tag.

**Cause:** Multiple tags selected (OR logic).

**Explanation:** Selecting multiple tags shows containers with **ANY** of the selected tags, not ALL.

**Example:**
```
Selected tags: "production", "staging"
Container A has: production
Container B has: staging
→ Both containers appear in results
```

**Workaround:** Use search + tag filter to narrow results further.

---

## Related Documentation

- [Bulk Operations](Bulk-Operations) - Tag multiple containers at once
- [Alert Rules](Alert-Rules) - Create alerts based on tags
- [Automatic Updates](Automatic-Updates) - Auto-update tagged containers
- [Container Operations](Container-Operations) - Manage tagged containers

---

## Examples

### Example 1: Organizing a Microservices Stack

**Setup:**
```yaml
# docker-compose.yml for e-commerce platform
version: '3'
services:
  frontend:
    image: shop-frontend
    labels:
      - dockmon.tag=web-tier,customer-facing
  api:
    image: shop-api
    labels:
      - dockmon.tag=app-tier,customer-facing
  admin-panel:
    image: shop-admin
    labels:
      - dockmon.tag=web-tier,internal
  database:
    image: postgres
    labels:
      - dockmon.tag=db-tier,critical
  redis:
    image: redis
    labels:
      - dockmon.tag=cache-tier
```

**Result in DockMon:**
- `frontend` → tags: `compose:shop`, `web-tier`, `customer-facing`
- `api` → tags: `compose:shop`, `app-tier`, `customer-facing`
- `admin-panel` → tags: `compose:shop`, `web-tier`, `internal`
- `database` → tags: `compose:shop`, `db-tier`, `critical`
- `redis` → tags: `compose:shop`, `cache-tier`

**Use cases:**
- Filter by `customer-facing` to see public-facing services
- Filter by `critical` to monitor essential services
- Filter by `compose:shop` to see entire stack

### Example 2: Multi-Environment Management

**Tag strategy:**
```
Environment tags:
- production
- staging
- development

Critical tags:
- critical (require 24/7 monitoring)
- important (monitor during business hours)
- standard (basic monitoring)
```

**Workflow:**
1. Deploy containers with `dockmon.tag=production,critical`
2. DockMon automatically tags them
3. Create alert rule targeting "critical" tag
4. Create separate alert rule for "production" tag with different channels
5. Filter dashboard by "production" to see only prod containers

### Example 3: Team-Based Container Ownership

**Tag strategy:**
```
team:platform
team:frontend
team:backend
team:data
team:security
```

**Setup:**
```bash
# Platform team's containers
docker run -d --label dockmon.tag=team:platform nginx

# Frontend team's containers
docker run -d --label dockmon.tag=team:frontend react-app

# Backend team's containers
docker run -d --label dockmon.tag=team:backend api-server
```

**Use cases:**
- Filter by `team:backend` to see backend team's containers
- Create alert rules per team with different notification channels
- Delegate monitoring responsibilities by tag

---

## Need Help?

- [Troubleshooting Guide](Troubleshooting)
- [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Report an Issue](https://github.com/darthnorse/dockmon/issues)
